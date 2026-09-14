"""Pure, static target-registry loader.

Created once by the Stage 3 foundation task; ownership then transfers to Rayyan along
with the rest of ``endpoint/``.

Why this module is deliberately boring
--------------------------------------
Importing it must be free. ``endpoint/model.py`` loads a model at import time, so
anything that reaches it turns "read the config" into "download and load weights".
Nothing here imports ``endpoint.model``, ``endpoint.v1``, ``endpoint.v2``,
``transformers`` or ``torch``. ``TargetSpec.module`` is a dotted *string*; it is never
imported, only recorded. That is what lets the runner, the orchestrator, the analysis
and ``--help`` all read the registry without paying for a model load.

What is validated when, and why the split matters
-------------------------------------------------
``load_registry`` validates everything that is knowable from the file alone: that every
cross-reference resolves, that revisions are real 40-hex pins, that ports do not collide,
that a target's declared task exists, and that configured paths are syntactically sane
repo-relative paths. It does **not** check that a file or module exists on disk.

That split is the point. ``endpoint/sentiment_v1.py`` (Task 2) and
``baseline/sentiment_baseline.json`` (Task 4) do not exist yet. If loading the registry
required them, the foundation would break the existing emotion path for everyone until
both land. Existence is checked by :func:`require_runnable`, which the orchestrator calls
for the one evaluation it is about to execute.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional, Union

from contract import (
    ContractError,
    EvaluationSpec,
    ModelSpec,
    Registry,
    TargetSpec,
    TaskSpec,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_REGISTRY_PATH = HERE / "targets.json"

# A repo-relative path: forward slashes, no drive letter, no leading slash, no "..".
# Checked as syntax only; existence is a separate, later question.
_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
# A dotted Python module path. Also syntax only -- never imported here.
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class TargetConfigError(ContractError):
    """Raised when the registry file is missing, unparseable or internally inconsistent.

    Subclasses ``ContractError`` (and so ``ValueError``) so a caller can catch either the
    structural contract errors raised by the spec dataclasses or the wiring errors raised
    here with one ``except``.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TargetConfigError(message)


def _check_path_syntax(value: str, where: str) -> None:
    _require(bool(value), f"{where}: path must not be empty")
    _require(
        "\\" not in value,
        f"{where}: use forward slashes in repo-relative paths, got {value!r}",
    )
    _require(
        ".." not in value.split("/"),
        f"{where}: path must not escape the repository, got {value!r}",
    )
    _require(
        bool(_PATH_RE.match(value)),
        f"{where}: {value!r} is not a valid repo-relative path",
    )


def _obj(raw, where: str) -> dict:
    _require(isinstance(raw, dict), f"{where}: expected an object, got {type(raw).__name__}")
    return raw


def load_registry(path: Optional[Union[str, Path]] = None) -> Registry:
    """Parse and validate the static registry. Loads no models.

    Raises :class:`TargetConfigError` on anything structurally wrong, with a message that
    names the offending key. Returns an immutable :class:`contract.Registry`; there is no
    module-level singleton, so two callers cannot contaminate each other's view.
    """
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    try:
        raw_bytes = registry_path.read_bytes()
    except OSError as exc:
        raise TargetConfigError(f"cannot read registry {registry_path}: {exc}") from exc
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetConfigError(f"registry {registry_path} is not valid JSON: {exc}") from exc

    raw = _obj(raw, str(registry_path))
    version = raw.get("registry_version")
    _require(isinstance(version, str) and version, "registry_version is required")

    # --- models -----------------------------------------------------------------------
    models: dict[str, ModelSpec] = {}
    for key, entry in _obj(raw.get("models", {}), "models").items():
        where = f"models.{key}"
        entry = _obj(entry, where)
        labels = entry.get("labels")
        _require(
            isinstance(labels, list) and all(isinstance(x, str) for x in labels),
            f"{where}.labels must be a list of strings",
        )
        try:
            models[key] = ModelSpec(
                model_id=entry["model_id"],
                revision=entry["revision"],
                tokenizer_id=entry.get("tokenizer_id", entry["model_id"]),
                tokenizer_revision=entry.get("tokenizer_revision", entry["revision"]),
                labels=tuple(labels),
                max_sequence_length=int(entry["max_sequence_length"]),
                notes=entry.get("notes", ""),
            )
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        except ContractError as exc:
            raise TargetConfigError(f"{where}: {exc}") from None
    _require(bool(models), "registry declares no models")

    # --- tasks ------------------------------------------------------------------------
    tasks: dict[str, TaskSpec] = {}
    for key, entry in _obj(raw.get("tasks", {}), "tasks").items():
        where = f"tasks.{key}"
        entry = _obj(entry, where)
        try:
            model_ref = entry["model_ref"]
            baseline_file = entry["baseline_file"]
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        _require(
            model_ref in models,
            f"{where}.model_ref {model_ref!r} is not a configured model; "
            f"configured: {sorted(models)}",
        )
        _check_path_syntax(baseline_file, f"{where}.baseline_file")
        tasks[key] = TaskSpec(
            task_id=key,
            model_ref=model_ref,
            baseline_file=baseline_file,
            description=entry.get("description", ""),
        )
    _require(bool(tasks), "registry declares no tasks")

    # --- targets ----------------------------------------------------------------------
    targets: dict[str, TargetSpec] = {}
    ports: dict[int, str] = {}
    for key, entry in _obj(raw.get("targets", {}), "targets").items():
        where = f"targets.{key}"
        entry = _obj(entry, where)
        try:
            task_id = entry["task_id"]
            module = entry["module"]
            port = int(entry["port"])
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        _require(
            task_id in tasks,
            f"{where}.task_id {task_id!r} is not a configured task; configured: {sorted(tasks)}",
        )
        _require(
            bool(_MODULE_RE.match(module)),
            f"{where}.module {module!r} is not a dotted module path",
        )
        _require(
            1 <= port <= 65535, f"{where}.port {port} is outside the valid range"
        )
        _require(
            port not in ports,
            f"{where}.port {port} collides with target {ports.get(port)!r}; "
            "two targets cannot share a loopback port",
        )
        ports[port] = key
        try:
            targets[key] = TargetSpec(
                target_id=key,
                task_id=task_id,
                version=entry["version"],
                module=module,
                app_attr=entry.get("app_attr", "app"),
                port=port,
                hardened=bool(entry.get("hardened", False)),
                description=entry.get("description", ""),
            )
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        except ContractError as exc:
            raise TargetConfigError(f"{where}: {exc}") from None
    _require(bool(targets), "registry declares no targets")

    # --- evaluations ------------------------------------------------------------------
    evaluations: dict[str, EvaluationSpec] = {}
    for key, entry in _obj(raw.get("evaluations", {}), "evaluations").items():
        where = f"evaluations.{key}"
        entry = _obj(entry, where)
        target_ids = entry.get("target_ids")
        _require(
            isinstance(target_ids, list) and all(isinstance(x, str) for x in target_ids),
            f"{where}.target_ids must be a list of strings",
        )
        families = entry.get("declared_families")
        _require(
            isinstance(families, list) and all(isinstance(x, str) for x in families),
            f"{where}.declared_families must be a list of strings",
        )
        try:
            task_id = entry["task_id"]
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        _require(
            task_id in tasks,
            f"{where}.task_id {task_id!r} is not a configured task; configured: {sorted(tasks)}",
        )
        for target_id in target_ids:
            _require(
                target_id in targets,
                f"{where}: target {target_id!r} is not configured; "
                f"configured: {sorted(targets)}",
            )
            _require(
                targets[target_id].task_id == task_id,
                f"{where}: target {target_id!r} belongs to task "
                f"{targets[target_id].task_id!r}, not {task_id!r}. An evaluation cannot "
                "mix tasks.",
            )
        override = entry.get("baseline_file")
        if override is not None:
            _check_path_syntax(override, f"{where}.baseline_file")
        try:
            evaluations[key] = EvaluationSpec(
                evaluation_id=key,
                kind=entry["kind"],
                task_id=task_id,
                suite_id=entry["suite_id"],
                target_ids=tuple(target_ids),
                declared_families=tuple(families),
                case_set_id=entry.get("case_set_id"),
                baseline_file=override,
                mode=entry.get("mode", "standard"),
                description=entry.get("description", ""),
            )
        except KeyError as exc:
            raise TargetConfigError(f"{where}: missing required field {exc}") from None
        except ContractError as exc:
            raise TargetConfigError(f"{where}: {exc}") from None
    _require(bool(evaluations), "registry declares no evaluations")

    return Registry(
        registry_version=version,
        models=dict(models),
        tasks=dict(tasks),
        targets=dict(targets),
        evaluations=dict(evaluations),
        source_path=str(registry_path),
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def missing_requirements(
    registry: Registry, evaluation_id: str, root: Optional[Union[str, Path]] = None
) -> list[str]:
    """Which files this evaluation needs but does not have yet.

    Separate from :func:`load_registry` on purpose: a sentiment component that Task 2 or
    Task 4 has not written yet must not stop the existing emotion path from loading the
    registry. Returns repo-relative paths, empty when everything is present.
    """
    base = Path(root) if root is not None else ROOT
    spec = registry.evaluation(evaluation_id)
    missing: list[str] = []

    baseline_file = registry.baseline_file_for(evaluation_id)
    if not (base / baseline_file).is_file():
        missing.append(baseline_file)

    for target_id in spec.target_ids:
        module_rel = registry.target(target_id).module.replace(".", "/") + ".py"
        if not (base / module_rel).is_file():
            missing.append(module_rel)

    return missing


def require_runnable(
    registry: Registry, evaluation_id: str, root: Optional[Union[str, Path]] = None
) -> None:
    """Raise unless every file this evaluation needs exists.

    Call this immediately before executing an evaluation -- not at registry load.
    """
    missing = missing_requirements(registry, evaluation_id, root=root)
    if missing:
        raise TargetConfigError(
            f"evaluation {evaluation_id!r} cannot run yet; missing: {', '.join(missing)}"
        )

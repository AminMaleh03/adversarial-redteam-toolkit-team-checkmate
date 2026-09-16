"""
Frozen additional-evaluation (OCES) case loader.

OCES variants are authored, human-reviewed, FROZEN data (see attacks/data/oces/provenance.json
and freeze_provenance.json) -- never generated on the fly. This module's only job is to load
that frozen data safely: verify it is exactly the committed bytes before trusting a single
case from it, then register each case's metadata and hand back plain AttackCase objects in
file order. It builds nothing, mutates nothing, and authors no new case content.

Fails closed: a missing, modified, incompatible or wrong-generator-version artifact raises
ContractError rather than silently falling back to an empty, partial or relabelled suite.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from contract import AttackCase, BaselineCase, ContractError

from attacks import metadata as md

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = HERE / "data" / "oces"
HASH_MANIFEST_PATH = DATA_DIR / "freeze_content_hashes.json"

# The generator version the currently-committed frozen bytes were produced by (see
# freeze_provenance.json's integration_repair block: 1.2.0 -> 1.2.1 for LF byte
# reproducibility, content unchanged). A hash manifest claiming any other version is
# refused rather than trusted, even if its individual file hashes happen to verify.
REQUIRED_GENERATOR_VERSION = "1.2.1"

# Repo-relative paths, one per task, as recorded in freeze_content_hashes.json.
CASE_FILE_BY_TASK = {
    "emotion_7": DATA_DIR / "emotion_cases.json",
    "sentiment_2": DATA_DIR / "sentiment_cases.json",
}


def _verify_frozen_hashes() -> None:
    """Verify every one of the seven frozen OCES artifacts against its recorded hash.

    Reads attacks/data/oces/freeze_content_hashes.json -- the current authoritative record
    per freeze_provenance.json's own note ("read that file, not the frozen_artifacts_sha256
    above, for the current on-disk identity") -- and hashes the actual bytes on disk for
    every file it lists. Any missing file, any byte difference, a manifest that does not
    declare exactly seven files, or a generator_version other than the required one raises
    ContractError. This runs before a single case is read from the case files themselves.
    """
    try:
        raw = HASH_MANIFEST_PATH.read_bytes()
    except OSError as exc:
        raise ContractError(
            f"OCES frozen hash manifest unreadable: {HASH_MANIFEST_PATH}: {exc}"
        ) from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"OCES frozen hash manifest is not valid JSON: {exc}") from exc

    if manifest.get("generator_version") != REQUIRED_GENERATOR_VERSION:
        raise ContractError(
            f"OCES frozen hash manifest declares generator_version "
            f"{manifest.get('generator_version')!r}, but this loader requires "
            f"{REQUIRED_GENERATOR_VERSION!r}. Refusing to load data from an unexpected "
            "generator version."
        )

    files = manifest.get("files")
    if not isinstance(files, dict) or len(files) != 7:
        found = len(files) if isinstance(files, dict) else "none"
        raise ContractError(
            f"OCES frozen hash manifest must declare exactly seven files; found {found}."
        )

    for rel_path, expected_hash in files.items():
        target = REPO_ROOT / rel_path
        try:
            actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(
                f"OCES frozen artifact missing or unreadable: {rel_path}: {exc}"
            ) from exc
        if actual_hash != expected_hash:
            raise ContractError(
                f"OCES frozen artifact {rel_path} does not match its frozen SHA-256 "
                f"(expected {expected_hash}, got {actual_hash}). Refusing to load "
                "tampered, modified or regenerated OCES data."
            )


def load_suite(baselines: list[BaselineCase], *, task_id: str) -> list[AttackCase]:
    """Load, verify and register the frozen OCES suite for one task.

    ``baselines`` must be the exact OCES seed set for this task, as returned by
    ``baseline.load.load_baseline`` on the task's frozen seed file
    (``baseline/oces/emotion_seeds.json`` or ``baseline/oces/sentiment_seeds.json`` --
    resolved by the caller via ``registry.baseline_file_for``). Every loaded case's
    ``baseline_id`` is checked against that set, so pointing this at the wrong seed file
    (e.g. the core baseline file) fails loudly instead of silently building an orphaned
    suite that a later drift comparison would misread.

    Returns cases in on-disk file order, which is fixed once frozen -- so the same frozen
    bytes always yield the same case order, deterministically, across runs and platforms.
    """
    case_file = CASE_FILE_BY_TASK.get(task_id)
    if case_file is None:
        raise ContractError(f"no frozen OCES case file is registered for task_id {task_id!r}")

    _verify_frozen_hashes()

    known_baseline_ids = {baseline.baseline_id for baseline in baselines}

    try:
        raw = case_file.read_bytes()
    except OSError as exc:
        raise ContractError(f"OCES frozen case file unreadable: {case_file}: {exc}") from exc
    try:
        entries = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"OCES frozen case file {case_file} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise ContractError(f"OCES frozen case file {case_file} must contain a JSON array")

    cases: list[AttackCase] = []
    for entry in entries:
        try:
            case = AttackCase(**entry["case"])
            meta = md.AttackMetadata(**entry["metadata"])
        except (TypeError, KeyError) as exc:
            raise ContractError(
                f"OCES frozen case file {case_file} contains a record that does not match "
                f"the AttackCase/AttackMetadata shape: {exc}"
            ) from exc
        if case.baseline_id not in known_baseline_ids:
            raise ContractError(
                f"OCES case {case.attack_id!r} references baseline_id {case.baseline_id!r}, "
                f"which is not in the supplied seed set for task {task_id!r}. The caller "
                "likely resolved the wrong baseline file for this evaluation."
            )
        md.register(case, meta)
        cases.append(case)
    return cases

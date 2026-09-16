"""Validate recorded artifact identity before any scoring or comparison claims.

Identity rules (CONTRACTS.md section 1, "the rule that has no exceptions"):

A new run records its identity explicitly. Nothing here infers a model from ``version``,
defaults an unknown identity to emotion, or falls back to emotion after a malformed new
run. Blank identity is supported *only* for recognised historical artifacts, where
``target_id``/``suite_id`` are absent from every row and the emotion label space is
recorded as **inferred** rather than declared.
"""

import math
import re
from dataclasses import dataclass

from contract import CORE_FAMILIES, SUITES, RunResult

CATEGORIES = CORE_FAMILIES

# The historical seven. Used only for artifacts recognised as the original emotion run;
# never as a default for data that carries its own identity.
EMOTION_LABELS = ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")

# v1/v2 mean these targets *only* within a recognised legacy emotion artifact.
LEGACY_VERSION_TO_TARGET = {"v1": "emotion_v1", "v2": "emotion_v2"}

PROVENANCE_DECLARED = "declared"
PROVENANCE_INFERRED_LEGACY = "inferred_legacy"


@dataclass(frozen=True)
class Identity:
    """The resolved identity of one results file."""

    target_id: str
    suite_id: str
    version: str
    labels: tuple[str, ...]
    provenance: str

    @property
    def is_legacy(self) -> bool:
        return self.provenance == PROVENANCE_INFERRED_LEGACY


def resolve_identity(
    rows: list[RunResult],
    *,
    labels=None,
    target_id: str | None = None,
    suite_id: str | None = None,
    expected_version: str | None = None,
) -> Identity:
    """Resolve one identity for a whole results file, or raise.

    A results file holds exactly one ``(target_id, suite_id, version)``. Mixed identity is
    an error, not something to partition afterwards.

    ``labels`` must be supplied for any run that carries its own ``target_id``; the caller
    reads it from that run's recorded model block. Omitting it for new data raises rather
    than quietly assuming emotion.
    """
    versions = {row.version for row in rows}
    targets = {row.target_id or "" for row in rows}
    suites = {row.suite_id or "" for row in rows}
    if len(versions) > 1 or len(targets) > 1 or len(suites) > 1:
        raise ValueError(
            "a results file holds exactly one (target_id, suite_id, version); found "
            f"targets={sorted(targets)} suites={sorted(suites)} versions={sorted(versions)}"
        )

    version = expected_version or (rows[0].version if rows else "")
    row_target = next(iter(targets)) if targets else ""
    row_suite = next(iter(suites)) if suites else ""

    if target_id is not None and row_target and target_id != row_target:
        raise ValueError(f"declared target_id {target_id!r} disagrees with rows ({row_target!r})")
    if suite_id is not None and row_suite and suite_id != row_suite:
        raise ValueError(f"declared suite_id {suite_id!r} disagrees with rows ({row_suite!r})")

    resolved_target = target_id or row_target
    resolved_suite = suite_id or row_suite

    if resolved_suite and resolved_suite not in SUITES:
        raise ValueError(f"unknown suite_id {resolved_suite!r}")

    if resolved_target:
        # Data that states its own identity must also state its label space.
        if labels is None:
            raise ValueError(
                f"target {resolved_target!r} declares its identity but no label space was "
                "supplied; analysis must not fall back to the emotion labels"
            )
        return Identity(
            target_id=resolved_target,
            suite_id=resolved_suite or "",
            version=version,
            labels=tuple(labels),
            provenance=PROVENANCE_DECLARED,
        )

    # No rows at all: an empty recorded run. There is nothing to label-check, so no
    # identity can be misattributed here; keep the caller's expected version and let the
    # coverage/metadata checks report the emptiness.
    if not rows:
        return Identity(
            target_id=LEGACY_VERSION_TO_TARGET.get(version, ""),
            suite_id=resolved_suite or "",
            version=version,
            labels=tuple(labels) if labels is not None else EMOTION_LABELS,
            provenance=PROVENANCE_INFERRED_LEGACY,
        )

    # No target_id on any row: a recognised historical artifact.
    if version not in LEGACY_VERSION_TO_TARGET:
        raise ValueError(
            f"unrecognised artifact: no target_id and version {version!r} is not a known "
            "legacy emotion version; refusing to guess an identity"
        )
    return Identity(
        target_id=LEGACY_VERSION_TO_TARGET[version],
        suite_id=resolved_suite or "core",
        version=version,
        labels=tuple(labels) if labels is not None else EMOTION_LABELS,
        provenance=PROVENANCE_INFERRED_LEGACY,
    )


def validate_manifest(manifest: dict) -> None:
    from analysis import drift

    oracles = {drift.ORACLE_LABEL_MATCH_BASELINE, drift.ORACLE_REQUEST_REJECTED,
               drift.ORACLE_GRACEFUL_OR_TRUNCATE, drift.ORACLE_STAY_AVAILABLE,
               drift.ORACLE_NO_INFO_LEAK, drift.ORACLE_DIAGNOSTIC}
    tiers = {drift.TIER_GOLD, drift.TIER_SILVER, drift.TIER_REVIEW, drift.TIER_DIAGNOSTIC}
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object keyed by attack_id")
    for aid, meta in manifest.items():
        if not isinstance(aid, str) or not aid or not isinstance(meta, dict):
            raise ValueError(f"invalid manifest entry {aid!r}")
        if meta.get("attack_id") != aid:
            raise ValueError(f"manifest key {aid!r} disagrees with attack_id")
        for name, values in (("family", CATEGORIES), ("oracle", oracles), ("validity_tier", tiers)):
            value = meta.get(name)
            if not isinstance(value, str) or value not in values:
                raise ValueError(f"manifest {aid!r}: unknown or missing {name}: {value!r}")
        for name in ("subfamily", "source"):
            if not isinstance(meta.get(name), str) or not meta[name].strip():
                raise ValueError(f"manifest {aid!r}: missing {name}")
        if meta.get("relation") not in ("invariant", "schema", "boundary", "availability", "diagnostic", "directional"):
            raise ValueError(f"manifest {aid!r}: unknown relation")
        if type(meta.get("requires_baseline")) is not bool:
            raise ValueError(f"manifest {aid!r}: requires_baseline must be boolean")
        # The shipped repeated_punctuation cases use diagnostic oracle + REVIEW tier.
        # Preserve the registered values; the oracle always excludes automatic scoring.


def case_key(row: RunResult) -> str:
    return f"{row.case_type}:{row.attack_id if row.case_type == 'attack' else row.baseline_id}"


def _validate_scores(
    key: str, row: RunResult, labels: tuple[str, ...], *, require_complete: bool
) -> None:
    """Check the recorded score vector.

    Shape and finiteness are checked everywhere: whatever is present must be a mapping of
    known labels to finite values in [0, 1]. *Completeness* is required only of data that
    declares its own identity, per the task's "validate all_scores shape and finite values
    for new target responses". Historical rows predate the rule and synthetic contract
    fixtures legitimately carry an empty vector, so demanding a full vector of them would
    reject evidence that is not actually corrupt.
    """
    scores = row.all_scores
    if scores is None:
        if require_complete and row.label is not None:
            raise ValueError(f"{key}: prediction {row.label!r} recorded without all_scores")
        return
    if not isinstance(scores, dict):
        raise ValueError(f"{key}: all_scores must be an object keyed by label")
    unknown = sorted(k for k in scores if k not in labels)
    if unknown:
        raise ValueError(f"{key}: all_scores carries labels outside the declared space: {unknown}")
    if require_complete and row.label is not None and set(scores) != set(labels):
        missing = sorted(set(labels) - set(scores))
        raise ValueError(f"{key}: all_scores is not a complete score vector; missing {missing}")
    for label, value in scores.items():
        if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"{key}: all_scores[{label!r}] is not a finite number")
        if not 0 <= value <= 1:
            raise ValueError(f"{key}: all_scores[{label!r}] outside [0, 1]")


def validate_rows(
    rows: list[RunResult],
    expected_version: str | None = None,
    *,
    labels=None,
    identity: Identity | None = None,
) -> str:
    """Missing predictions/references are legitimate; ambiguous identity is not.

    ``labels``/``identity`` carry the declared label space. Callers that already resolved
    an identity pass it through so the label check is made against the run's own space
    rather than the historical emotion one.
    """
    if identity is None:
        identity = resolve_identity(rows, labels=labels, expected_version=expected_version)
    allowed = identity.labels
    declared = identity.provenance == PROVENANCE_DECLARED
    version = identity.version or expected_version or (rows[0].version if rows else "")
    seen = set()
    for row in rows:
        if row.version not in ("v1", "v2") or row.version != version:
            raise ValueError(f"mixed or unexpected version {row.version!r}; expected {version!r}")
        if row.case_type not in ("baseline", "attack"):
            raise ValueError(f"unknown case_type {row.case_type!r}")
        identifier = row.attack_id if row.case_type == "attack" else row.baseline_id
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{row.case_type} row requires a nonempty identifier")
        if row.baseline_id is not None and (not isinstance(row.baseline_id, str) or not row.baseline_id):
            raise ValueError("baseline_id must be null or a nonempty string")
        if row.case_type == "baseline" and (row.attack_id is not None or row.category is not None):
            raise ValueError("baseline row must not carry attack_id or category")
        key = case_key(row)
        if key in seen:
            raise ValueError(f"duplicate result case key {key!r}")
        seen.add(key)
        if row.status_code is not None and (type(row.status_code) is not int or not 100 <= row.status_code <= 599):
            raise ValueError(f"{key}: invalid status_code")
        if not isinstance(row.response_body, str) or type(row.endpoint_alive_after) is not bool:
            raise ValueError(f"{key}: invalid response_body or endpoint_alive_after")
        if row.latency_band not in ("normal", "slow", "timeout"):
            raise ValueError(f"{key}: invalid latency_band")
        if row.label is not None and row.label not in allowed:
            raise ValueError(
                f"{key}: prediction {row.label!r} is outside the declared label space "
                f"for {identity.target_id or 'this run'}"
            )
        _validate_scores(key, row, allowed, require_complete=declared)
        if row.error is not None and not isinstance(row.error, str):
            raise ValueError(f"{key}: error must be null or a string")
        if row.request_body_bytes is not None and (
            type(row.request_body_bytes) is not int or row.request_body_bytes < 0
        ):
            raise ValueError(f"{key}: request_body_bytes must be null or a non-negative integer")
        if row.request_body_sha256 is not None and not (
            isinstance(row.request_body_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", row.request_body_sha256)
        ):
            raise ValueError(f"{key}: request_body_sha256 must be null or 64 lowercase hex")
        for name in ("confidence", "latency_ms"):
            value = getattr(row, name)
            if value is None and name == "confidence":
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key}: invalid {name}")
            if name == "confidence" and value > 1:
                raise ValueError(f"{key}: confidence must be at most 1")
    return version


def validate_run(
    rows: list[RunResult],
    meta: dict,
    manifest: dict,
    version: str,
    manifest_sha: str,
    *,
    labels=None,
    identity: Identity | None = None,
) -> None:
    validate_rows(rows, version, labels=labels, identity=identity)
    if not isinstance(meta, dict) or meta.get("version") != version:
        raise ValueError(f"{version}: run metadata version mismatch")
    fingerprints = meta.get("fingerprints", {})
    if not isinstance(fingerprints, dict):
        raise ValueError(f"{version}: invalid fingerprints")
    for name in ("planned_suite_sha256", "manifest_sha256"):
        value = fingerprints.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{version}: invalid {name}")
    if fingerprints["manifest_sha256"] != manifest_sha:
        raise ValueError(f"{version}: actual manifest SHA-256 does not match run metadata")
    ids = meta.get("case_ids")
    coverage = meta.get("coverage")
    if not isinstance(ids, dict) or not isinstance(coverage, dict):
        raise ValueError(f"{version}: missing case_ids or coverage")
    sets = {}
    for name in ("planned", "selected", "completed", "missing", "skipped", "limit_excluded"):
        keys = ids.get(name)
        if not isinstance(keys, list) or any(not isinstance(k, str) or not re.fullmatch(r"(?:baseline|attack):.+", k) for k in keys):
            raise ValueError(f"{version}: invalid case_ids.{name}")
        if len(keys) != len(set(keys)):
            raise ValueError(f"{version}: duplicate case_ids.{name}")
        sets[name] = set(keys)
        if type(coverage.get(name)) is not int or coverage[name] != len(keys):
            raise ValueError(f"{version}: coverage.{name} disagrees with case IDs")
    if [case_key(r) for r in rows] != ids["completed"]:
        raise ValueError(f"{version}: actual result rows disagree with completed case IDs/order")
    if sets["completed"] & sets["missing"] or sets["completed"] | sets["missing"] != sets["selected"]:
        raise ValueError(f"{version}: completed/missing must partition selected cases")
    if (sets["selected"] & sets["skipped"] or sets["selected"] & sets["limit_excluded"]
            or sets["skipped"] & sets["limit_excluded"]
            or sets["selected"] | sets["skipped"] | sets["limit_excluded"] != sets["planned"]):
        raise ValueError(f"{version}: selected/skipped/limit_excluded must partition planned cases")
    rate = len(rows) / len(sets["planned"]) if sets["planned"] else 0.0
    if coverage.get("coverage_rate") != round(rate, 6):
        raise ValueError(f"{version}: coverage_rate disagrees with actual rows")
    planned_attacks = {key[7:] for key in sets["planned"] if key.startswith("attack:")}
    if planned_attacks != set(manifest):
        raise ValueError(f"{version}: planned attack IDs disagree with manifest")
    for row in rows:
        if row.case_type != "attack":
            continue
        entry = manifest[row.attack_id]
        if row.category != entry["family"]:
            raise ValueError(f"{version}: {row.attack_id} category disagrees with manifest")
        if entry["requires_baseline"] != (row.baseline_id is not None):
            raise ValueError(f"{version}: {row.attack_id} baseline association disagrees with manifest")
        if row.baseline_id is not None and f"baseline:{row.baseline_id}" not in sets["planned"]:
            raise ValueError(f"{version}: {row.attack_id} references an unplanned baseline")

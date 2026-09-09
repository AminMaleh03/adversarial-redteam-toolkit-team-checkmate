"""Validate recorded artifact identity before any scoring or comparison claims."""

import math
import re

from contract import RunResult

CATEGORIES = ("malformed", "boundary", "perturbation", "encoding", "whitespace", "truncation")


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


def validate_rows(rows: list[RunResult], expected_version: str | None = None) -> str:
    """Missing predictions/references are legitimate; ambiguous identity is not."""
    version = expected_version or (rows[0].version if rows else "")
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
        if row.label is not None and row.label not in ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"):
            raise ValueError(f"{key}: invalid prediction label")
        if row.error is not None and not isinstance(row.error, str):
            raise ValueError(f"{key}: error must be null or a string")
        for name in ("confidence", "latency_ms"):
            value = getattr(row, name)
            if value is None and name == "confidence":
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key}: invalid {name}")
            if name == "confidence" and value > 1:
                raise ValueError(f"{key}: confidence must be at most 1")
    return version


def validate_run(rows: list[RunResult], meta: dict, manifest: dict, version: str, manifest_sha: str) -> None:
    validate_rows(rows, version)
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

"""
Provenance and oracle metadata for every attack the library produces.

Why this exists
---------------
``contract.AttackCase`` is frozen and deliberately minimal: it carries only what the
runner needs to fire a request. A serious robustness scanner has to record more than
"here is a weird string" -- for each case it records where the payload came from, what
*relation* the transformation declares, and what *oracle* decides whether the observed
behaviour is actually a defect. We keep all of that here, in a sidecar manifest keyed by
``attack_id``, so the frozen contract is never touched.

Division of responsibility (do not blur it)
-------------------------------------------
This layer only *declares* expectations. It never decides that an attack "succeeded". The
runner supplies the observed response; the analysis evaluates it against the declared
oracle.

Generic facts vs target-profile expectations
--------------------------------------------
Most fields (relation, oracle, source, dose, position) are generic: they hold no matter
what endpoint you point the scanner at. A few (``expected_sanitizer_behavior``,
``expected_http_behavior``) are expectations about *this competition's* hardened endpoint,
so they are grouped under ``target_profile`` (default ``"rayyan-v2"``). A future user
pointing the scanner at a different system would supply a different profile rather than
inherit Rayyan-specific assumptions as universal truth. This keeps today's integration
working while leaving a clean migration path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from contract import AttackCase

# --------------------------------------------------------------------------------------
# Controlled vocabularies (module constants so a typo is an ImportError, not a silent join
# failure downstream).
# --------------------------------------------------------------------------------------

# Relation the transformation declares about model decision / service behaviour.
REL_INVARIANT = "invariant"        # meaning preserved -> label must not change
REL_SCHEMA = "schema"              # request malformed/invalid -> rejected cleanly
REL_BOUNDARY = "boundary"          # around a defined limit -> defined, graceful behaviour
REL_AVAILABILITY = "availability"  # unusual but bounded -> service must stay up
REL_DIRECTIONAL = "directional"    # RESERVED for Phase 2 (negation/contrast/intensity);
#                                    changes the oracle, so it is a team decision, defined
#                                    here only to complete the vocabulary.

RELATIONS = frozenset(
    {REL_INVARIANT, REL_SCHEMA, REL_BOUNDARY, REL_AVAILABILITY, REL_DIRECTIONAL}
)

# What decides whether the observed behaviour is a defect. Analysis reads this.
ORACLE_LABEL_MATCH_BASELINE = "label_should_match_baseline"
ORACLE_REQUEST_REJECTED = "request_should_be_rejected_cleanly"
ORACLE_GRACEFUL_OR_TRUNCATE = "endpoint_should_fail_gracefully_or_apply_documented_truncation"
ORACLE_STAY_AVAILABLE = "endpoint_should_stay_available"
ORACLE_NO_INFO_LEAK = "error_response_must_not_leak_internals"
ORACLE_DIAGNOSTIC = "diagnostic_no_fixed_oracle"  # inspect only; never auto-scored

ORACLES = frozenset(
    {
        ORACLE_LABEL_MATCH_BASELINE,
        ORACLE_REQUEST_REJECTED,
        ORACLE_GRACEFUL_OR_TRUNCATE,
        ORACLE_STAY_AVAILABLE,
        ORACLE_NO_INFO_LEAK,
        ORACLE_DIAGNOSTIC,
    }
)

# Confidence that the declared relation holds. Morris et al. (2020) showed many "successful"
# NLP attacks silently break semantics, so REVIEW/DIAGNOSTIC cases are never auto-scored.
TIER_GOLD = "GOLD"            # deterministic relation, or human-labelled seed
TIER_SILVER = "SILVER"        # mechanically justified, low semantic risk
TIER_REVIEW = "REVIEW"        # meaning could have shifted; do not count automatically
TIER_DIAGNOSTIC = "DIAGNOSTIC"  # intentionally ambiguous; inspect, never score as a vuln

VALIDITY_TIERS = frozenset({TIER_GOLD, TIER_SILVER, TIER_REVIEW, TIER_DIAGNOSTIC})

SEMANTIC_RISK = frozenset({"low", "medium", "high", "none"})

# Where a payload's characters/positions sit.
POSITIONS = frozenset(
    {"leading", "middle", "trailing", "whole", "content_word", "start", "end", "none"}
)

# How a boundary length was derived.
BOUNDARY_SOURCES = frozenset(
    {"tokenizer", "approximate_word_estimate", "code", "empirical"}
)

# --- target-profile expectations (profile: rayyan-v2) ---------------------------------
# What we EXPECT this competition's hardened V2 to do. Hypotheses, measured by the runner,
# never assertions.
SAN_V2_STRIPS = "v2_strips"                    # control/format char removed
SAN_V2_NORMALIZES = "v2_normalizes"            # NFKC folds it (compatibility forms)
SAN_V2_COLLAPSES_WS = "v2_collapses_whitespace"
SAN_V2_PASSES_THROUGH = "v2_passes_through"    # NFKC does NOT touch it (mixed-script homoglyphs)
SAN_V2_REJECTS_LENGTH = "v2_rejects_on_length_limit"
SAN_V2_REJECTS_TYPE = "v2_rejects_on_strict_type"
SAN_V2_REJECTS_EXTRA = "v2_rejects_on_extra_forbid"
SAN_NOT_APPLICABLE = "not_applicable"

HTTP_EXPECT_200 = "expect_200_ok"
HTTP_EXPECT_4XX = "expect_4xx_rejected"
HTTP_EXPECT_5XX_OR_CONN = "expect_5xx_or_connection_error"
HTTP_MEASURE = "measure_empirically"


@dataclass
class AttackMetadata:
    """Everything about an attack that does not fit in the frozen AttackCase contract."""

    attack_id: str
    family: str                       # matches AttackCase.category
    subfamily: str
    relation: str                     # one of RELATIONS
    oracle: str                       # one of ORACLES
    source: str
    validity_tier: str                # one of VALIDITY_TIERS
    semantic_risk: str = "none"       # one of SEMANTIC_RISK
    requires_baseline: bool = False
    # provenance
    source_version: Optional[str] = None
    source_url: Optional[str] = None
    transform_version: str = "v1"
    # generic attack facts
    dose: Optional[int] = None
    position: Optional[str] = None
    script_change: Optional[str] = None
    boundary_source: Optional[str] = None
    boundary_target: Optional[int] = None    # requested token count for a boundary case
    boundary_measured: Optional[int] = None  # what the counter actually reported
    # target-profile expectations (profile below)
    target_profile: str = "rayyan-v2"
    expected_sanitizer_behavior: str = SAN_NOT_APPLICABLE
    expected_http_behavior: str = HTTP_MEASURE
    notes: str = ""

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise ValueError(f"unknown relation {self.relation!r} for {self.attack_id}")
        if self.oracle not in ORACLES:
            raise ValueError(f"unknown oracle {self.oracle!r} for {self.attack_id}")
        if self.validity_tier not in VALIDITY_TIERS:
            raise ValueError(f"unknown validity_tier {self.validity_tier!r} for {self.attack_id}")
        if self.semantic_risk not in SEMANTIC_RISK:
            raise ValueError(f"unknown semantic_risk {self.semantic_risk!r} for {self.attack_id}")
        if self.position is not None and self.position not in POSITIONS:
            raise ValueError(f"unknown position {self.position!r} for {self.attack_id}")
        if self.boundary_source is not None and self.boundary_source not in BOUNDARY_SOURCES:
            raise ValueError(
                f"unknown boundary_source {self.boundary_source!r} for {self.attack_id}"
            )


# --------------------------------------------------------------------------------------
# The sidecar manifest + a payload fingerprint registry.
# --------------------------------------------------------------------------------------

_MANIFEST: dict[str, AttackMetadata] = {}
_FINGERPRINTS: dict[str, str] = {}


def _fingerprint(case: AttackCase) -> str:
    """Deterministic digest of a case's payload, so a reused id with a different payload is caught."""
    parts = [
        case.attack_id,
        case.category,
        str(case.is_raw),
        case.attacked_text or "",
        (case.raw_body.decode("utf-8", "surrogatepass")
         if isinstance(case.raw_body, bytes) else (case.raw_body or "")),
        json.dumps(case.raw_headers, sort_keys=True) if case.raw_headers else "",
    ]
    blob = "\x1f".join(parts).encode("utf-8", "surrogatepass")
    return hashlib.sha256(blob).hexdigest()


def register(case: AttackCase, meta: AttackMetadata) -> AttackCase:
    """
    Record ``meta`` for ``case`` and return the case unchanged.

    Enforced invariants (the tests assert these):
      * attack_id on case and metadata agree; category == family;
      * derived cases carry a baseline_id and set requires_baseline=True, and vice-versa;
      * an attack_id is never reused for a *different* payload (checked by fingerprint) or
        for different metadata.

    Registration is idempotent per attack_id: the runner calls build_derived() once per
    baseline, so re-registering the identical case just overwrites.
    """
    if case.attack_id != meta.attack_id:
        raise ValueError(
            f"attack_id mismatch: case {case.attack_id!r} vs metadata {meta.attack_id!r}"
        )
    if case.category != meta.family:
        raise ValueError(
            f"category/family mismatch on {case.attack_id!r}: {case.category!r} vs {meta.family!r}"
        )
    has_baseline = case.baseline_id is not None
    if has_baseline != meta.requires_baseline:
        raise ValueError(
            f"{case.attack_id!r}: baseline_id present={has_baseline} but "
            f"requires_baseline={meta.requires_baseline}"
        )

    fp = _fingerprint(case)
    existing_fp = _FINGERPRINTS.get(case.attack_id)
    if existing_fp is not None and existing_fp != fp:
        raise ValueError(f"attack_id {case.attack_id!r} reused for a DIFFERENT payload")
    existing_meta = _MANIFEST.get(case.attack_id)
    if existing_meta is not None and existing_meta != meta:
        raise ValueError(f"attack_id {case.attack_id!r} reused with DIFFERENT metadata")

    _MANIFEST[case.attack_id] = meta
    _FINGERPRINTS[case.attack_id] = fp
    return case


def manifest() -> dict[str, AttackMetadata]:
    """Return a copy of the current metadata manifest, keyed by attack_id."""
    return dict(_MANIFEST)


def metadata_for(attack_id: str) -> Optional[AttackMetadata]:
    """Look up the metadata for one attack_id, or None if it was never registered."""
    return _MANIFEST.get(attack_id)


def reset() -> None:
    """Clear the manifest and fingerprint registry. Used by tests for a clean start."""
    _MANIFEST.clear()
    _FINGERPRINTS.clear()


def write_manifest(path: str) -> None:
    """Dump the manifest to JSON for the report and for analysis to join against."""
    payload = {aid: asdict(meta) for aid, meta in sorted(_MANIFEST.items())}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

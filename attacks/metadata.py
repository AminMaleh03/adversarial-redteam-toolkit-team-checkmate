"""
Provenance and oracle metadata for every attack the library produces.

Why this exists
---------------
`contract.AttackCase` is frozen and deliberately minimal: it carries only what the
runner needs to fire a request. But a serious robustness scanner has to record more
than "here is a weird string" — it has to record, for each case:

  * where the payload came from (which research / standard / dataset),
  * what *relation* the transformation declares (should the label stay the same,
    should the request be rejected, should the service stay up), and
  * what *oracle* decides whether the observed behaviour is actually a defect.

We do NOT touch the frozen contract to store this. Instead every `AttackCase` we build
is registered here in a sidecar manifest keyed by `attack_id`. Analysis and the report
can read the manifest to know, per case, what "failure" even means — they never have to
guess. This is the difference between a behavioural-testing framework and a bag of
exploits.

Division of responsibility (do not blur it)
-------------------------------------------
This layer only *declares* the expected relation and oracle. It never decides that an
attack "succeeded". The runner supplies the observed response; the analysis evaluates
the observed response against the declared oracle. So a case says
"label_should_match_baseline", and only Khalid's analysis rules on whether it did.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from contract import AttackCase

# --------------------------------------------------------------------------------------
# Controlled vocabularies. Kept as module constants so a typo becomes an ImportError
# instead of a silent string mismatch that analysis can't join on later.
# --------------------------------------------------------------------------------------

# What the transformation promises about the model's decision / the service's behaviour.
REL_INVARIANT = "invariant"        # meaning preserved -> label must not change
REL_SCHEMA = "schema"              # request is malformed/invalid -> must be rejected cleanly
REL_BOUNDARY = "boundary"          # around a defined limit -> defined, graceful behaviour
REL_AVAILABILITY = "availability"  # unusual but bounded -> service must stay up
REL_DIRECTIONAL = "directional"    # RESERVED for Phase 2 (negation/contrast/intensity).
#                                    Changes the oracle, so it is a team decision, not a
#                                    silent addition to this branch. Defined here only so
#                                    the vocabulary is complete when the team enables it.

RELATIONS = frozenset(
    {REL_INVARIANT, REL_SCHEMA, REL_BOUNDARY, REL_AVAILABILITY, REL_DIRECTIONAL}
)

# What decides whether the observed behaviour is a defect. Analysis reads this.
ORACLE_LABEL_MATCH_BASELINE = "label_should_match_baseline"
ORACLE_REQUEST_REJECTED = "request_should_be_rejected_cleanly"
ORACLE_GRACEFUL_OR_TRUNCATE = "endpoint_should_fail_gracefully_or_apply_documented_truncation"
ORACLE_STAY_AVAILABLE = "endpoint_should_stay_available"
ORACLE_NO_INFO_LEAK = "error_response_must_not_leak_internals"

ORACLES = frozenset(
    {
        ORACLE_LABEL_MATCH_BASELINE,
        ORACLE_REQUEST_REJECTED,
        ORACLE_GRACEFUL_OR_TRUNCATE,
        ORACLE_STAY_AVAILABLE,
        ORACLE_NO_INFO_LEAK,
    }
)

# Confidence that the declared relation actually holds for this case. Drives whether a
# result can be counted automatically or must be human-reviewed before it is a finding.
# Rationale: Morris et al. (2020) showed many "successful" NLP attacks silently break
# semantics, so a flip on a REVIEW/DIAGNOSTIC case is not automatically a vulnerability.
TIER_GOLD = "GOLD"            # deterministic relation (schema/boundary) or human-labelled seed
TIER_SILVER = "SILVER"        # mechanically justified, low semantic risk (e.g. 1 typo)
TIER_REVIEW = "REVIEW"        # meaning could have shifted; do not count automatically
TIER_DIAGNOSTIC = "DIAGNOSTIC"  # intentionally ambiguous; inspect, never score as a vuln

VALIDITY_TIERS = frozenset({TIER_GOLD, TIER_SILVER, TIER_REVIEW, TIER_DIAGNOSTIC})

SEMANTIC_RISK = frozenset({"low", "medium", "high", "none"})

# What we EXPECT the hardened V2 to do with this payload. This is a hypothesis to be
# measured, never an assertion. It is what powers the automated before/after column.
SAN_V2_STRIPS = "v2_strips"                    # control/format char removed (zero-width, RTL, null)
SAN_V2_NORMALIZES = "v2_normalizes"            # NFKC folds it (compatibility forms, full-width)
SAN_V2_COLLAPSES_WS = "v2_collapses_whitespace"
SAN_V2_PASSES_THROUGH = "v2_passes_through"    # NFKC does NOT touch it (mixed-script homoglyphs!)
SAN_V2_REJECTS_LENGTH = "v2_rejects_on_length_limit"
SAN_V2_REJECTS_TYPE = "v2_rejects_on_strict_type"
SAN_V2_REJECTS_EXTRA = "v2_rejects_on_extra_forbid"
SAN_NOT_APPLICABLE = "not_applicable"

# What we EXPECT over HTTP. "measure_empirically" is the honest default whenever we are
# not certain from reading the endpoint code. Measure first, narrate second.
HTTP_EXPECT_200 = "expect_200_ok"
HTTP_EXPECT_4XX = "expect_4xx_rejected"
HTTP_EXPECT_5XX_OR_CONN = "expect_5xx_or_connection_error"
HTTP_MEASURE = "measure_empirically"


@dataclass
class AttackMetadata:
    """Everything about an attack that does not fit in the frozen AttackCase contract."""

    attack_id: str
    family: str                       # matches AttackCase.category, e.g. "encoding"
    subfamily: str                    # e.g. "homoglyph_mixed_script"
    relation: str                     # one of RELATIONS
    oracle: str                       # one of ORACLES
    source: str                       # e.g. "Unicode UTS #39", "Bad Characters (Boucher 2022)"
    validity_tier: str                # one of VALIDITY_TIERS
    semantic_risk: str = "none"       # one of SEMANTIC_RISK
    requires_baseline: bool = False   # True for derived (invariance) cases
    source_version: Optional[str] = None       # e.g. Unicode "15.1"
    dose: Optional[int] = None                  # number of injections / perturbations
    position: Optional[str] = None              # start | middle | end | keyword | n/a
    script_change: Optional[str] = None         # e.g. "Latin->Cyrillic" for confusables
    boundary_source: Optional[str] = None       # tokenizer | approximate | code | empirical
    expected_sanitizer_behavior: str = SAN_NOT_APPLICABLE
    expected_http_behavior: str = HTTP_MEASURE
    notes: str = ""

    def __post_init__(self) -> None:
        # Fail loudly at construction if a controlled field is off-vocabulary. A silent
        # bad value here would only surface as a broken join in analysis, far away.
        if self.relation not in RELATIONS:
            raise ValueError(f"unknown relation {self.relation!r} for {self.attack_id}")
        if self.oracle not in ORACLES:
            raise ValueError(f"unknown oracle {self.oracle!r} for {self.attack_id}")
        if self.validity_tier not in VALIDITY_TIERS:
            raise ValueError(f"unknown validity_tier {self.validity_tier!r} for {self.attack_id}")
        if self.semantic_risk not in SEMANTIC_RISK:
            raise ValueError(f"unknown semantic_risk {self.semantic_risk!r} for {self.attack_id}")


# --------------------------------------------------------------------------------------
# The sidecar manifest. Keyed by attack_id, populated as cases are registered.
# --------------------------------------------------------------------------------------

_MANIFEST: dict[str, AttackMetadata] = {}


def register(case: AttackCase, meta: AttackMetadata) -> AttackCase:
    """
    Record `meta` for `case` and return the case unchanged.

    Every builder in this package funnels through here, which is also the one place we
    enforce two contract invariants that the tests assert:
      * attack_id on the case and the metadata agree,
      * the derived/standalone rule holds: a case with a baseline_id is derived and its
        metadata must say requires_baseline=True, and vice-versa.

    Registration is idempotent per attack_id: the runner calls build_derived() once per
    baseline sentence, so re-registering the same id (same content) just overwrites. A
    *different* payload reusing an existing id is a bug and raises.
    """
    if case.attack_id != meta.attack_id:
        raise ValueError(
            f"attack_id mismatch: case {case.attack_id!r} vs metadata {meta.attack_id!r}"
        )
    if case.category != meta.family:
        raise ValueError(
            f"category/family mismatch on {case.attack_id!r}: "
            f"{case.category!r} vs {meta.family!r}"
        )
    # Derived cases carry a baseline_id; standalone cases leave it None. Keep metadata
    # honest about which it is, because analysis uses baseline_id emptiness to decide
    # what it can diff.
    has_baseline = case.baseline_id is not None
    if has_baseline != meta.requires_baseline:
        raise ValueError(
            f"{case.attack_id!r}: baseline_id present={has_baseline} but "
            f"requires_baseline={meta.requires_baseline}"
        )

    existing = _MANIFEST.get(case.attack_id)
    if existing is not None and existing != meta:
        raise ValueError(f"duplicate attack_id with differing metadata: {case.attack_id!r}")
    _MANIFEST[case.attack_id] = meta
    return case


def manifest() -> dict[str, AttackMetadata]:
    """Return a copy of the current metadata manifest, keyed by attack_id."""
    return dict(_MANIFEST)


def metadata_for(attack_id: str) -> Optional[AttackMetadata]:
    """Look up the metadata for one attack_id, or None if it was never registered."""
    return _MANIFEST.get(attack_id)


def reset() -> None:
    """Clear the manifest. Used by tests so each run starts from a clean registry."""
    _MANIFEST.clear()


def write_manifest(path: str) -> None:
    """
    Dump the manifest to JSON for the report and for analysis to join against.

    Written on demand by library.py, not committed: it is generated output, like
    anything under results/.
    """
    payload = {aid: asdict(meta) for aid, meta in sorted(_MANIFEST.items())}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

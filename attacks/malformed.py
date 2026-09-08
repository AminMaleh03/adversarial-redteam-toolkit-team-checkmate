"""
Category 1 - malformed and oversized payloads (standalone).

Transport/schema boundary: broken JSON, missing/renamed/extra fields, wrong content type,
a parser-depth ladder (deeply nested JSON), and oversized text values at three sizes.
Framed against the OWASP AI Testing Guide; expected outcomes are hypotheses, measured.

Raw vs structured
-----------------
Anything whose exact bytes matter (broken JSON, wrong content-type, a body shaped
differently from {"text": "<string>"}, or a hand-built nesting depth) is is_raw=True with
a verbatim raw_body. The oversized payloads ARE ordinary {"text": "<huge string>"}
requests, so they stay structured; the string is built in code and never committed.

The one genuine V1 vs V2 difference here
----------------------------------------
``extra_field`` is the clean before/after case: V1 default extra="ignore" should accept
(200); V2 extra="forbid" should reject (422). Contrast the ``number`` type-confusion case
in boundary.py, which is NOT a V1/V2 difference because plain Pydantic already rejects it.
"""

from __future__ import annotations

from contract import AttackCase
from attacks import metadata as md

_OWASP_URL = "https://owaspai.org/docs/5_testing/"
_ONE_KIB = 1024
_OVERSIZE_SIZES = {
    "100kb": 100 * _ONE_KIB,
    "1mb": 1 * _ONE_KIB * _ONE_KIB,
    "10mb": 10 * _ONE_KIB * _ONE_KIB,
}
# Depth-response ladder for the nested-JSON parser stress, so analysis can find the
# threshold rather than reacting to one arbitrary depth.
_NESTING_DEPTHS = (32, 128, 512, 1024, 2000)


def _raw_case(subfamily: str, raw_body: str, headers: dict, *, oracle: str, http: str,
              source: str, notes: str, relation: str = md.REL_SCHEMA,
              sanitizer: str = md.SAN_NOT_APPLICABLE, tier: str = md.TIER_GOLD) -> AttackCase:
    aid = f"malformed.{subfamily}"
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="malformed",
        original_text=None, attacked_text=None, is_raw=True,
        raw_body=raw_body, raw_headers=headers,
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="malformed", subfamily=subfamily,
        relation=relation, oracle=oracle, source=source, source_url=_OWASP_URL,
        validity_tier=tier, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=sanitizer, expected_http_behavior=http,
        notes=notes,
    ))
    return case


def _oversized_case(label: str, size_bytes: int) -> AttackCase:
    aid = f"malformed.oversized_{label}"
    text = "A" * size_bytes  # ASCII -> one byte per char, so len(text) == text-value bytes
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="malformed",
        original_text=None, attacked_text=text,
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="malformed", subfamily=f"oversized_{label}",
        relation=md.REL_AVAILABILITY, oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
        source="OWASP AI Testing Guide (oversized input)", source_url=_OWASP_URL,
        validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=md.SAN_V2_REJECTS_LENGTH,
        expected_http_behavior=md.HTTP_MEASURE,
        notes=(f"{label} TEXT-VALUE size ({size_bytes} bytes); the serialised HTTP body is a "
               "few bytes larger. V1 never truncates -> reaches the model; V2 rejects on length. "
               "Each size is a separate result so we find where V1 actually breaks."),
    ))
    return case


def _nested_case(depth: int) -> AttackCase:
    # Built as a raw string so we control exact depth without tripping Python's own
    # recursion limit while serialising a giant dict.
    raw_body = '{"text":' + '{"a":' * depth + '"x"' + "}" * depth + "}"
    return _raw_case(
        f"deeply_nested_json_d{depth}", raw_body, {"Content-Type": "application/json"},
        oracle=md.ORACLE_STAY_AVAILABLE, http=md.HTTP_MEASURE, relation=md.REL_AVAILABILITY,
        source="OWASP AI Testing Guide (input fuzzing)",
        notes=f"{depth}-level nested JSON; parser-depth stress. Part of a depth ladder to find "
              "the threshold. (Moved here from encoding: this is parser/availability, not encoding.)")


def standalone() -> list[AttackCase]:
    """All malformed + oversized + nesting payloads."""
    cases: list[AttackCase] = []

    cases.append(_raw_case(
        "broken_json", '{"text": "I am happy', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (malformed input)",
        notes="Unterminated string; JSON parser should reject with 4xx, not 5xx."))

    cases.append(_raw_case(
        "missing_field", '{"message": "I am happy"}', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)",
        notes="No `text` key; Pydantic should return 422 on both versions."))

    cases.append(_raw_case(
        "wrong_field_name", '{"txt": "I am happy"}', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)",
        notes="`txt` is not `text`; required field still missing -> 422 on both versions."))

    cases.append(_raw_case(
        "extra_field", '{"text": "I am happy", "surprise": "extra"}',
        {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_MEASURE,
        source="Pydantic extra-field handling (ignore vs forbid)",
        sanitizer=md.SAN_V2_REJECTS_EXTRA,
        notes=("THE clean before/after case: V1 default extra='ignore' should accept (200); "
               "V2 extra='forbid' should reject (422).")))

    cases.append(_raw_case(
        "wrong_content_type", '{"text": "I am happy"}', {"Content-Type": "text/plain"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (content-type confusion)",
        notes="JSON body labelled text/plain; endpoint should reject rather than mis-parse."))

    for depth in _NESTING_DEPTHS:
        cases.append(_nested_case(depth))

    for label, size in _OVERSIZE_SIZES.items():
        cases.append(_oversized_case(label, size))

    return cases

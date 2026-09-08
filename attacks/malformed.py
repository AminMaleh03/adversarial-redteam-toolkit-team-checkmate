"""
Category 1 - malformed and oversized payloads (standalone).

Covers the transport/schema boundary: broken JSON, missing/renamed/extra fields, a wrong
content type, and oversized bodies at three separate sizes. Framed against OWASP AI
Testing Guide input-fuzzing; expected outcomes are declared as hypotheses and measured.

Raw vs structured
-----------------
Anything whose exact bytes matter -- broken JSON, a wrong content-type header, or a body
shaped differently from ``{"text": "<string>"}`` -- is ``is_raw=True`` with a verbatim
``raw_body``, because the structured path can only serialise ``{"text": <str>}``. The
oversized payloads ARE ordinary ``{"text": "<huge string>"}`` requests, so they stay
structured; the string is built in code at request time and never committed to the repo.

The one genuine V1 vs V2 difference here
----------------------------------------
``extra_field`` ({"text": "...", "surprise": "..."}) is the clean before/after case:
V1 uses Pydantic's default (extra="ignore") and should accept it (200); V2 sets
extra="forbid" and should reject it (422). Contrast this with ``number``/type-confusion
in boundary.py, which is NOT a V1/V2 difference because plain Pydantic already rejects it.
"""

from __future__ import annotations

from contract import AttackCase
from attacks import metadata as md

_ONE_KIB = 1024
_OVERSIZE_SIZES = {
    "100kb": 100 * _ONE_KIB,
    "1mb": 1 * _ONE_KIB * _ONE_KIB,
    "10mb": 10 * _ONE_KIB * _ONE_KIB,
}


def _raw_case(subfamily: str, raw_body: str, headers: dict, *, oracle: str, http: str,
              source: str, notes: str, sanitizer: str = md.SAN_NOT_APPLICABLE,
              tier: str = md.TIER_GOLD) -> AttackCase:
    aid = f"malformed.{subfamily}"
    case = AttackCase(
        attack_id=aid,
        baseline_id=None,
        category="malformed",
        original_text=None,
        attacked_text=None,
        is_raw=True,
        raw_body=raw_body,
        raw_headers=headers,
    )
    md.register(
        case,
        md.AttackMetadata(
            attack_id=aid,
            family="malformed",
            subfamily=subfamily,
            relation=md.REL_SCHEMA,
            oracle=oracle,
            source=source,
            validity_tier=tier,
            semantic_risk="none",
            requires_baseline=False,
            expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=http,
            notes=notes,
        ),
    )
    return case


def _oversized_case(label: str, size_bytes: int) -> AttackCase:
    aid = f"malformed.oversized_{label}"
    # ASCII 'A' -> one byte per character, so len(text) == payload size in bytes.
    text = "A" * size_bytes
    case = AttackCase(
        attack_id=aid,
        baseline_id=None,
        category="malformed",
        original_text=None,
        attacked_text=text,
    )
    md.register(
        case,
        md.AttackMetadata(
            attack_id=aid,
            family="malformed",
            subfamily=f"oversized_{label}",
            relation=md.REL_AVAILABILITY,
            oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
            source="OWASP AI Testing Guide (oversized input)",
            validity_tier=md.TIER_GOLD,
            semantic_risk="none",
            requires_baseline=False,
            expected_sanitizer_behavior=md.SAN_V2_REJECTS_LENGTH,
            expected_http_behavior=md.HTTP_MEASURE,
            notes=(f"{label} body ({size_bytes} bytes). V1 never truncates -> reaches the model "
                   "and is expected to struggle; V2 rejects on the length limit. Each size is a "
                   "separate result so we find where V1 actually breaks."),
        ),
    )
    return case


def standalone() -> list[AttackCase]:
    """All malformed + oversized payloads."""
    cases: list[AttackCase] = []

    # Broken JSON that will not parse (required raw case).
    cases.append(_raw_case(
        "broken_json", '{"text": "I am happy', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (malformed input)",
        notes="Unterminated string; JSON parser should reject with 4xx, not 5xx.",
    ))

    # Missing the required `text` field.
    cases.append(_raw_case(
        "missing_field", '{"message": "I am happy"}', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)",
        notes="No `text` key; Pydantic should return 422 on both versions.",
    ))

    # Wrong field name (txt instead of text).
    cases.append(_raw_case(
        "wrong_field_name", '{"txt": "I am happy"}', {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)",
        notes="`txt` is not `text`; required field still missing -> 422 on both versions.",
    ))

    # Extra field alongside a valid text -- the clean V1/V2 difference.
    cases.append(_raw_case(
        "extra_field", '{"text": "I am happy", "surprise": "extra"}',
        {"Content-Type": "application/json"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_MEASURE,
        source="Pydantic extra-field handling (ignore vs forbid)",
        sanitizer=md.SAN_V2_REJECTS_EXTRA,
        notes=("THE clean before/after case: V1 default extra='ignore' should accept (200); "
               "V2 extra='forbid' should reject (422)."),
    ))

    # Valid JSON body sent with the wrong content type (required raw case).
    cases.append(_raw_case(
        "wrong_content_type", '{"text": "I am happy"}', {"Content-Type": "text/plain"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (content-type confusion)",
        notes="JSON body labelled text/plain; endpoint should reject rather than mis-parse.",
    ))

    # Oversized payloads at three separate sizes (structured; built in code).
    for label, size in _OVERSIZE_SIZES.items():
        cases.append(_oversized_case(label, size))

    return cases

"""
Category 1 - malformed, transport and oversized payloads (standalone).

Transport/schema boundary: broken JSON, missing/renamed/extra fields, wrong content type,
wrong top-level JSON shapes, duplicate keys, encoding-boundary bodies (UTF-8 BOM, invalid
UTF-8 bytes, trailing garbage, unusual escapes), a nested-JSON depth ladder, and oversized
text values at three sizes. Framed against the OWASP AI Testing Guide and RFC 8259 (JSON);
expected outcomes are hypotheses, measured.

Raw vs structured
-----------------
Anything whose exact bytes matter (broken JSON, wrong content-type, a non-``{"text":str}``
shape, or raw bytes) is is_raw=True with a verbatim raw_body -- which may be ``bytes`` for
the UTF-8-boundary cases, since AttackCase.raw_body supports bytes. The oversized payloads
are ordinary structured requests; the string is built in code and never committed.

The one genuine V1 vs V2 difference here
----------------------------------------
``extra_field`` is the clean before/after: V1 default extra="ignore" should accept (200);
V2 extra="forbid" should reject (422). Contrast ``boundary.type_confusion.number``, which
is NOT a V1/V2 difference because plain Pydantic already rejects it.
"""

from __future__ import annotations

from typing import Union

from contract import AttackCase
from attacks import metadata as md

_OWASP_URL = "https://owaspai.org/docs/5_testing/"
_JSON_RFC_URL = "https://www.rfc-editor.org/rfc/rfc8259"
_PYDANTIC_URL = "https://docs.pydantic.dev/latest/concepts/models/#extra-fields"

_ONE_KIB = 1024
_OVERSIZE_SIZES = {
    "100kb": 100 * _ONE_KIB,
    "1mb": 1 * _ONE_KIB * _ONE_KIB,
    "10mb": 10 * _ONE_KIB * _ONE_KIB,
}
_NESTING_DEPTHS = (32, 128, 512, 1024, 2000)


def _raw_case(subfamily: str, raw_body: Union[str, bytes], headers: dict, *, oracle: str,
              http: str, source: str, source_url: str, notes: str,
              relation: str = md.REL_SCHEMA, sanitizer: str = md.SAN_NOT_APPLICABLE,
              tier: str = md.TIER_GOLD) -> AttackCase:
    aid = f"malformed.{subfamily}"
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="malformed",
        original_text=None, attacked_text=None, is_raw=True,
        raw_body=raw_body, raw_headers=headers,
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="malformed", subfamily=subfamily,
        relation=relation, oracle=oracle, source=source, source_url=source_url,
        validity_tier=tier, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=sanitizer, expected_http_behavior=http,
        notes=notes,
    ))
    return case


def _oversized_case(label: str, size_bytes: int) -> AttackCase:
    aid = f"malformed.oversized_{label}"
    text = "A" * size_bytes  # ASCII -> one byte per char, so len(text) == text-value bytes
    case = AttackCase(attack_id=aid, baseline_id=None, category="malformed",
                      original_text=None, attacked_text=text)
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="malformed", subfamily=f"oversized_{label}",
        relation=md.REL_AVAILABILITY, oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
        source="OWASP AI Testing Guide (oversized input)", source_url=_OWASP_URL,
        validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=md.SAN_V2_REJECTS_LENGTH,
        expected_http_behavior=md.HTTP_MEASURE,
        notes=(f"{label} TEXT-VALUE size ({size_bytes} bytes); the serialised HTTP body is a "
               "few bytes larger. V1 never truncates -> reaches the model; V2 rejects on length. "
               "Each size is a separate result so we find where V1 actually breaks.")))
    return case


def _nested_case(depth: int) -> AttackCase:
    raw_body = '{"text":' + '{"a":' * depth + '"x"' + "}" * depth + "}"
    return _raw_case(
        f"deeply_nested_json_d{depth}", raw_body, {"Content-Type": "application/json"},
        oracle=md.ORACLE_STAY_AVAILABLE, http=md.HTTP_MEASURE, relation=md.REL_AVAILABILITY,
        source="OWASP AI Testing Guide (input fuzzing)", source_url=_OWASP_URL,
        notes=f"{depth}-level nested JSON; parser-depth stress, part of a depth ladder to find "
              "the threshold. (Parser/availability, not encoding.)")


def standalone() -> list[AttackCase]:
    """All malformed + transport + oversized + nesting payloads."""
    cases: list[AttackCase] = []
    json_ct = {"Content-Type": "application/json"}

    # --- classic malformed / schema ---
    cases.append(_raw_case("broken_json", '{"text": "I am happy', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (malformed input)", source_url=_OWASP_URL,
        notes="Unterminated string; JSON parser should reject with 4xx, not 5xx."))
    cases.append(_raw_case("missing_field", '{"message": "I am happy"}', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)", source_url=_OWASP_URL,
        notes="No `text` key; Pydantic should return 422 on both versions."))
    cases.append(_raw_case("wrong_field_name", '{"txt": "I am happy"}', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (schema fuzzing)", source_url=_OWASP_URL,
        notes="`txt` is not `text`; required field still missing -> 422 on both versions."))
    cases.append(_raw_case("extra_field", '{"text": "I am happy", "surprise": "extra"}', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_MEASURE,
        source="Pydantic extra-field handling (ignore vs forbid)", source_url=_PYDANTIC_URL,
        sanitizer=md.SAN_V2_REJECTS_EXTRA,
        notes="THE clean before/after case: V1 extra='ignore' accepts (200); V2 'forbid' rejects (422)."))
    cases.append(_raw_case("wrong_content_type", '{"text": "I am happy"}', {"Content-Type": "text/plain"},
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="OWASP AI Testing Guide (content-type confusion)", source_url=_OWASP_URL,
        notes="JSON body labelled text/plain; endpoint should reject rather than mis-parse."))

    # --- Expansion Pack 1: transport / JSON-boundary weirdness (RFC 8259) ---
    cases.append(_raw_case("duplicate_text_keys",
        '{"text": "I am happy", "text": "I am furious"}', json_ct,
        oracle=md.ORACLE_STAY_AVAILABLE, http=md.HTTP_MEASURE, relation=md.REL_AVAILABILITY,
        source="RFC 8259 (JSON): duplicate names have undefined behaviour", source_url=_JSON_RFC_URL,
        notes="Two `text` keys with conflicting values; observe which one wins and that it does not crash."))
    cases.append(_raw_case("top_level_array", '["I am happy"]', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="RFC 8259 (JSON): top-level value shape", source_url=_JSON_RFC_URL,
        notes="Top-level array instead of object; should be rejected as wrong shape."))
    cases.append(_raw_case("top_level_string", '"I am happy"', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="RFC 8259 (JSON): top-level value shape", source_url=_JSON_RFC_URL,
        notes="Top-level JSON string instead of object; should be rejected as wrong shape."))
    cases.append(_raw_case("top_level_number", '42', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="RFC 8259 (JSON): top-level value shape", source_url=_JSON_RFC_URL,
        notes="Top-level JSON number instead of object; should be rejected as wrong shape."))
    cases.append(_raw_case("utf8_bom",
        b"\xef\xbb\xbf" + b'{"text": "I am happy"}', json_ct,
        oracle=md.ORACLE_STAY_AVAILABLE, http=md.HTTP_MEASURE, relation=md.REL_AVAILABILITY,
        source="RFC 8259 (JSON): byte order mark handling", source_url=_JSON_RFC_URL,
        notes="UTF-8 BOM before valid JSON; some parsers strip it, some reject it -- must not crash."))
    cases.append(_raw_case("malformed_utf8",
        b'{"text": "' + b"\xff\xfe" + b'"}', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_MEASURE,
        source="RFC 8259 / UTF-8: invalid byte sequence", source_url=_JSON_RFC_URL,
        notes="Invalid UTF-8 bytes in the body; should be rejected cleanly, not 5xx."))
    cases.append(_raw_case("trailing_garbage", '{"text": "I am happy"} GARBAGE', json_ct,
        oracle=md.ORACLE_REQUEST_REJECTED, http=md.HTTP_EXPECT_4XX,
        source="RFC 8259 (JSON): trailing content", source_url=_JSON_RFC_URL,
        notes="Valid JSON followed by trailing non-JSON; should be rejected."))
    cases.append(_raw_case("unusual_json_escapes",
        '{"text": "I am \\u0068\\u0061\\u0070\\u0070\\u0079"}', json_ct,
        oracle=md.ORACLE_STAY_AVAILABLE, http=md.HTTP_EXPECT_200, relation=md.REL_AVAILABILITY,
        source="RFC 8259 (JSON): string escape sequences", source_url=_JSON_RFC_URL,
        notes=r'Valid \u escapes that decode to "I am happy"; should parse to normal text and classify.'))

    # --- depth ladder + oversized ---
    for depth in _NESTING_DEPTHS:
        cases.append(_nested_case(depth))
    for label, size in _OVERSIZE_SIZES.items():
        cases.append(_oversized_case(label, size))

    return cases

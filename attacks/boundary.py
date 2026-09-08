"""
Category 2 - boundary values and type confusion (standalone).

1. Type confusion (OWASP AI Testing Guide): a non-string JSON value where ``text`` is
   expected. The frozen ``AttackCase.attacked_text`` is typed ``str``, so ``123`` / ``null``
   / ``[...]`` / ``{...}`` cannot go through the dict-serialising path -- they are
   necessarily ``is_raw=True`` with an exact ``raw_body`` (valid JSON, wrong type).

2. Length boundaries around the ENFORCED limit, not a hardcoded number. This layer is
   model-blind, so:
     * with a real ``token_counter`` (+ ``max_tokens``) it emits exact N-1 / N / N+1 cases
       and records the measured token count; ``boundary_source="tokenizer"``.
     * with no counter (Amin's plain call) it emits coarse under / near / over cases from a
       word estimate; ``boundary_source="approximate_word_estimate"``.
   The real threshold is what the runner establishes -- Hugging Face truncation is
   configurable, so ``model_max_length`` is not guaranteed to be it.
"""

from __future__ import annotations

from typing import Callable, Optional

from contract import AttackCase
from attacks import metadata as md

# Used only as a target for generating candidate lengths in approximate mode. NOT treated
# as the real enforced limit -- that is measured by the runner. distilroberta's documented
# max is 512 tokens.
_ASSUMED_TOKEN_LIMIT = 512

TokenCounter = Callable[[str], int]


def _approx_tokens(text: str) -> int:
    """Cheap model-blind token estimate (~1.3 tokens per whitespace word)."""
    words = len(text.split())
    return max(1, round(words * 1.3))


def _text_up_to_tokens(target: int, counter: TokenCounter) -> str:
    """Largest filler text whose counter value is <= target. Guarded against runaway loops."""
    if target <= 0:
        return ""
    parts: list[str] = []
    guard = 0
    max_iters = target * 2 + 64  # a sane cap even if the counter is non-monotonic
    while counter((" ".join(parts + ["word"])).strip()) <= target and guard < max_iters:
        parts.append("word")
        guard += 1
    guard = 0
    while counter((" ".join(parts + ["x"])).strip()) <= target and guard < target + 64:
        parts.append("x")
        guard += 1
    return " ".join(parts) or "x"


def _text_over_tokens(target: int, counter: TokenCounter) -> str:
    """Filler text whose counter value is strictly greater than target."""
    text = _text_up_to_tokens(target, counter)
    guard = 0
    while counter(text) <= target and guard < 128:
        text = (text + " x").strip()
        guard += 1
    return text


def _raw_typed_case(subfamily: str, json_value_literal: str, notes: str) -> AttackCase:
    """Raw case whose body is  {"text": <json_value_literal>}  -- valid JSON, wrong type."""
    aid = f"boundary.type_confusion.{subfamily}"
    body = '{"text": ' + json_value_literal + "}"
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="boundary",
        original_text=None, attacked_text=None, is_raw=True,
        raw_body=body, raw_headers={"Content-Type": "application/json"},
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="boundary", subfamily=f"type_confusion_{subfamily}",
        relation=md.REL_SCHEMA, oracle=md.ORACLE_REQUEST_REJECTED,
        source="OWASP AI Testing Guide (type/argument confusion)",
        source_url="https://owaspai.org/docs/5_testing/",
        validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=md.SAN_NOT_APPLICABLE,
        expected_http_behavior=md.HTTP_EXPECT_4XX, notes=notes,
    ))
    return case


def _string_boundary_case(subfamily: str, text: str, *, sanitizer: str, http: str,
                          notes: str) -> AttackCase:
    aid = f"boundary.{subfamily}"
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="boundary",
        original_text=None, attacked_text=text,
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="boundary", subfamily=subfamily,
        relation=md.REL_BOUNDARY, oracle=md.ORACLE_STAY_AVAILABLE,
        source="Boundary-value analysis (classic test design)",
        validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
        position="none", expected_sanitizer_behavior=sanitizer, expected_http_behavior=http,
        notes=notes,
    ))
    return case


def _length_case(subfamily: str, text: str, *, sanitizer: str, http: str, source: str,
                 target: int, measured: int, notes: str) -> AttackCase:
    aid = f"boundary.length.{subfamily}"
    case = AttackCase(
        attack_id=aid, baseline_id=None, category="boundary",
        original_text=None, attacked_text=text,
    )
    md.register(case, md.AttackMetadata(
        attack_id=aid, family="boundary", subfamily=f"length_{subfamily}",
        relation=md.REL_BOUNDARY, oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
        source="Boundary-value analysis around the enforced length limit",
        validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
        position="none", boundary_source=source, boundary_target=target, boundary_measured=measured,
        expected_sanitizer_behavior=sanitizer, expected_http_behavior=http, notes=notes,
    ))
    return case


def standalone(*, token_counter: Optional[TokenCounter] = None,
               max_tokens: Optional[int] = None) -> list[AttackCase]:
    """
    All boundary + type-confusion payloads.

    No-argument call (Amin's runner) -> approximate length cases, tagged as such.
    Pass a real ``token_counter`` (and optionally ``max_tokens``) -> exact N-1 / N / N+1.
    """
    cases: list[AttackCase] = []

    # --- simple boundary strings (valid requests) ---
    cases.append(_string_boundary_case(
        "empty_string", "", sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_MEASURE,
        notes="Empty text: endpoint should handle without crashing."))
    cases.append(_string_boundary_case(
        "single_char", "a", sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
        notes="Minimum non-empty input."))
    cases.append(_string_boundary_case(
        "single_space", " ", sanitizer=md.SAN_V2_COLLAPSES_WS, http=md.HTTP_MEASURE,
        notes="V2 collapses+strips whitespace, so this becomes empty after cleaning; V1 does not."))

    # --- type confusion (raw, valid JSON with the wrong type for `text`) ---
    cases.append(_raw_typed_case("null", "null",
        notes="text=null. Pydantic rejects None for a str field; expect 4xx on both versions."))
    cases.append(_raw_typed_case("number", "123",
        notes=("text=123. Pydantic v2 does NOT coerce int->str, so BOTH V1 and V2 likely 422. "
               "Validation-contract test, NOT a V1/V2 difference -- verify empirically.")))
    cases.append(_raw_typed_case("boolean", "true",
        notes="text=true. Boolean where string expected; expect 4xx."))
    cases.append(_raw_typed_case("list", '["a", "b", "c"]',
        notes="text=[...]. Array where string expected; expect 4xx."))
    cases.append(_raw_typed_case("nested_object", '{"nested": {"deep": "value"}}',
        notes="text={...}. Object where string expected; expect 4xx."))

    # --- length boundaries ---
    limit = max_tokens or _ASSUMED_TOKEN_LIMIT
    if token_counter is not None:
        # Exact N-1 / N / N+1 using the real counter.
        for label, target in (("minus_one", limit - 1), ("at_limit", limit)):
            text = _text_up_to_tokens(target, token_counter)
            measured = token_counter(text)
            http = md.HTTP_EXPECT_200 if label == "minus_one" else md.HTTP_MEASURE
            cases.append(_length_case(
                label, text, sanitizer=md.SAN_NOT_APPLICABLE, http=http,
                source="tokenizer", target=target, measured=measured,
                notes=f"Exact boundary case: target={target} tokens, measured={measured}."))
        over_text = _text_over_tokens(limit, token_counter)
        over_measured = token_counter(over_text)
        cases.append(_length_case(
            "plus_one", over_text, sanitizer=md.SAN_V2_REJECTS_LENGTH, http=md.HTTP_MEASURE,
            source="tokenizer", target=limit + 1, measured=over_measured,
            notes=(f"Just over the limit: measured={over_measured}. V2 should reject (422) before "
                   "inference; V1 never truncates and feeds it to the model -- the core V1/V2 diff.")))
    else:
        # Coarse under / near / over from a word estimate.
        under = _text_up_to_tokens(limit // 2, _approx_tokens)
        near = _text_up_to_tokens(limit, _approx_tokens)
        over = _text_over_tokens(limit, _approx_tokens)
        cases.append(_length_case(
            "clearly_under", under, sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
            source="approximate_word_estimate", target=limit // 2, measured=_approx_tokens(under),
            notes="~half the assumed limit; both versions should accept."))
        cases.append(_length_case(
            "near_limit", near, sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_MEASURE,
            source="approximate_word_estimate", target=limit, measured=_approx_tokens(near),
            notes="Around the assumed limit (approximate; runner should re-measure exactly)."))
        cases.append(_length_case(
            "clearly_over", over, sanitizer=md.SAN_V2_REJECTS_LENGTH, http=md.HTTP_MEASURE,
            source="approximate_word_estimate", target=limit + limit // 2, measured=_approx_tokens(over),
            notes="Over the assumed limit: V2 should reject on length; V1 feeds the model."))

    return cases

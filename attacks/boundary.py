"""
Category 2 - boundary values and type confusion (standalone).

Two ideas from the research audit shape this file:

1. Type confusion is a documented root cause of ML-API bugs (OWASP AI Testing Guide:
   argument/type mismatch). We send a non-string JSON value where ``text`` is expected.
   Because the frozen ``AttackCase.attacked_text`` is typed ``str``, a JSON value like
   ``123`` / ``null`` / ``[...]`` / ``{...}`` cannot be produced by the normal
   dict-serialising path -- so these are necessarily ``is_raw=True`` with an exact
   ``raw_body``. This is a valid JSON body carrying the WRONG type, not broken JSON.

2. Boundaries should straddle the *actual* enforced limit, not a hardcoded number.
   Hugging Face lets an app pass ``max_length``, use the model default, or disable
   truncation, so ``tokenizer.model_max_length`` is not guaranteed to be the endpoint's
   real threshold. This layer is model-blind, so it builds cases around an *assumed*
   limit and records ``boundary_source="approximate_word_estimate"``. If the integration
   step injects a real token counter, the cases become exact and ``boundary_source``
   becomes ``"tokenizer"``. The real threshold is what the runner establishes; we only
   generate candidates that clearly sit under / near / over it.
"""

from __future__ import annotations

from typing import Callable, Optional

from contract import AttackCase
from attacks import metadata as md

# Assumed only as a target for generating candidate lengths. NOT treated as the real
# enforced limit -- that is measured. distilroberta's documented max is 512 tokens.
_ASSUMED_TOKEN_LIMIT = 512

TokenCounter = Callable[[str], int]


def _approx_tokens(text: str) -> int:
    """Cheap model-blind token estimate (~1.3 tokens per whitespace word)."""
    words = len(text.split())
    return max(1, round(words * 1.3))


def _text_of_token_length(target: int, counter: TokenCounter) -> str:
    """Grow filler text until ``counter`` reports the largest length <= target."""
    parts: list[str] = []

    def current() -> str:
        return " ".join(parts)

    while counter((current() + " word").strip()) <= target:
        parts.append("word")
    # fine-tune with single-character tokens to sit as close under the target as we can
    while counter((current() + " x").strip()) <= target:
        parts.append("x")
    return current() or "x"


def _raw_typed_case(subfamily: str, json_value_literal: str, notes: str) -> AttackCase:
    """
    Build a raw case whose body is  {"text": <json_value_literal>}  sent verbatim.

    Used for type-confusion values that cannot be represented as a Python str in
    attacked_text. The body is valid JSON carrying the wrong type for ``text``.
    """
    aid = f"boundary.type_confusion.{subfamily}"
    body = '{"text": ' + json_value_literal + "}"
    case = AttackCase(
        attack_id=aid,
        baseline_id=None,
        category="boundary",
        original_text=None,
        attacked_text=None,
        is_raw=True,
        raw_body=body,
        raw_headers={"Content-Type": "application/json"},
    )
    md.register(
        case,
        md.AttackMetadata(
            attack_id=aid,
            family="boundary",
            subfamily=f"type_confusion_{subfamily}",
            relation=md.REL_SCHEMA,
            oracle=md.ORACLE_REQUEST_REJECTED,
            source="OWASP AI Testing Guide (type/argument confusion)",
            validity_tier=md.TIER_GOLD,
            semantic_risk="none",
            requires_baseline=False,
            expected_sanitizer_behavior=md.SAN_NOT_APPLICABLE,
            expected_http_behavior=md.HTTP_EXPECT_4XX,
            notes=notes,
        ),
    )
    return case


def _string_boundary_case(subfamily: str, text: str, *, sanitizer: str,
                          http: str, notes: str) -> AttackCase:
    """Build a normal (structured) boundary case carrying a real string in attacked_text."""
    aid = f"boundary.{subfamily}"
    case = AttackCase(
        attack_id=aid,
        baseline_id=None,
        category="boundary",
        original_text=None,
        attacked_text=text,
    )
    md.register(
        case,
        md.AttackMetadata(
            attack_id=aid,
            family="boundary",
            subfamily=subfamily,
            relation=md.REL_BOUNDARY,
            oracle=md.ORACLE_STAY_AVAILABLE,
            source="Boundary-value analysis (classic test design)",
            validity_tier=md.TIER_GOLD,
            semantic_risk="none",
            requires_baseline=False,
            expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=http,
            notes=notes,
        ),
    )
    return case


def _length_boundary_case(subfamily: str, text: str, *, sanitizer: str, http: str,
                          boundary_source: str, target_tokens: int, notes: str) -> AttackCase:
    aid = f"boundary.length.{subfamily}"
    case = AttackCase(
        attack_id=aid,
        baseline_id=None,
        category="boundary",
        original_text=None,
        attacked_text=text,
    )
    md.register(
        case,
        md.AttackMetadata(
            attack_id=aid,
            family="boundary",
            subfamily=f"length_{subfamily}",
            relation=md.REL_BOUNDARY,
            oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
            source="Boundary-value analysis around the V2 length limit",
            validity_tier=md.TIER_GOLD,
            semantic_risk="none",
            requires_baseline=False,
            boundary_source=boundary_source,
            expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=http,
            notes=notes,
        ),
    )
    return case


def standalone(*, token_counter: Optional[TokenCounter] = None,
               max_tokens: Optional[int] = None) -> list[AttackCase]:
    """
    All boundary + type-confusion payloads.

    Callable with no arguments (Amin's runner does exactly that), in which case lengths
    are approximated and tagged as such. Pass a real ``token_counter`` (and optionally
    ``max_tokens``) to make the length-boundary cases exact.
    """
    cases: list[AttackCase] = []

    # --- simple boundary strings (valid requests) ---
    cases.append(_string_boundary_case(
        "empty_string", "",
        sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_MEASURE,
        notes="Empty text: endpoint should handle without crashing.",
    ))
    cases.append(_string_boundary_case(
        "single_char", "a",
        sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
        notes="Minimum non-empty input.",
    ))
    cases.append(_string_boundary_case(
        "single_space", " ",
        sanitizer=md.SAN_V2_COLLAPSES_WS, http=md.HTTP_MEASURE,
        notes="V2 collapses+strips whitespace, so this becomes empty after cleaning; V1 does not.",
    ))

    # --- type confusion (raw, valid JSON with the wrong type for `text`) ---
    cases.append(_raw_typed_case(
        "null", "null",
        notes="text=null. Pydantic rejects None for a str field; expect 4xx on both versions.",
    ))
    cases.append(_raw_typed_case(
        "number", "123",
        notes=("text=123. Pydantic v2 does NOT coerce int->str, so BOTH V1 and V2 likely 422. "
               "Kept as a validation-contract test, NOT as a V1/V2 difference -- verify empirically."),
    ))
    cases.append(_raw_typed_case(
        "boolean", "true",
        notes="text=true. Boolean where string expected; expect 4xx.",
    ))
    cases.append(_raw_typed_case(
        "list", '["a", "b", "c"]',
        notes="text=[...]. Array where string expected; expect 4xx.",
    ))
    cases.append(_raw_typed_case(
        "nested_object", '{"nested": {"deep": "value"}}',
        notes="text={...}. Object where string expected; expect 4xx.",
    ))

    # --- length boundaries around the (assumed or measured) token limit ---
    limit = max_tokens or _ASSUMED_TOKEN_LIMIT
    counter = token_counter or _approx_tokens
    boundary_source = "tokenizer" if token_counter else "approximate_word_estimate"

    under = _text_of_token_length(limit // 2, counter)
    near = _text_of_token_length(limit, counter)
    over = near + " " + " ".join(["word"] * (limit // 2))  # comfortably above the limit

    cases.append(_length_boundary_case(
        "clearly_under", under,
        sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
        boundary_source=boundary_source, target_tokens=limit // 2,
        notes=f"~{limit // 2} tokens (source={boundary_source}); both versions should accept.",
    ))
    cases.append(_length_boundary_case(
        "near_limit", near,
        sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_MEASURE,
        boundary_source=boundary_source, target_tokens=limit,
        notes=f"~{limit} tokens, at/just under the assumed limit (source={boundary_source}).",
    ))
    cases.append(_length_boundary_case(
        "clearly_over", over,
        sanitizer=md.SAN_V2_REJECTS_LENGTH, http=md.HTTP_MEASURE,
        boundary_source=boundary_source, target_tokens=limit + limit // 2,
        notes=("Over the assumed limit: V2 should reject with 422 before inference; "
               "V1 lets it reach the model (never truncated) -- the core V1/V2 difference."),
    ))

    return cases

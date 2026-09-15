"""
Deterministic generator for attacks/coverage_map.json.

The classification table below is the single source of truth. It is derived from attack
CONSTRUCTION and the three declared V2 controls, never from observed V1/V2 results. Run:

    python -m attacks.build_coverage_map        # writes attacks/coverage_map.json

A test (tests/test_attacks_coverage.py) asserts every generated core subfamily appears
here exactly once and that the committed file matches this generator's output.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from attacks.metadata import (
    CONTROL_LENGTH,
    CONTROL_NORMALIZATION,
    CONTROL_STRICT_TYPE_SCHEMA,
)

COVERAGE_MAP_VERSION = "1.0.0"
AUTHORED_UTC = "2026-09-15"

# The preserved core manifest this classification overlays/derives from. Its hash is a
# distinct artifact identity from the payload suite fingerprint -- Task 4 requires both.
SOURCE_MANIFEST_REL = "artifacts/benchmark_v6/run/manifest.json"

# Defense identity this classification is authored against (see docs/stage3/handoffs/lamei.md).
DEFENSE_IDENTITY = {
    "defense_commit": "257e15f3432aa29a3942d52b2cf3befb12ba3354",
    "v2_blob_oid": "b71787e3bf39e4062f883c9e34fae78d5b7c6263",
    "v2_repo_content_sha256": "b71193bef639410c828ec78e9aacc172e5da6a1c3b9fd8e5f7041ee6afc78baf",
    "foundation_recorded_sha256_crlf": "cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e",
    "note": (
        "v2.py git blob matches the foundation exactly; the foundation's SHA-256 was taken "
        "on a Windows/CRLF checkout, so the platform-independent (LF) content SHA-256 "
        "differs. Canonical identity: the git blob OID. Pending Ahsan's confirmation."
    ),
}

# The exact payload suite this classification maps (the planned-suite fingerprint).
SOURCE_SUITE_FINGERPRINT = (
    "7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430"
)

CONTROLS_DESC = {
    CONTROL_LENGTH: (
        "V2 rejects input whose TOKEN count exceeds the model limit, checked before "
        "inference. This is a post-parse token-length gate, NOT an HTTP/wire body-size limit."
    ),
    CONTROL_STRICT_TYPE_SCHEMA: (
        "V2 uses StrictStr + extra='forbid' on the request model; wrong types, missing/"
        "unknown fields and incompatible body shapes are rejected."
    ),
    CONTROL_NORMALIZATION: (
        "V2 applies NFKC + control/format-character stripping + whitespace collapse before "
        "inference."
    ),
}

CROSS_CUTTING_NOTE = (
    "The scoped exception handler (C3) is cross-cutting. Its observable responses are "
    "evaluated, but it is never listed in controls_targeted and never attributed as causal "
    "coverage by length/schema/normalization. A clean rejection may reflect framework/parser "
    "behaviour shared with V1, not V2 hardening."
)

_SHARED_V1 = " Rejection is shared with V1 (base validation); NOT evidence of incremental V2 hardening."
_TOKEN_NOT_BODY = (
    " NOTE: exercises the POST-PARSE token-length gate, not an HTTP/wire body-size limit; "
    "Rayyan records exact serialized body bytes separately."
)

IN, NOT, OUT, MIX = "in_scope", "not_targeted", "out_of_scope", "mixed"
LEN, TYP, NRM = CONTROL_LENGTH, CONTROL_STRICT_TYPE_SCHEMA, CONTROL_NORMALIZATION

# (family, subfamily, coverage_class, controls_targeted, rationale)
TABLE: list[tuple[str, str, str, list[str], str]] = [
    # ---- boundary ----
    ("boundary", "empty_string", NOT, [], "Valid empty text; no declared control alters or rejects an empty value."),
    ("boundary", "single_char", NOT, [], "Valid single-character text; no declared control acts."),
    ("boundary", "single_space", IN, [NRM], "Whitespace-only text; normalization is designed to collapse/strip it."),
    ("boundary", "type_confusion_null", IN, [TYP], "Non-string (null) for text; the strict type/schema control governs it." + _SHARED_V1),
    ("boundary", "type_confusion_number", IN, [TYP], "Non-string (number) for text; strict type/schema governs it." + _SHARED_V1),
    ("boundary", "type_confusion_boolean", IN, [TYP], "Non-string (boolean) for text; strict type/schema governs it." + _SHARED_V1),
    ("boundary", "type_confusion_list", IN, [TYP], "Non-string (array) for text; strict type/schema governs it." + _SHARED_V1),
    ("boundary", "type_confusion_nested_object", IN, [TYP], "Non-string (object) for text; strict type/schema governs it." + _SHARED_V1),
    ("boundary", "length_minus_one", IN, [LEN], "Text just under the token limit; exercises the length gate on the accept side." + _TOKEN_NOT_BODY),
    ("boundary", "length_at_limit", IN, [LEN], "Text at the token limit; exercises the length-gate boundary." + _TOKEN_NOT_BODY),
    ("boundary", "length_plus_one", IN, [LEN], "Text just over the token limit; the length control is designed to reject it." + _TOKEN_NOT_BODY),
    # Approximate-mode boundary variants (emitted only when no real token_counter is injected;
    # the runner always injects one, so in a canonical run these have zero cases -- kept so
    # build_suite never fails on a legitimate no-counter call). Same length-gate intent.
    ("boundary", "length_clearly_under", IN, [LEN], "Approximate-mode fallback of length_minus_one: text well under the token limit." + _TOKEN_NOT_BODY),
    ("boundary", "length_near_limit", IN, [LEN], "Approximate-mode fallback of length_at_limit: text near the token limit." + _TOKEN_NOT_BODY),
    ("boundary", "length_clearly_over", IN, [LEN], "Approximate-mode fallback of length_plus_one: text over the token limit." + _TOKEN_NOT_BODY),
    # ---- encoding ----
    ("encoding", "invisible_zero_width", IN, [NRM], "Zero-width (category Cf) chars; normalization's control-char strip is designed to remove them."),
    ("encoding", "deletion_backspace", IN, [NRM], "Backspace (Cc) control chars; normalization strip is designed to remove them."),
    ("encoding", "bidi_reorder", IN, [NRM], "Bidi directional-format (Cf) controls; normalization strip is designed to remove them."),
    ("encoding", "null_byte", IN, [NRM], "NUL (Cc); normalization strip is designed to remove it."),
    ("encoding", "compatibility_fullwidth", IN, [NRM], "Full-width compatibility characters; NFKC normalization is designed to fold them to ASCII."),
    ("encoding", "compatibility_ligature", IN, [NRM], "f-ligature compatibility characters; NFKC normalization is designed to fold them."),
    ("encoding", "homoglyph", NOT, [], "Cross-script Cyrillic confusables: by construction NFKC does NOT fold confusables (UTS #39 is separate from UAX #15) and they are letters, not control chars -- no declared control alters them; any effect is model-level."),
    ("encoding", "homoglyph_greek", NOT, [], "Cross-script Greek confusables: same NFKC gap as Cyrillic; no declared control alters them; any effect is model-level."),
    # ---- malformed ----
    ("malformed", "extra_field", IN, [TYP], "Unknown extra field beside valid text; V2 extra='forbid' is designed to reject it. This is the one case that differs from V1 (default 'ignore' accepts)."),
    ("malformed", "missing_field", IN, [TYP], "Required `text` absent; the schema/type validation surface governs it." + _SHARED_V1),
    ("malformed", "wrong_field_name", IN, [TYP], "`txt` not `text`: required field missing + unknown field present; schema/type governs it." + _SHARED_V1),
    ("malformed", "top_level_array", IN, [TYP], "JSON parses but the top-level value is an array, not the declared request object; schema/model validation rejects the body shape." + _SHARED_V1),
    ("malformed", "top_level_string", IN, [TYP], "Top-level JSON string, not the declared request object; schema/model validation rejects the body shape." + _SHARED_V1),
    ("malformed", "top_level_number", IN, [TYP], "Top-level JSON number, not the declared request object; schema/model validation rejects the body shape." + _SHARED_V1),
    ("malformed", "oversized_100kb", IN, [LEN], "Very large text value; once parsed it is exactly what the token-length control is designed to reject." + _TOKEN_NOT_BODY),
    ("malformed", "oversized_1mb", IN, [LEN], "Very large text value; once parsed it is exactly what the token-length control is designed to reject." + _TOKEN_NOT_BODY),
    ("malformed", "oversized_10mb", IN, [LEN], "Very large text value; once parsed it is exactly what the token-length control is designed to reject." + _TOKEN_NOT_BODY),
    ("malformed", "unusual_json_escapes", NOT, [], "Valid JSON \\u escapes that decode to ordinary text; the request is valid and no declared control alters it."),
    ("malformed", "broken_json", OUT, [], "Unparseable JSON; fails at JSON decoding before the declared controls (which see an already-parsed {text}) run. C3 may shape the response; no causal control attribution."),
    ("malformed", "wrong_content_type", OUT, [], "Valid JSON body labelled text/plain; content-type handling is transport/framework layer, before the declared controls."),
    ("malformed", "utf8_bom", OUT, [], "UTF-8 BOM prefix; byte-level decoding at the transport/parser layer, before the declared controls."),
    ("malformed", "malformed_utf8", OUT, [], "Invalid UTF-8 bytes; decoding fails at the transport/parser layer before the declared controls."),
    ("malformed", "trailing_garbage", OUT, [], "Valid JSON followed by trailing non-JSON; rejected at the parser layer before the declared controls."),
    ("malformed", "duplicate_text_keys", OUT, [], "Duplicate `text` keys; RFC 8259 leaves duplicate-name behaviour to the parser, which resolves the structure before Pydantic can inspect it -- parser semantics, not the schema control."),
    ("malformed", "deeply_nested_json_d32", MIX, [TYP], "Dual-purpose by construction: (1) parser-depth/resource behaviour before validation; AND (2) if parsing succeeds, `text` is a nested object (not a string), which the strict type/schema control rejects. Not classified by observed outcome."),
    ("malformed", "deeply_nested_json_d128", MIX, [TYP], "Dual-purpose: parser-depth before validation; and object-typed `text` rejected by strict type/schema if it parses. Construction-based, not outcome-based."),
    ("malformed", "deeply_nested_json_d512", MIX, [TYP], "Dual-purpose: parser-depth before validation; and object-typed `text` rejected by strict type/schema if it parses. Construction-based, not outcome-based."),
    ("malformed", "deeply_nested_json_d1024", MIX, [TYP], "Dual-purpose: parser-depth before validation; and object-typed `text` rejected by strict type/schema if it parses. Construction-based, not outcome-based."),
    ("malformed", "deeply_nested_json_d2000", MIX, [TYP], "Dual-purpose: parser-depth before validation; and object-typed `text` rejected by strict type/schema if it parses. Construction-based, not outcome-based."),
    # ---- perturbation (all model-level; normalization does not fix typos/casing) ----
    ("perturbation", "swap_adjacent", NOT, [], "Adjacent-letter swap in valid text; no declared control alters it -- model-level."),
    ("perturbation", "keyboard_typo", NOT, [], "Keyboard-neighbour typo in valid text; no declared control alters it -- model-level."),
    ("perturbation", "keyboard_typo_second_word", NOT, [], "Keyboard-neighbour typo on a second content word; no declared control alters it -- model-level."),
    ("perturbation", "delete_char", NOT, [], "Character deletion in valid text; no declared control alters it -- model-level."),
    ("perturbation", "word_split", NOT, [], "A single space inserted inside a word; not a whitespace run, so normalization does not collapse it -- model-level."),
    ("perturbation", "insert_char", NOT, [], "Character insertion in valid text; no declared control alters it -- model-level."),
    ("perturbation", "repeat_char", NOT, [], "Character repetition in valid text; no declared control alters it -- model-level."),
    ("perturbation", "misspell", NOT, [], "Common misspelling in valid text; no declared control alters it -- model-level."),
    ("perturbation", "capitalization", NOT, [], "Casing change in valid text; NFKC does not case-fold, so no declared control alters it -- model-level."),
    # ---- whitespace ----
    ("whitespace", "interior_runs", IN, [NRM], "Repeated interior spaces; normalization's whitespace collapse is designed to normalize them."),
    ("whitespace", "tabs", IN, [NRM], "Tabs; normalization's whitespace collapse is designed to normalize them."),
    ("whitespace", "newlines", IN, [NRM], "Newlines; normalization's whitespace collapse is designed to normalize them."),
    ("whitespace", "leading_trailing", IN, [NRM], "Leading/trailing whitespace; normalization strip is designed to remove it."),
    ("whitespace", "unicode_spaces", IN, [NRM], "Unicode space look-alikes; NFKC + whitespace collapse are designed to normalize them."),
    ("whitespace", "repeated_punctuation", NOT, [], "Repeated punctuation (not whitespace); no declared control removes punctuation; may shift intensity -- model-level."),
    # ---- truncation ----
    ("truncation", "signal_start_short", NOT, [], "Under-limit valid text, signal at start; positional/semantic -- no declared control acts."),
    ("truncation", "signal_end_short", NOT, [], "Under-limit valid text, signal at end; positional/semantic -- no declared control acts."),
    ("truncation", "signal_head_only", NOT, [], "Under-limit truncated head of the signal; no declared control acts -- model-level/diagnostic."),
    ("truncation", "signal_tail_only", NOT, [], "Under-limit truncated tail of the signal; no declared control acts -- model-level/diagnostic."),
    ("truncation", "signal_start_over_limit", IN, [LEN], "Signal + long filler exceeding the token limit; the length control is designed to reject it before inference." + _TOKEN_NOT_BODY),
    ("truncation", "signal_end_over_limit", IN, [LEN], "Signal + long filler exceeding the token limit; the length control is designed to reject it before inference." + _TOKEN_NOT_BODY),
]


def build() -> dict:
    subfamilies: dict[str, dict] = {}
    for family, subfamily, cls, controls, rationale in TABLE:
        if subfamily in subfamilies:
            raise ValueError(f"duplicate subfamily in TABLE: {subfamily}")
        subfamilies[subfamily] = {
            "family": family,
            "coverage_class": cls,
            "controls_targeted": controls,
            "coverage_rationale": rationale,
        }
    manifest_path = Path(__file__).resolve().parents[1] / SOURCE_MANIFEST_REL
    source_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    # Subfamily-weighted class counts (map-intrinsic; independent of baseline count). The
    # case-weighted view (which depends on the 42-baseline suite) is reported in the handover
    # alongside this one -- both denominators are always shown, never "65% of families".
    class_subfamily_counts = dict(sorted(
        Counter(d["coverage_class"] for d in subfamilies.values()).items()
    ))
    return {
        "coverage_map_version": COVERAGE_MAP_VERSION,
        "authored_utc": AUTHORED_UTC,
        "source_manifest_path": SOURCE_MANIFEST_REL,
        "source_manifest_sha256": source_manifest_sha256,
        "source_suite_fingerprint": SOURCE_SUITE_FINGERPRINT,
        "defense_identity": DEFENSE_IDENTITY,
        "controls": CONTROLS_DESC,
        "cross_cutting_note": CROSS_CUTTING_NOTE,
        "classification_basis": "attack construction + declared control design; never observed V1/V2 results",
        "class_subfamily_counts": class_subfamily_counts,
        "subfamilies": dict(sorted(subfamilies.items())),
        "case_exceptions": {},  # none needed: every subfamily is internally uniform
    }


def main() -> None:
    out_path = Path(__file__).with_name("coverage_map.json")
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(build(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    cmap = build()
    counts: dict[str, int] = {}
    for decl in cmap["subfamilies"].values():
        counts[decl["coverage_class"]] = counts.get(decl["coverage_class"], 0) + 1
    print(f"wrote {out_path.name}: {len(cmap['subfamilies'])} subfamilies -> {counts}")


if __name__ == "__main__":
    main()

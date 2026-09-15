"""
Builds the frozen OCES additional-evaluation data (Task 4, Phase 4). Owner: Lamei.

Pipeline:
  1. Select seeds DETERMINISTICALLY and MODEL-FREE from the committed baselines
     (emotion: 3 per each of the 7 labels; sentiment: 10 per label), by a fixed ordering
     rule -- never by any model output.
  2. Derive each seed's OCES CLEAN REQUEST = clean_text(raw source). This is the sanitation-
     invariant request actually sent for OCES; the exact raw source text is retained in
     provenance. (The committed CORE baselines are NOT modified -- this is a separate OCES
     artifact.)
  3. Join each seed with its AI-drafted paraphrase + neutral-distractor variant
     (baseline/oces/oces_content.py). The distractor is composed as
     "<clean request> + ' ' + <neutral clause>", so it never rewrites the request's
     casing/punctuation/tokenization -- it only ADDS one unrelated, affect-free sentence.
  4. Mechanical checks on EVERY clean request AND EVERY variant (CONTRACTS 6.6): valid non-
     empty JSON string, sanitation-invariant (frozen clean_text is a no-op), and within the
     token limit of BOTH pinned tokenizers (special tokens, no truncation).
  5. Freeze:
       baseline/oces/emotion_seeds.json      (clean requests: BaselineCase with the cleaned
       baseline/oces/sentiment_seeds.json     text; raw source kept in provenance)
       attacks/data/oces/emotion_cases.json  (AttackCase + AttackMetadata per variant;
       attacks/data/oces/sentiment_cases.json original_text = the clean request)
       attacks/data/oces/provenance.json     (selection rule, RAW source text, author,
                                              review status, coverage, tokenizer identities,
                                              lengths, distributions -- NO freeze commit)
       attacks/data/oces/oces_review_sheet.csv  (fast human-review sheet; decision blank)

Discipline enforced here:
  * NO model prediction (inference) on any seed or variant. Only the two tokenizers are used
    (length counting) -- never predict()/a label.
  * Candidates are AI-DRAFTED: `author` is recorded honestly and reviewer=null,
    review_method="ai_drafted_pending_human_review". Nothing is marked human-reviewed.
  * OCES authored AFTER the evaluated defenses were frozen, by authors aware of them:
    recorded as exposure; not a blind holdout, not design-independent.
  * Every OCES case gets an outcome-independent coverage declaration (CONTRACTS 6.5: a case
    with no valid declaration fails validation). By construction these are `not_targeted`:
    ordinary clean English designed to trigger none of V2's declared input controls.

Run from the repo root:  python -m baseline.oces.build_oces
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from transformers import AutoTokenizer

from contract import (
    AttackCase,
    COVERAGE_NOT_TARGETED,
    OCES_FAMILY_PARAPHRASE,
    OCES_FAMILY_DISTRACTOR,
    SUITE_OCES,
)
from baseline.load import load_baseline
from baseline.oces import oces_content
from attacks import coverage
from attacks import metadata as md

# --- frozen knobs ---------------------------------------------------------------------
GENERATOR_VERSION = "1.2.0"
AUTHORED_UTC = "2026-09-15"
TRANSFORM_VERSION = "oces-v1"
SOURCE = "oces-authored-v1"
AUTHOR = "AI draft (Claude Code); Task 4 owner: Lamei"

# Human review is complete (Phase 5): the Task 4 owner reviewed all 82 candidates with a
# ChatGPT-assisted semantic audit and accepted the current set (0 deleted, 0 rewrites, no
# GOLD promotion). Author stays the AI-draft attribution; reviewer/method are recorded
# honestly. REVIEW cases stay REVIEW.
REVIEWER = "Lamei (Task 4 owner)"
REVIEW_METHOD = "human semantic review by Lamei, assisted by ChatGPT"

EMOTION_PER_LABEL = 3
SENTIMENT_PER_LABEL = 10
TOKEN_LIMIT = 512                 # both models declare 512 incl. special tokens

# Required wording, verbatim in substance (CONTRACTS 6.6).
EXPOSURE_STATEMENT = (
    "additional evaluation authored after the evaluated defenses were frozen; the authors "
    "were aware of the defenses; not a blind holdout and not design-independent"
)

# Defense identity being frozen against (verified Phase 0; endpoint/v2.py is unchanged).
FOUNDATION_COMMIT = "257e15f3432aa29a3942d52b2cf3befb12ba3354"
V2_GIT_BLOB = "b71787e3bf39e4062f883c9e34fae78d5b7c6263"          # cross-platform content id
V2_LF_SHA256 = "b71193bef639410c828ec78e9aacc172e5da6a1c3b9fd8e5f7041ee6afc78baf"
V2_CRLF_SHA256 = "cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e"

# Outcome-independent coverage for every OCES case: by construction they are ordinary clean
# English that triggers none of V2's declared input controls, so they are `not_targeted`.
OCES_COVERAGE_RATIONALE = (
    "OCES clean semantic transformation (paraphrase / neutral distractor) in ordinary valid "
    "English: sanitation-invariant, well-formed and within the token limit, so by "
    "construction it triggers none of V2's declared input controls (normalization / "
    "strict_type_schema / length). Any label change is model-level, not control-mediated. "
    "Classification is from construction, never from observed results."
)

EMOTION_TOKENIZER = ("j-hartmann/emotion-english-distilroberta-base",
                     "0e1cd914e3d46199ed785853e12b57304e04178b")
SENTIMENT_TOKENIZER = ("distilbert/distilbert-base-uncased-finetuned-sst-2-english",
                       "714eb0fa89d2f80546fda750413ed43d93601a13")

REPO = Path(__file__).resolve().parents[2]
EMOTION_BASELINE = REPO / "baseline" / "baseline.json"
SENTIMENT_BASELINE = REPO / "baseline" / "sentiment_baseline.json"
SEEDS_DIR = REPO / "baseline" / "oces"
CASES_DIR = REPO / "attacks" / "data" / "oces"

_FAMILY = {"paraphrase": OCES_FAMILY_PARAPHRASE, "distractor": OCES_FAMILY_DISTRACTOR}


# --- frozen sanitizer MIRROR ----------------------------------------------------------
# Byte-for-byte mirror of endpoint/v2.py::clean_text (owner: Rayyan/Ahsan). Duplicated here
# ONLY so this builder needs no model import (endpoint.model loads weights at import). The
# equality of this mirror to the real frozen clean_text is asserted by
# tests/test_oces.py::test_clean_text_mirror_matches_frozen_sanitizer.
def _clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    visible = "".join(
        ch for ch in normalized
        if ch in (" ", "\t", "\n") or unicodedata.category(ch)[0] != "C"
    )
    return re.sub(r"\s+", " ", visible).strip()


# --- deterministic, model-free seed selection -----------------------------------------
def select_emotion_seeds() -> list:
    by_label = defaultdict(list)
    for case in load_baseline(EMOTION_BASELINE):
        by_label[case.label].append(case)
    seeds = []
    for label in sorted(by_label):                        # 7 labels, alphabetical
        chosen = sorted(by_label[label], key=lambda c: c.baseline_id)[:EMOTION_PER_LABEL]
        if len(chosen) < EMOTION_PER_LABEL:
            raise ValueError(f"emotion label {label!r}: need {EMOTION_PER_LABEL} seeds")
        seeds.extend(chosen)
    return seeds


def _sst_idx(baseline_id: str) -> int:
    return int(baseline_id.split("-")[-1])


def select_sentiment_seeds() -> list:
    by_label = defaultdict(list)
    for case in load_baseline(SENTIMENT_BASELINE):
        by_label[case.label].append(case)
    seeds = []
    for label in ("NEGATIVE", "POSITIVE"):
        chosen = sorted(by_label[label], key=lambda c: _sst_idx(c.baseline_id))[:SENTIMENT_PER_LABEL]
        if len(chosen) < SENTIMENT_PER_LABEL:
            raise ValueError(f"sentiment label {label!r}: need {SENTIMENT_PER_LABEL} seeds")
        seeds.extend(chosen)
    return seeds


# --- assembly + mechanical checks -----------------------------------------------------
def _counters(emo_tok, sent_tok):
    def count(tok, text):
        return len(tok.encode(text, add_special_tokens=True, truncation=False))
    return (lambda t: count(emo_tok, t)), (lambda t: count(sent_tok, t))


def _mechanical_check(what: str, text: str, emo_count, sent_count) -> dict:
    """Valid non-empty JSON string, sanitation-invariant, within both tokenizers' limits."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{what}: empty/invalid text")
    if _clean_text(text) != text:
        raise ValueError(f"{what}: not sanitation-invariant (clean_text changes it)")
    json.loads(json.dumps({"text": text}))                # valid JSON string round-trip
    lengths = {"emotion": emo_count(text), "sentiment": sent_count(text)}
    for name, length in lengths.items():
        if length >= TOKEN_LIMIT:
            raise ValueError(f"{what}: {length} {name} tokens >= limit {TOKEN_LIMIT}")
    return lengths


def _build_task(seeds, task, emo_count, sent_count, map_version):
    """Return (seed_records, cases, provenance_entries, review_rows) for one task."""
    seed_by_id = {s.baseline_id: s for s in seeds}
    seed_ids = list(seed_by_id)
    authored = oces_content.EMOTION_VARIANTS if task == "emotion" else oces_content.SENTIMENT_VARIANTS

    # every seed must have exactly one paraphrase and one distractor; no stray references
    fam_by_seed = defaultdict(set)
    for seed_id, family, *_ in authored:
        fam_by_seed[seed_id].add(family)
    for seed_id in seed_ids:
        if fam_by_seed[seed_id] != {"paraphrase", "distractor"}:
            raise ValueError(
                f"{seed_id}: expected one paraphrase + one distractor, got {sorted(fam_by_seed[seed_id])}"
            )
    extra = set(fam_by_seed) - set(seed_ids)
    if extra:
        raise ValueError(f"authored variants reference non-selected seeds: {sorted(extra)}")

    # ---- clean requests (the OCES originals) + their checks ----
    clean_request = {}
    request_lengths = {}
    for seed in seeds:
        req = _clean_text(seed.text)
        clean_request[seed.baseline_id] = req
        request_lengths[seed.baseline_id] = _mechanical_check(
            f"clean_request[{seed.baseline_id}]", req, emo_count, sent_count
        )

    seed_records = [
        {"baseline_id": s.baseline_id, "text": clean_request[s.baseline_id],
         "label": s.label, "source": s.source}
        for s in seeds
    ]

    cases, provenance, review_rows = [], {}, []
    seen_attack_ids = set()
    order = {"paraphrase": 0, "distractor": 1}
    for seed_id, family, subtype, payload, risk, tier, rationale in sorted(
        authored, key=lambda e: (seed_ids.index(e[0]), order[e[1]])
    ):
        seed = seed_by_id[seed_id]
        req = clean_request[seed_id]
        declared_family = _FAMILY[family]
        attack_id = f"{seed_id}.{declared_family}"
        if attack_id in seen_attack_ids:
            raise ValueError(f"duplicate OCES attack_id {attack_id!r}")
        seen_attack_ids.add(attack_id)

        # paraphrase carries the full text; distractor = clean request + " " + neutral clause
        if family == "paraphrase":
            variant_text = payload
        else:
            variant_text = f"{req} {payload}"
            if not variant_text.startswith(req + " "):          # causal-isolation guarantee
                raise ValueError(f"{attack_id}: distractor prefix != clean request")

        variant_lengths = _mechanical_check(attack_id, variant_text, emo_count, sent_count)

        meta = md.AttackMetadata(
            attack_id=attack_id, family=declared_family, subfamily=subtype,
            relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source=SOURCE, validity_tier=tier, semantic_risk=risk,
            requires_baseline=True, transform_version=TRANSFORM_VERSION,
            suite_id=SUITE_OCES, exposure=EXPOSURE_STATEMENT,
            declared_family=declared_family, notes=rationale,
            # outcome-independent coverage declaration (CONTRACTS 6.5)
            coverage_class=COVERAGE_NOT_TARGETED, controls_targeted=[],
            coverage_rationale=OCES_COVERAGE_RATIONALE, coverage_map_version=map_version,
        )
        case = AttackCase(
            attack_id=attack_id, baseline_id=seed_id, category=declared_family,
            original_text=req, attacked_text=variant_text, is_raw=False,
        )
        cases.append({"case": asdict(case), "metadata": asdict(meta)})

        provenance[attack_id] = {
            "seed_baseline_id": seed_id,
            "raw_source_text": seed.text,               # exact distributed text
            "clean_request": req,                        # sanitation-invariant OCES original
            "expected_label": seed.label,
            "family": declared_family,
            "transform_subtype": subtype,
            "distractor_clause": payload if family == "distractor" else None,
            "variant_text": variant_text,
            "rationale": rationale,
            "author": AUTHOR,
            "reviewer": REVIEWER,
            "review_method": REVIEW_METHOD,
            "semantic_risk": risk,
            "proposed_tier": tier,
            "coverage_class": COVERAGE_NOT_TARGETED,
            "controls_targeted": [],
            "clean_text_invariant": True,
            "tokenizer_lengths": {"clean_request": request_lengths[seed_id],
                                  "variant": variant_lengths},
        }
        review_rows.append({
            "case_id": attack_id, "task": task, "expected_label": seed.label,
            "clean_request": req, "raw_source_text": seed.text, "family": declared_family,
            "variant_text": variant_text, "rationale": rationale, "author": AUTHOR,
            "reviewer": REVIEWER, "semantic_risk": risk, "proposed_tier": tier,
            # accepted decisions: SILVER -> APPROVE, REVIEW -> KEEP_REVIEW (no GOLD promotion)
            "Lamei_decision": "APPROVE" if tier == "SILVER" else "KEEP_REVIEW",
        })
    return seed_records, cases, provenance, review_rows


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256_file(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _len_stats(values):
    """min / median / max of an integer list, integer-valued."""
    s = sorted(values)
    n = len(s)
    mid = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2
    return {"min": s[0], "median": mid, "max": s[-1], "n": n}


def _pre_freeze_summary(emo_seeds, sent_seeds, all_prov, tier_dist, risk_dist,
                        coverage_dist, subtype_dist, map_version):
    from collections import Counter
    seeds_by_label = Counter()
    for s in emo_seeds + sent_seeds:
        seeds_by_label[s.label] += 1
    fam = Counter(v["family"] for v in all_prov.values())
    # tokenizer length stats: clean requests (unique per seed) and variants
    req_seen, req_emo, req_sent, var_emo, var_sent = set(), [], [], [], []
    for v in all_prov.values():
        tl = v["tokenizer_lengths"]
        if v["seed_baseline_id"] not in req_seen:
            req_seen.add(v["seed_baseline_id"])
            req_emo.append(tl["clean_request"]["emotion"])
            req_sent.append(tl["clean_request"]["sentiment"])
        var_emo.append(tl["variant"]["emotion"])
        var_sent.append(tl["variant"]["sentiment"])
    all_lengths = req_emo + req_sent + var_emo + var_sent
    return {
        "seeds_by_label": dict(sorted(seeds_by_label.items())),
        "clean_requests": len(emo_seeds) + len(sent_seeds),
        "variants": len(all_prov),
        "total_additional_requests": (len(emo_seeds) + len(sent_seeds)) + len(all_prov),
        "family_counts": dict(sorted(fam.items())),
        "transform_subtype_distribution": dict(sorted(subtype_dist.items())),
        "tier_distribution": dict(sorted(tier_dist.items())),
        "semantic_risk_distribution": dict(sorted(risk_dist.items())),
        "coverage_distribution": dict(sorted(coverage_dist.items())),
        "coverage_map_version": map_version,
        "tokenizer_length": {
            "clean_request_emotion_tok": _len_stats(req_emo),
            "clean_request_sentiment_tok": _len_stats(req_sent),
            "variant_emotion_tok": _len_stats(var_emo),
            "variant_sentiment_tok": _len_stats(var_sent),
        },
        "token_limit": TOKEN_LIMIT,
        "all_comfortably_below_limit": max(all_lengths) < TOKEN_LIMIT,
        "defense_identity": {
            "foundation_commit": FOUNDATION_COMMIT,
            "endpoint_v2_git_blob": V2_GIT_BLOB,
            "endpoint_v2_lf_sha256": V2_LF_SHA256,
            "endpoint_v2_crlf_sha256": V2_CRLF_SHA256,
        },
        "model_prediction_queries_before_freeze": 0,
    }


def build():
    emo_tok = AutoTokenizer.from_pretrained(EMOTION_TOKENIZER[0], revision=EMOTION_TOKENIZER[1])
    sent_tok = AutoTokenizer.from_pretrained(SENTIMENT_TOKENIZER[0], revision=SENTIMENT_TOKENIZER[1])
    emo_count, sent_count = _counters(emo_tok, sent_tok)
    map_version = coverage.load_coverage_map()["coverage_map_version"]

    emo_seeds = select_emotion_seeds()
    sent_seeds = select_sentiment_seeds()

    emo_seed_rec, emo_cases, emo_prov, emo_rows = _build_task(
        emo_seeds, "emotion", emo_count, sent_count, map_version)
    sent_seed_rec, sent_cases, sent_prov, sent_rows = _build_task(
        sent_seeds, "sentiment", emo_count, sent_count, map_version)

    all_prov = {**emo_prov, **sent_prov}
    tier_dist = Counter(v["proposed_tier"] for v in all_prov.values())
    risk_dist = Counter(v["semantic_risk"] for v in all_prov.values())
    coverage_dist = Counter(v["coverage_class"] for v in all_prov.values())
    subtype_dist = Counter(v["transform_subtype"] for v in all_prov.values())
    summary = _pre_freeze_summary(emo_seeds, sent_seeds, all_prov, tier_dist, risk_dist,
                                  coverage_dist, subtype_dist, map_version)

    provenance = {
        "artifact": "oces",
        "generator_version": GENERATOR_VERSION,
        "authored_utc": AUTHORED_UTC,
        "generator": "baseline/oces/build_oces.py",
        "author": AUTHOR,
        "exposure_statement": EXPOSURE_STATEMENT,
        "oracle": "label_should_match_baseline (relation=invariant)",
        "families": [OCES_FAMILY_PARAPHRASE, OCES_FAMILY_DISTRACTOR],
        "no_model_inference": True,
        "no_inference_note": (
            "No predict()/label was run on any seed or variant while authoring or checking "
            "OCES. The only model assets used were the two tokenizers, for length counting."
        ),
        "clean_request_note": (
            "The OCES clean request is clean_text(raw source); it is sanitation-invariant and "
            "is the request actually sent. The exact raw source text is retained per variant. "
            "The committed core baselines are unchanged."
        ),
        "distractor_construction": (
            "distractor = clean_request + ' ' + neutral_clause; the clean request is the exact "
            "prefix, so no casing/punctuation/tokenization is rewritten -- only a neutral "
            "sentence is added."
        ),
        "coverage": {
            "note": "Every OCES case carries an outcome-independent declaration (CONTRACTS 6.5). "
                    "By construction all are not_targeted with zero targeted controls.",
            "coverage_map_version": map_version,
            "distribution": dict(sorted(coverage_dist.items())),
        },
        "review": {"method": REVIEW_METHOD, "reviewer": REVIEWER, "author": AUTHOR,
                   "status": "accepted; 0 deleted, 0 rewrites, no GOLD promotion",
                   "decisions": {"SILVER": "APPROVE", "REVIEW": "KEEP_REVIEW"},
                   "note": "AI-drafted candidates accepted after human semantic review by the "
                           "Task 4 owner (ChatGPT-assisted); human review does not auto-promote "
                           "to GOLD; REVIEW cases stay REVIEW and out of automatic rates"},
        "pre_freeze_summary": summary,
        "seed_selection": {
            "emotion": {
                "rule": "within each of the 7 labels, sort baselines by baseline_id and take "
                        "the first 3; model-free and deterministic",
                "per_label": EMOTION_PER_LABEL,
                "labels": sorted({s.label for s in emo_seeds}),
                "seed_ids": [s.baseline_id for s in emo_seeds],
            },
            "sentiment": {
                "rule": "within each label, sort baselines by ascending dataset idx and take "
                        "the first 10; model-free and deterministic",
                "per_label": SENTIMENT_PER_LABEL,
                "seed_ids": [s.baseline_id for s in sent_seeds],
            },
        },
        "tokenizers": {
            "emotion": {"id": EMOTION_TOKENIZER[0], "revision": EMOTION_TOKENIZER[1]},
            "sentiment": {"id": SENTIMENT_TOKENIZER[0], "revision": SENTIMENT_TOKENIZER[1]},
            "token_limit_checked": TOKEN_LIMIT,
            "check": "add_special_tokens=True, truncation=False; both tokenizers per clean "
                     "request AND per variant",
        },
        "counts": {
            "emotion_seeds": len(emo_seeds), "sentiment_seeds": len(sent_seeds),
            "emotion_variants": len(emo_cases), "sentiment_variants": len(sent_cases),
            "clean_requests": len(emo_seeds) + len(sent_seeds),
            "total_variants": len(emo_cases) + len(sent_cases),
        },
        "proposed_tier_distribution": dict(sorted(tier_dist.items())),
        "semantic_risk_distribution": dict(sorted(risk_dist.items())),
        "variants": all_prov,
    }

    # ---- write frozen artifacts ----
    _write_json(SEEDS_DIR / "emotion_seeds.json", emo_seed_rec)
    _write_json(SEEDS_DIR / "sentiment_seeds.json", sent_seed_rec)
    _write_json(CASES_DIR / "emotion_cases.json", emo_cases)
    _write_json(CASES_DIR / "sentiment_cases.json", sent_cases)
    _write_json(CASES_DIR / "provenance.json", provenance)

    review_path = CASES_DIR / "oces_review_sheet.csv"
    fields = ["case_id", "task", "expected_label", "clean_request", "raw_source_text",
              "family", "variant_text", "rationale", "author", "reviewer", "semantic_risk",
              "proposed_tier", "Lamei_decision"]
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(emo_rows + sent_rows)

    # ---- deterministic content-hash artifact (hashes the finalized freeze files; NOT itself) ----
    hashed = {
        "baseline/oces/emotion_seeds.json": _sha256_file(SEEDS_DIR / "emotion_seeds.json"),
        "baseline/oces/sentiment_seeds.json": _sha256_file(SEEDS_DIR / "sentiment_seeds.json"),
        "attacks/data/oces/emotion_cases.json": _sha256_file(CASES_DIR / "emotion_cases.json"),
        "attacks/data/oces/sentiment_cases.json": _sha256_file(CASES_DIR / "sentiment_cases.json"),
        "attacks/data/oces/provenance.json": _sha256_file(CASES_DIR / "provenance.json"),
        "baseline/oces/oces_content.py": _sha256_file(Path(oces_content.__file__)),
        "baseline/oces/build_oces.py": _sha256_file(Path(__file__)),
    }
    _write_json(CASES_DIR / "freeze_content_hashes.json", {
        "artifact": "oces_freeze_content_hashes",
        "generator_version": GENERATOR_VERSION,
        "coverage_map_version": map_version,
        "note": "SHA-256 of each finalized OCES freeze file (content identity for "
                "reproducibility). This file does not hash itself.",
        "files": hashed,
    })

    return provenance


def main():
    prov = build()
    c = prov["counts"]
    print(f"emotion: {c['emotion_seeds']} seeds -> {c['emotion_variants']} variants")
    print(f"sentiment: {c['sentiment_seeds']} seeds -> {c['sentiment_variants']} variants")
    print(f"clean requests checked: {c['clean_requests']}; total variants: {c['total_variants']}")
    print("proposed tiers:", prov["proposed_tier_distribution"])
    print("semantic risk :", prov["semantic_risk_distribution"])
    print("coverage      :", prov["coverage"]["distribution"])
    print("no model inference:", prov["no_model_inference"])


if __name__ == "__main__":
    main()

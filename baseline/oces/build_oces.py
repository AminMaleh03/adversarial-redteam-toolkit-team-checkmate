"""
Builds the frozen OCES additional-evaluation data (Task 4, Phase 4). Owner: Lamei.

Pipeline:
  1. Select seeds DETERMINISTICALLY and MODEL-FREE from the committed baselines
     (emotion: 3 per each of the 7 labels; sentiment: 10 per label), by a fixed ordering
     rule -- never by any model output.
  2. Join each seed with its hand-authored paraphrase + neutral-distractor variant
     (baseline/oces/oces_content.py).
  3. Run mechanical checks on every variant: valid non-empty JSON string, sanitation-
     invariant (the frozen clean_text is a no-op on it), and within the token limit of BOTH
     pinned tokenizers (special tokens included, no truncation).
  4. Freeze:
       baseline/oces/emotion_seeds.json      (BaselineCase clean requests, verbatim seeds)
       baseline/oces/sentiment_seeds.json
       attacks/data/oces/emotion_cases.json  (AttackCase + AttackMetadata per variant)
       attacks/data/oces/sentiment_cases.json
       attacks/data/oces/provenance.json     (selection rule, source text, review status,
                                              tokenizer identities, distributions -- NO
                                              freeze commit; that is recorded in Phase 5)
       attacks/data/oces/oces_review_sheet.csv  (fast human-review sheet, decision blank)

Discipline enforced here:
  * NO model prediction (inference) is run on any seed or variant. The only model assets
    touched are the two tokenizers (length counting) -- never predict()/a label.
  * Candidates are AI-drafted; the frozen output records reviewer=null and
    review_method="ai_drafted_pending_human_review". Nothing is marked human-reviewed.
  * OCES is authored AFTER the defenses were frozen, by authors who knew them: recorded as
    exposure, and NOT called a blind holdout.

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
    OCES_FAMILY_PARAPHRASE,
    OCES_FAMILY_DISTRACTOR,
    SUITE_OCES,
)
from baseline.load import load_baseline
from baseline.oces import oces_content
from attacks import metadata as md

# --- frozen knobs ---------------------------------------------------------------------
GENERATOR_VERSION = "1.0.0"
AUTHORED_UTC = "2026-09-15"
TRANSFORM_VERSION = "oces-v1"
SOURCE = "oces-authored-v1"

EMOTION_PER_LABEL = 3
SENTIMENT_PER_LABEL = 10
TOKEN_LIMIT = 512                 # both models declare 512 incl. special tokens

# Honest exposure wording (Task 4): NOT a blind holdout.
EXPOSURE_STATEMENT = (
    "additional evaluation authored after defense freeze; authors knew the defenses; "
    "not a blind or design-independent holdout"
)
REVIEW_METHOD = "ai_drafted_pending_human_review"

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


def _build_variants(seeds, emo_count, sent_count):
    """Return (cases, provenance_entries, review_rows) for one task's seeds."""
    seed_by_id = {s.baseline_id: s for s in seeds}
    seed_ids = list(seed_by_id)
    task = "emotion" if seeds and seeds[0].baseline_id.startswith(("dataset-", "handwritten-")) else "sentiment"
    authored = oces_content.EMOTION_VARIANTS if task == "emotion" else oces_content.SENTIMENT_VARIANTS

    # every seed must have exactly one paraphrase and one distractor
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

    cases, provenance, review_rows = [], {}, []
    seen_attack_ids = set()
    # deterministic order: seed selection order, paraphrase before distractor
    order = {"paraphrase": 0, "distractor": 1}
    for seed_id, family, subtype, text, risk, tier, rationale in sorted(
        authored, key=lambda e: (seed_ids.index(e[0]), order[e[1]])
    ):
        seed = seed_by_id[seed_id]
        declared_family = _FAMILY[family]
        attack_id = f"{seed_id}.{declared_family}"
        if attack_id in seen_attack_ids:
            raise ValueError(f"duplicate OCES attack_id {attack_id!r}")
        seen_attack_ids.add(attack_id)

        # ---- mechanical checks (no model prediction) ----
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{attack_id}: empty/invalid variant text")
        if _clean_text(text) != text:
            raise ValueError(
                f"{attack_id}: variant is NOT sanitation-invariant (clean_text changes it); "
                "OCES must be ordinary clean English"
            )
        json.loads(json.dumps({"text": text}))          # valid JSON string round-trip
        emo_len, sent_len = emo_count(text), sent_count(text)
        for name, length in (("emotion", emo_len), ("sentiment", sent_len)):
            if length >= TOKEN_LIMIT:
                raise ValueError(f"{attack_id}: {length} {name} tokens >= limit {TOKEN_LIMIT}")

        # ---- frozen metadata (constructed via the dataclass, so values are validated) ----
        meta = md.AttackMetadata(
            attack_id=attack_id, family=declared_family, subfamily=subtype,
            relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source=SOURCE, validity_tier=tier, semantic_risk=risk,
            requires_baseline=True, transform_version=TRANSFORM_VERSION,
            suite_id=SUITE_OCES, exposure=EXPOSURE_STATEMENT,
            declared_family=declared_family, notes=rationale,
        )
        case = AttackCase(
            attack_id=attack_id, baseline_id=seed_id, category=declared_family,
            original_text=seed.text, attacked_text=text, is_raw=False,
        )
        cases.append({"case": asdict(case), "metadata": asdict(meta)})

        provenance[attack_id] = {
            "seed_baseline_id": seed_id,
            "source_text": seed.text,                    # verbatim seed
            "expected_label": seed.label,
            "family": declared_family,
            "transform_subtype": subtype,
            "variant_text": text,
            "rationale": rationale,
            "semantic_risk": risk,
            "proposed_tier": tier,
            "review_method": REVIEW_METHOD,
            "reviewer": None,
            "clean_text_invariant": True,
            "tokenizer_lengths": {"emotion": emo_len, "sentiment": sent_len},
        }
        review_rows.append({
            "case_id": attack_id, "task": task, "expected_label": seed.label,
            "clean_text_seed": seed.text, "family": declared_family,
            "variant_text": text, "rationale": rationale,
            "semantic_risk": risk, "proposed_tier": tier, "Lamei_decision": "",
        })
    return cases, provenance, review_rows


def _seed_records(seeds):
    return [{"baseline_id": s.baseline_id, "text": s.text, "label": s.label, "source": s.source}
            for s in seeds]


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build():
    emo_tok = AutoTokenizer.from_pretrained(EMOTION_TOKENIZER[0], revision=EMOTION_TOKENIZER[1])
    sent_tok = AutoTokenizer.from_pretrained(SENTIMENT_TOKENIZER[0], revision=SENTIMENT_TOKENIZER[1])
    emo_count, sent_count = _counters(emo_tok, sent_tok)

    emo_seeds = select_emotion_seeds()
    sent_seeds = select_sentiment_seeds()

    emo_cases, emo_prov, emo_rows = _build_variants(emo_seeds, emo_count, sent_count)
    sent_cases, sent_prov, sent_rows = _build_variants(sent_seeds, emo_count, sent_count)

    all_prov = {**emo_prov, **sent_prov}
    tier_dist = Counter(v["proposed_tier"] for v in all_prov.values())
    risk_dist = Counter(v["semantic_risk"] for v in all_prov.values())

    provenance = {
        "artifact": "oces",
        "generator_version": GENERATOR_VERSION,
        "authored_utc": AUTHORED_UTC,
        "generator": "baseline/oces/build_oces.py",
        "exposure_statement": EXPOSURE_STATEMENT,
        "oracle": "label_should_match_baseline (relation=invariant)",
        "families": [OCES_FAMILY_PARAPHRASE, OCES_FAMILY_DISTRACTOR],
        "no_model_inference": True,
        "no_inference_note": (
            "No predict()/label was run on any seed or variant while authoring or checking "
            "OCES. The only model assets used were the two tokenizers, for length counting."
        ),
        "review": {"method": REVIEW_METHOD, "reviewer": None,
                   "note": "AI-drafted candidates; human semantic review pending; "
                           "proposed_tier is not a claim of human review"},
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
            "check": "add_special_tokens=True, truncation=False; both tokenizers per variant",
        },
        "counts": {
            "emotion_seeds": len(emo_seeds), "sentiment_seeds": len(sent_seeds),
            "emotion_variants": len(emo_cases), "sentiment_variants": len(sent_cases),
            "total_variants": len(emo_cases) + len(sent_cases),
        },
        "proposed_tier_distribution": dict(sorted(tier_dist.items())),
        "semantic_risk_distribution": dict(sorted(risk_dist.items())),
        "variants": all_prov,
    }

    # ---- write frozen artifacts ----
    _write_json(SEEDS_DIR / "emotion_seeds.json", _seed_records(emo_seeds))
    _write_json(SEEDS_DIR / "sentiment_seeds.json", _seed_records(sent_seeds))
    _write_json(CASES_DIR / "emotion_cases.json", emo_cases)
    _write_json(CASES_DIR / "sentiment_cases.json", sent_cases)
    _write_json(CASES_DIR / "provenance.json", provenance)

    review_path = CASES_DIR / "oces_review_sheet.csv"
    fields = ["case_id", "task", "expected_label", "clean_text_seed", "family",
              "variant_text", "rationale", "semantic_risk", "proposed_tier", "Lamei_decision"]
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(emo_rows + sent_rows)

    return provenance


def main():
    prov = build()
    c = prov["counts"]
    print(f"emotion: {c['emotion_seeds']} seeds -> {c['emotion_variants']} variants")
    print(f"sentiment: {c['sentiment_seeds']} seeds -> {c['sentiment_variants']} variants")
    print(f"total variants: {c['total_variants']}")
    print("proposed tiers:", prov["proposed_tier_distribution"])
    print("semantic risk :", prov["semantic_risk_distribution"])
    print("no model inference:", prov["no_model_inference"])


if __name__ == "__main__":
    main()

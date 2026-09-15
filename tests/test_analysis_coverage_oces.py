"""Coverage, OCES and remediation tests (Task 3 items 3-5). Owner: Khalid."""

import pytest

from contract import RunResult

from analysis import coverage as coverage_mod
from analysis import oces as oces_mod
from analysis import remediation as remediation_mod


class FakeEvaluation:
    def __init__(self, attack_id, bucket):
        self.attack_id = attack_id
        self.bucket = bucket


def overlay(entries, version="cov-1.0.0", is_overlay=True):
    return {
        "coverage_map_version": version,
        "is_overlay": is_overlay,
        "created_at_utc": "2026-09-15T00:00:00Z",
        "source_manifest_sha256": "a" * 64,
        "entries": entries,
    }


def entry(klass="in_scope", controls=("length",), family="malformed", subfamily="oversized_1mb"):
    return {
        "coverage_class": klass,
        "controls_targeted": list(controls),
        "coverage_rationale": "declared from case and control construction",
        "family": family,
        "subfamily": subfamily,
    }


class TestRateObject:
    def test_rate_carries_its_denominator(self):
        assert coverage_mod.rate(2, 10) == {"numerator": 2, "denominator": 10, "rate": 0.2}

    def test_zero_denominator_is_null_never_zero(self):
        result = coverage_mod.rate(0, 0)
        assert result["rate"] is None
        assert result["denominator"] == 0

    def test_no_eligible_cases_is_not_a_zero_failure_claim(self):
        # "no cases were eligible" and "no cases failed" are different claims.
        assert coverage_mod.rate(0, 0)["rate"] is not 0


class TestCoverageMap:
    def test_unknown_class_is_rejected_not_invented(self):
        with pytest.raises(ValueError, match="unknown coverage_class"):
            coverage_mod.load_coverage_map(
                overlay({"a1": entry(klass="made_up")}), sha256="x", source="t")

    def test_unknown_control_is_rejected(self):
        with pytest.raises(ValueError, match="unknown control"):
            coverage_mod.load_coverage_map(
                overlay({"a1": entry(controls=("telepathy",))}), sha256="x", source="t")

    def test_missing_rationale_is_rejected(self):
        bad = entry()
        del bad["coverage_rationale"]
        with pytest.raises(ValueError, match="coverage_rationale"):
            coverage_mod.load_coverage_map(overlay({"a1": bad}), sha256="x", source="t")

    def test_overlay_records_its_later_creation(self):
        cmap = coverage_mod.load_coverage_map(overlay({"a1": entry()}), sha256="x", source="t")
        assert cmap.is_overlay is True
        assert cmap.source_manifest_sha256 == "a" * 64


class TestCoverageCounts:
    def _build(self, **kwargs):
        cmap = coverage_mod.load_coverage_map(
            overlay({
                "a1": entry(klass="in_scope", controls=("length",)),
                "a2": entry(klass="in_scope", controls=("length", "normalization")),
                "a3": entry(klass="not_targeted", controls=()),
            }), sha256="s" * 64, source="run_artifact")
        defaults = dict(
            planned_attack_ids=["a1", "a2", "a3"],
            selected_attack_ids=["a1", "a2"],
            completed_attack_ids=["a1"],
            evaluations=[FakeEvaluation("a1", "fail")],
            coverage_map=cmap,
            require_declaration=True,
        )
        defaults.update(kwargs)
        return coverage_mod.build_coverage(**defaults)

    def test_counts_reconcile_with_planned_and_selected_ids(self):
        result = self._build()
        assert result["totals"]["planned"] == 3
        assert result["totals"]["selected"] == 2
        assert result["totals"]["completed"] == 1

    def test_not_selected_and_not_executed_stay_visible_separately(self):
        result = self._build()
        assert result["not_selected_attack_ids"] == ["a3"]
        assert result["not_executed_attack_ids"] == ["a2"]

    def test_failure_numerator_counts_a_case_once(self):
        result = self._build()
        assert result["classes"]["in_scope"]["failed_case_ids"] == ["a1"]
        assert result["classes"]["in_scope"]["failure_rate"]["numerator"] == 1

    def test_class_with_no_eligible_cases_reports_null_rate(self):
        result = self._build()
        assert result["classes"]["not_targeted"]["failure_rate"]["rate"] is None

    def test_per_control_counts_are_marked_as_overlapping(self):
        result = self._build()
        assert "must not be summed" in result["controls"]["note"]
        # a2 targets two controls, so control totals deliberately exceed the case count.
        per = result["controls"]["per_control"]
        assert per["length"]["selected"] + per["normalization"]["selected"] > 2

    def test_undeclared_attack_rejected_for_new_data(self):
        with pytest.raises(ValueError, match="no coverage declaration"):
            self._build(planned_attack_ids=["a1", "a2", "a3", "unknown"])

    def test_undeclared_attack_counted_not_classified_for_historical_data(self):
        result = self._build(planned_attack_ids=["a1", "a2", "a3", "legacy1"],
                             require_declaration=False)
        assert result["undeclared_attack_ids"] == ["legacy1"]
        assert result["classes"]["undeclared"]["planned"] == 1

    def test_classes_are_intent_not_causal_attribution(self):
        text = self._build()["interpretation"]["classes_are_intent"]
        assert "not effectiveness" in text and "not causal attribution" in text

    def test_error_handling_is_reported_as_cross_cutting(self):
        assert "no isolated causal proof" in \
            self._build()["interpretation"]["cross_cutting_error_handling"]


class TestMatchedDelta:
    def test_delta_uses_a_common_denominator(self):
        result = coverage_mod.matched_delta(
            coverage_mod.rate(5, 20), coverage_mod.rate(2, 20), 20)
        assert result["common_denominator"] == 20
        assert result["delta"] == pytest.approx(-0.15)

    def test_delta_is_null_without_a_common_denominator(self):
        result = coverage_mod.matched_delta(
            coverage_mod.rate(0, 0), coverage_mod.rate(2, 20), 0)
        assert result["delta"] is None


def oces_meta(tier="SILVER"):
    return {"validity_tier": tier}


def oces_row(label="joy", confidence=0.9, **overrides):
    fields = dict(
        case_type="attack", attack_id="p1", baseline_id="b1", category="perturbation",
        version="v1", status_code=200, response_body="{}", error=None,
        label=label, confidence=confidence, all_scores=None, latency_ms=5.0,
        latency_band="normal", endpoint_alive_after=True,
    )
    fields.update(overrides)
    return RunResult(**fields)


def clean_row(label="joy", confidence=0.9, **overrides):
    return oces_row(label=label, confidence=confidence, case_type="baseline",
                    attack_id=None, category=None, **overrides)


def classify(**kwargs):
    defaults = dict(case_id="p1", family="oces.paraphrase", target_id="emotion_v1",
                    meta=oces_meta(), clean=clean_row(), attacked=oces_row())
    defaults.update(kwargs)
    return oces_mod.classify_case(**defaults)


class TestOcesStatuses:
    def test_unchanged_label_meets_expectation(self):
        assert classify().status == oces_mod.STATUS_MEETS

    def test_changed_label_violates_expectation(self):
        result = classify(attacked=oces_row(label="anger"))
        assert result.status == oces_mod.STATUS_VIOLATES

    def test_review_tier_is_excluded_not_scored(self):
        result = classify(meta=oces_meta("REVIEW"), attacked=oces_row(label="anger"))
        assert result.status == oces_mod.STATUS_EXCLUDED
        assert "REVIEW" in result.reason

    def test_diagnostic_tier_is_excluded_not_scored(self):
        assert classify(meta=oces_meta("DIAGNOSTIC")).status == oces_mod.STATUS_EXCLUDED

    def test_low_clean_confidence_is_excluded(self):
        result = classify(clean=clean_row(confidence=0.4))
        assert result.status == oces_mod.STATUS_EXCLUDED
        assert "below" in result.reason

    def test_missing_row_is_not_executed_with_a_reason(self):
        result = classify(attacked=None)
        assert result.status == oces_mod.STATUS_NOT_EXECUTED
        assert result.reason

    def test_absent_prediction_is_unevaluable_never_successful_invariance(self):
        result = classify(attacked=oces_row(label=None, confidence=None, status_code=500))
        assert result.status == oces_mod.STATUS_UNEVALUABLE
        assert result.status != oces_mod.STATUS_MEETS

    def test_missing_clean_reference_is_unevaluable(self):
        assert classify(clean=None).status == oces_mod.STATUS_UNEVALUABLE

    def test_unsupported_family_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported OCES family"):
            classify(family="oces.negation")

    def test_every_planned_case_gets_exactly_one_status(self):
        assert classify().status in oces_mod.STATUSES


class TestOcesSummary:
    def test_rates_exclude_non_scored_statuses(self):
        outcomes = [
            classify(case_id="p1"),
            classify(case_id="p2", attacked=oces_row(label="anger")),
            classify(case_id="p3", meta=oces_meta("REVIEW")),
        ]
        summary = oces_mod.summarise(outcomes, target_id="emotion_v1")
        assert summary["violation_rate"]["denominator"] == 2
        assert summary["violation_rate"]["numerator"] == 1

    def test_induced_misclassification_needs_a_correct_clean_baseline(self):
        wrong_clean = classify(case_id="p1", attacked=oces_row(label="anger"),
                               reference_label="sadness")
        summary = oces_mod.summarise([wrong_clean], target_id="emotion_v1")
        family = summary["families"]["oces.paraphrase"]
        assert family["violation_rate"]["numerator"] == 1
        assert family["induced_misclassification"]["count"] == 0

    def test_author_exposure_statement_is_verbatim(self):
        summary = oces_mod.summarise([classify()], target_id="emotion_v1")
        assert summary["author_exposure"] == (
            "Additional evaluation authored after the evaluated defenses were frozen; the "
            "authors were aware of the defenses; not a blind holdout.")

    def test_block_keeps_oces_separate_from_core(self):
        block = oces_mod.build_oces_block(
            outcomes_by_target={"emotion_v1": [classify()]})
        assert "separately from the original core suite" in block["separation_note"]
        assert block["families"] == ["oces.paraphrase", "oces.distractor"]

    def test_every_planned_case_is_visible_with_its_evidence(self):
        block = oces_mod.build_oces_block(
            outcomes_by_target={"emotion_v1": [classify(case_id="p1")]})
        case = block["cases"]["emotion_v1"][0]
        assert case["case_id"] == "p1" and case["status"] and case["evidence_refs"]


class FakeFinding:
    def __init__(self, category="malformed", evidence=None):
        self.category = category
        self.evidence = evidence or ["mal.oversized_1mb"]
        self.finding_id = "F-1"


def remediation_row(attack_id="mal.oversized_1mb", **overrides):
    fields = dict(
        case_type="attack", attack_id=attack_id, baseline_id=None, category="malformed",
        version="v1", status_code=500, response_body="", error=None, label=None,
        confidence=None, all_scores=None, latency_ms=200.0, latency_band="normal",
        endpoint_alive_after=True,
    )
    fields.update(overrides)
    return RunResult(**fields)


class TestRemediation:
    def test_rules_load_with_a_version_and_hash(self):
        rules = remediation_mod.load_rules()
        assert rules["version"] and len(rules["sha256"]) == 64

    def test_rule_is_selected_by_observed_failure_not_finding_number(self):
        rules = remediation_mod.load_rules()
        chosen = remediation_mod.select_rule(
            rules, failure_mode="unhandled_5xx", family="malformed",
            subfamily="oversized_1mb")
        assert chosen["rule_id"] == "RM-5XX-OVERSIZED"

    def test_more_specific_subfamily_rule_wins(self):
        rules = remediation_mod.load_rules()
        chosen = remediation_mod.select_rule(
            rules, failure_mode="prediction_flip", family="encoding",
            subfamily="homoglyph")
        assert chosen["rule_id"] == "RM-FLIP-NORMALISABLE"

    def test_unknown_failure_mode_uses_the_marked_fallback(self):
        rules = remediation_mod.load_rules()
        chosen = remediation_mod.select_rule(
            rules, failure_mode="something_new", family="malformed", subfamily="x")
        assert chosen["rule_id"] == remediation_mod.FALLBACK_RULE_ID

    def test_detail_carries_evidence_specific_observations(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(), failure_mode="unhandled_5xx", subfamily="oversized_1mb",
            rows=[remediation_row()], target_id="emotion_v1",
            case_set_file="analysis/case_sets/ci_core_v1.json")
        assert detail["observed"]["status_distribution"] == {"500": 1}
        assert detail["observed"]["affected_case_count"] == 1

    def test_token_limit_is_never_claimed_to_stop_oversized_bodies(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(), failure_mode="unhandled_5xx", subfamily="oversized_1mb",
            rows=[remediation_row()], target_id="emotion_v1",
            case_set_file="analysis/case_sets/ci_core_v1.json")
        assert "token-count limit does not cover this" in detail["fix"]

    def test_generic_500_is_not_claimed_as_a_crash(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(category="encoding"), failure_mode="unhandled_5xx",
            subfamily="null_byte", rows=[remediation_row(attack_id="enc.null_byte")],
            target_id="emotion_v1", case_set_file="analysis/case_sets/ci_core_v1.json")
        text = (detail["significance"] + detail["fix"]).lower()
        assert "process death" not in text or "not evidence" in text
        assert detail["diagnosis_confidence"] in ("supported", "suspected")

    def test_model_level_weakness_states_its_limitation(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(category="perturbation", evidence=["p.typo"]),
            failure_mode="prediction_flip", subfamily="keyboard_typo",
            rows=[remediation_row(attack_id="p.typo", status_code=200, label="joy",
                                  confidence=0.8)],
            target_id="emotion_v1", case_set_file="analysis/case_sets/ci_core_v1.json")
        assert "limitation" in detail
        assert "No endpoint control fixes it" in detail["limitation"]

    def test_verification_names_the_affected_target_and_a_real_case_set(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(), failure_mode="unhandled_5xx", subfamily="oversized_1mb",
            rows=[remediation_row()], target_id="sentiment_v1",
            case_set_file="analysis/case_sets/ci_core_v1.json")
        verification = detail["verification"]
        assert verification["target_id"] == "sentiment_v1"
        # A sentiment finding is never rerouted to emotion_v2 as its fix.
        assert "emotion_v2" not in verification["command"]
        assert verification["command"].startswith("python -m runner.run")
        assert verification["expected"]

    def test_missing_body_evidence_is_stated_not_filled_in(self):
        detail = remediation_mod.build_remediation_detail(
            finding=FakeFinding(), failure_mode="unhandled_5xx", subfamily="oversized_1mb",
            rows=[remediation_row()], target_id="emotion_v1",
            case_set_file="analysis/case_sets/ci_core_v1.json")
        joined = " ".join(detail["unavailable_evidence"])
        assert "cannot be reconstructed" in joined

    def test_legacy_remediation_string_is_evidence_specific(self):
        finding = FakeFinding()
        detail = remediation_mod.build_remediation_detail(
            finding=finding, failure_mode="unhandled_5xx", subfamily="oversized_1mb",
            rows=[remediation_row()], target_id="emotion_v1",
            case_set_file="analysis/case_sets/ci_core_v1.json")
        text = remediation_mod.build_finding_remediation_string(detail, finding)
        assert "500" in text and text.endswith(detail["fix"])

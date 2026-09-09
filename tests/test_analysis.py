"""Tests for drift detection, severity tiering, and the V1 versus V2 comparison.

Everything here runs against synthetic RunResult rows and hand-written manifest entries
(plain dicts, exactly as they come back from ``json.load`` on manifest.json) -- no real
runner output is required. Owner: Khalid.
"""

import dataclasses
import json

import pytest

from contract import RunResult

from analysis import analyze, compare, drift, severity

# ----------------------------------------------------------------------------------------
# fixture factories
# ----------------------------------------------------------------------------------------


def make_result(**overrides) -> RunResult:
    defaults = dict(
        case_type="attack",
        attack_id="a1",
        baseline_id="b1",
        category="encoding",
        version="v1",
        status_code=200,
        response_body='{"label":"joy","confidence":0.9,"all_scores":{}}',
        error=None,
        label="joy",
        confidence=0.9,
        all_scores={},
        latency_ms=100.0,
        latency_band="normal",
        endpoint_alive_after=True,
    )
    defaults.update(overrides)
    return RunResult(**defaults)


def make_baseline(baseline_id="b1", label="joy", confidence=0.9, version="v1", **overrides) -> RunResult:
    defaults = dict(
        case_type="baseline",
        attack_id=None,
        baseline_id=baseline_id,
        category=None,
        version=version,
        status_code=200,
        response_body="{}",
        error=None,
        label=label,
        confidence=confidence,
        all_scores={},
        latency_ms=50.0,
        latency_band="normal",
        endpoint_alive_after=True,
    )
    defaults.update(overrides)
    return RunResult(**defaults)


def make_meta(
    attack_id="a1",
    family="encoding",
    subfamily="homoglyph",
    oracle="label_should_match_baseline",
    validity_tier="SILVER",
    requires_baseline=True,
    **overrides,
) -> dict:
    meta = dict(
        attack_id=attack_id,
        family=family,
        subfamily=subfamily,
        relation="invariant",
        oracle=oracle,
        source="test",
        validity_tier=validity_tier,
        semantic_risk="none",
        requires_baseline=requires_baseline,
    )
    meta.update(overrides)
    return meta


# ==========================================================================================
# drift.py
# ==========================================================================================


class TestDriftFlipRule:
    def test_flip_at_exact_threshold_qualifies(self):
        clean = make_baseline(confidence=0.6, label="joy")
        attacked = make_result(label="sadness", confidence=0.8)
        record = drift.evaluate_pair("a1", "b1", "v1", clean, attacked, make_meta())
        assert record.status == "eligible"
        assert record.qualifying_flip is True

    def test_flip_below_threshold_does_not_qualify(self):
        clean = make_baseline(confidence=0.59, label="joy")
        attacked = make_result(label="sadness", confidence=0.8)
        record = drift.evaluate_pair("a1", "b1", "v1", clean, attacked, make_meta())
        assert record.status == "excluded"
        assert record.reason == drift.EXCLUDE_LOW_CLEAN_CONFIDENCE

    def test_unchanged_label_is_not_a_flip(self):
        clean = make_baseline(confidence=0.93, label="joy")
        attacked = make_result(label="joy", confidence=0.81)
        record = drift.evaluate_pair("a1", "b1", "v1", clean, attacked, make_meta())
        assert record.status == "eligible"
        assert record.qualifying_flip is False

    def test_do_not_lower_threshold_after_seeing_results(self):
        # 0.6 is a hard cutoff, not a heuristic: just under it never qualifies no matter
        # how confident the attacked prediction becomes.
        clean = make_baseline(confidence=0.4655, label="neutral")
        attacked = make_result(label="anger", confidence=0.99)
        record = drift.evaluate_pair("a1", "b1", "v1", clean, attacked, make_meta())
        assert record.status == "excluded"
        assert record.qualifying_flip is False


class TestDriftPairingAndSkips:
    def test_missing_baseline_id_skipped_cleanly(self):
        standalone = make_result(attack_id="a-standalone", baseline_id=None)
        manifest = {"a-standalone": make_meta(attack_id="a-standalone", requires_baseline=False)}
        summary = drift.compute_drift([standalone], manifest)
        assert summary.eligible == 0
        assert summary.excluded == {}
        assert summary.unevaluable == {}
        assert summary.records == []

    def test_v1_attack_pairs_only_with_v1_baseline(self):
        v1_clean = make_baseline(baseline_id="b1", label="joy", confidence=0.9, version="v1")
        v1_attack = make_result(attack_id="a1", baseline_id="b1", version="v1", label="joy", confidence=0.8)
        manifest = {"a1": make_meta()}
        # A V2 "clean" result must never leak into a V1 computation: compute_drift only
        # ever looks inside the single results list it is given.
        summary = drift.compute_drift([v1_clean, v1_attack], manifest)
        assert summary.eligible == 1
        assert summary.records[0].version == "v1"

    def test_missing_clean_result_is_unevaluable_not_a_pass(self):
        attacked = make_result(attack_id="a1", baseline_id="b-missing")
        manifest = {"a1": make_meta()}
        summary = drift.compute_drift([attacked], manifest)
        assert summary.eligible == 0
        assert summary.unevaluable == {drift.UNEVAL_MISSING_CLEAN_RESULT: 1}

    def test_missing_attacked_prediction_is_unevaluable_not_a_pass(self):
        clean = make_baseline(confidence=0.9)
        attacked = make_result(status_code=500, response_body="", label=None, confidence=None)
        manifest = {"a1": make_meta()}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.eligible == 0
        assert summary.unevaluable == {drift.UNEVAL_MISSING_ATTACKED_PREDICTION: 1}

    def test_missing_clean_prediction_is_unevaluable(self):
        clean = make_baseline(label=None, confidence=None)
        attacked = make_result()
        manifest = {"a1": make_meta()}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.unevaluable == {drift.UNEVAL_MISSING_CLEAN_PREDICTION: 1}

    @pytest.mark.parametrize(
        "attacked_kwargs",
        [
            dict(status_code=500, response_body="", label=None, confidence=None),
            dict(status_code=None, error="timeout: no response", latency_band="timeout", label=None, confidence=None),
            dict(status_code=None, error="connection_error: boom", label=None, confidence=None),
        ],
    )
    def test_5xx_timeout_connection_failure_stay_out_of_denominator(self, attacked_kwargs):
        clean = make_baseline(confidence=0.9)
        attacked = make_result(**attacked_kwargs)
        manifest = {"a1": make_meta()}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.eligible == 0
        assert summary.qualifying_flips == 0

    def test_zero_eligible_gives_na(self):
        summary = drift.DriftSummary()
        assert summary.flip_rate is None

    def test_diagnostic_case_excluded_from_drift(self):
        clean = make_baseline(confidence=0.9)
        attacked = make_result(label="sadness", confidence=0.8)
        manifest = {"a1": make_meta(validity_tier="DIAGNOSTIC")}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.eligible == 0
        assert summary.excluded == {drift.EXCLUDE_DIAGNOSTIC: 1}

    def test_unresolved_review_excluded_from_drift(self):
        clean = make_baseline(confidence=0.9)
        attacked = make_result(label="sadness", confidence=0.8)
        manifest = {"a1": make_meta(validity_tier="REVIEW")}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.eligible == 0
        assert summary.excluded == {drift.EXCLUDE_REVIEW_UNRESOLVED: 1}

    def test_oracle_without_baseline_comparison_excluded(self):
        clean = make_baseline(confidence=0.9)
        attacked = make_result(status_code=422, label=None, confidence=None)
        manifest = {"a1": make_meta(oracle="request_should_be_rejected_cleanly")}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.excluded == {drift.EXCLUDE_NOT_LABEL_ORACLE: 1}

    def test_dataset_label_is_context_only_never_the_reference(self):
        # The clean reference is the model's OWN prediction, never the dataset label the
        # baseline was built to represent -- a flip is judged purely model-against-model.
        clean = make_baseline(label="fear", confidence=0.9)  # model disagreed with dataset intent
        attacked = make_result(label="fear", confidence=0.85)
        manifest = {"a1": make_meta()}
        summary = drift.compute_drift([clean, attacked], manifest)
        assert summary.records[0].qualifying_flip is False


# ==========================================================================================
# severity.py
# ==========================================================================================


class TestSeverityBaseOutcomes:
    @pytest.mark.parametrize(
        "failure_mode, context, expected_score, expected_tier",
        [
            (severity.FINDING_SERVICE_UNAVAILABLE, {}, 100.0, "Critical"),
            (severity.FINDING_UNHANDLED_5XX, {}, 70.0, "High"),
            (severity.FINDING_INFO_LEAK, {}, 65.0, "High"),
            (severity.FINDING_TIMEOUT, {}, 60.0, "High"),
            (severity.FINDING_PREDICTION_FLIP, {"clean_confidence": 0.6}, 40.0, "Medium"),
            (severity.FINDING_INVALID_INPUT_ACCEPTED, {"accepted_confidence": 0.1}, 30.0, "Low"),
            (severity.FINDING_SLOW_RESPONSE, {"seconds": 2.0}, 20.0, "Low"),
        ],
    )
    def test_frozen_base_weight_and_tier(self, failure_mode, context, expected_score, expected_tier):
        score, tier = severity.compute_severity(failure_mode, **context)
        assert score == expected_score
        assert tier == expected_tier

    def test_unknown_failure_mode_rejected(self):
        with pytest.raises(ValueError):
            severity.compute_severity("not_a_real_finding")


class TestFlipAdjustment:
    def test_max_confidence_reaches_exactly_60_and_high(self):
        score, tier = severity.compute_severity(severity.FINDING_PREDICTION_FLIP, clean_confidence=1.00)
        assert score == 60.0
        assert tier == "High"

    def test_just_under_max_stays_medium(self):
        score, tier = severity.compute_severity(severity.FINDING_PREDICTION_FLIP, clean_confidence=0.99)
        assert score == 59.5
        assert tier == "Medium"

    def test_high_confidence_stays_medium(self):
        score, tier = severity.compute_severity(severity.FINDING_PREDICTION_FLIP, clean_confidence=0.95)
        assert score == 57.5
        assert tier == "Medium"

    def test_adjustment_capped_at_20(self):
        # A confidence above 1.0 should not exist in practice, but the cap must hold anyway.
        assert severity.flip_adjustment(2.0) == 20.0

    def test_scores_are_not_rounded_up_before_tiering(self):
        # 59.5 must not round to 60 and jump a tier.
        _, tier = severity.compute_severity(severity.FINDING_PREDICTION_FLIP, clean_confidence=0.99)
        assert tier != "High"


class TestOtherAdjustments:
    def test_leak_stack_or_path_adjustment(self):
        score, tier = severity.compute_severity(severity.FINDING_INFO_LEAK, leak_kind="stack_or_path")
        assert score == 85.0
        assert tier == "Critical"

    def test_leak_internal_names_only_adjustment(self):
        score, tier = severity.compute_severity(severity.FINDING_INFO_LEAK, leak_kind="internal_names")
        assert score == 70.0
        assert tier == "High"

    def test_invalid_input_confident_answer_adjustment(self):
        score, _ = severity.compute_severity(
            severity.FINDING_INVALID_INPUT_ACCEPTED, accepted_confidence=0.61
        )
        assert score == 40.0

    def test_invalid_input_low_confidence_no_adjustment(self):
        score, _ = severity.compute_severity(
            severity.FINDING_INVALID_INPUT_ACCEPTED, accepted_confidence=0.2
        )
        assert score == 30.0

    def test_slow_response_adjustment_scales_and_caps(self):
        score, _ = severity.compute_severity(severity.FINDING_SLOW_RESPONSE, seconds=6.0)
        assert score == 20.0 + (6.0 - 2.0) * 2.0
        capped_score, _ = severity.compute_severity(severity.FINDING_SLOW_RESPONSE, seconds=100.0)
        assert capped_score == 20.0 + 16.0

    @pytest.mark.parametrize(
        "subfamily, base_finding, expected",
        [
            ("oversized_100kb", severity.FINDING_UNHANDLED_5XX, 90.0),
            ("oversized_1mb", severity.FINDING_TIMEOUT, 70.0),
            ("oversized_10mb", severity.FINDING_TIMEOUT, 60.0),
        ],
    )
    def test_size_dependent_adjustment_reads_subfamily_not_notes(self, subfamily, base_finding, expected):
        score, _ = severity.compute_severity(base_finding, subfamily=subfamily)
        assert score == expected

    def test_adjustment_never_applied_across_finding_types(self):
        # A subfamily context on prediction_flip must not accidentally pick up the size table.
        score, _ = severity.compute_severity(
            severity.FINDING_PREDICTION_FLIP, subfamily="oversized_100kb", clean_confidence=0.6
        )
        assert score == 40.0


class TestGroupScoring:
    def test_group_uses_highest_instance_never_a_sum(self):
        score, tier = severity.score_group([44.0, 47.0, 55.0])
        assert score == 55.0
        assert tier == "Medium"

    def test_repeated_identical_scores_do_not_raise_severity(self):
        score, _ = severity.score_group([55.0, 55.0, 55.0, 55.0])
        assert score == 55.0

    def test_empty_group_rejected(self):
        with pytest.raises(ValueError):
            severity.score_group([])

    def test_connection_failure_has_request_failure_weight(self):
        assert severity.compute_severity("connection_failure", subfamily="oversized_100kb") == (70.0, "High")
        assert "connection_error" not in severity.BASE_WEIGHTS


# ==========================================================================================
# analyze.py -- per-case oracle evaluation, leak detection, grouping, category stats
# ==========================================================================================


class TestDiagnosticAndReviewHandling:
    def test_diagnostic_case_never_auto_scored(self):
        result = make_result(status_code=500, response_body="Traceback (most recent call last)")
        meta = make_meta(validity_tier="DIAGNOSTIC")
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "diagnostic"
        assert evaluation.instances == []

    def test_review_case_never_promoted_to_a_vulnerability(self):
        result = make_result(status_code=500, endpoint_alive_after=False)
        meta = make_meta(validity_tier="REVIEW")
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "review"
        assert evaluation.instances == []


class TestLeakDetection:
    def test_stack_trace_detected(self):
        body = 'Traceback (most recent call last):\n  File "app.py", line 1\nValueError'
        assert analyze.detect_leak(body) == "stack_or_path"

    def test_windows_absolute_path_detected(self):
        body = '{"detail": "error at C:\\\\Users\\\\amin\\\\app\\\\endpoint\\\\v1.py"}'
        assert analyze.detect_leak(body) == "stack_or_path"

    def test_unix_absolute_path_detected(self):
        body = '{"detail": "failed reading /home/amin/app/endpoint/v1.py"}'
        assert analyze.detect_leak(body) == "stack_or_path"

    def test_internal_module_name_without_path_detected(self):
        body = '{"detail": "starlette.exceptions.HTTPException raised"}'
        assert analyze.detect_leak(body) == "internal_names"

    def test_clean_response_not_flagged(self):
        assert analyze.detect_leak('{"label":"joy","confidence":0.9}') is None

    def test_ordinary_422_validation_body_not_leakage(self):
        body = '{"detail":[{"loc":["body","text"],"msg":"field required","type":"value_error.missing"}]}'
        assert analyze.detect_leak(body) is None

    def test_real_pydantic_v2_422_body_not_leakage(self):
        # Pydantic v2's default error output includes a public docs URL on every ordinary
        # validation error -- it contains the substring "pydantic." incidentally, and must
        # not be enough on its own to classify a normal 422 as an information leak.
        body = (
            '{"detail":[{"type":"string_type","loc":["body","text"],'
            '"msg":"Input should be a valid string","input":123,'
            '"url":"https://errors.pydantic.dev/2.9/v/string_type"}]}'
        )
        assert analyze.detect_leak(body) is None

    def test_empty_body_not_flagged(self):
        assert analyze.detect_leak("") is None
        assert analyze.detect_leak(None) is None


class TestOracleLookup:
    def test_label_should_match_baseline_pass(self):
        result = make_result(label="joy")
        meta = make_meta(oracle="label_should_match_baseline")
        drift_record = drift.DriftRecord(
            "a1", "b1", "v1", "eligible", None, qualifying_flip=False, clean_label="joy", clean_confidence=0.9
        )
        evaluation = analyze.evaluate_case(result, meta, drift_record)
        assert evaluation.bucket == "pass"

    def test_label_should_match_baseline_fail_gives_qualifying_flip(self):
        result = make_result(label="sadness", confidence=0.81)
        meta = make_meta(oracle="label_should_match_baseline")
        drift_record = drift.DriftRecord(
            "a1", "b1", "v1", "eligible", None, qualifying_flip=True,
            clean_label="joy", clean_confidence=0.93, attacked_label="sadness", attacked_confidence=0.81,
        )
        evaluation = analyze.evaluate_case(result, meta, drift_record)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_PREDICTION_FLIP]
        assert evaluation.instances[0].context["clean_confidence"] == 0.93

    def test_request_should_be_rejected_cleanly_pass_on_4xx(self):
        result = make_result(status_code=422, response_body='{"detail":[]}', label=None, confidence=None)
        meta = make_meta(oracle="request_should_be_rejected_cleanly", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "pass"

    def test_request_should_be_rejected_cleanly_fails_on_2xx_accept(self):
        result = make_result(status_code=200, confidence=0.9)
        meta = make_meta(oracle="request_should_be_rejected_cleanly", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_INVALID_INPUT_ACCEPTED]

    def test_request_should_be_rejected_cleanly_fails_on_5xx(self):
        result = make_result(status_code=500, response_body="", label=None, confidence=None)
        meta = make_meta(oracle="request_should_be_rejected_cleanly", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert severity.FINDING_UNHANDLED_5XX in [i.failure_mode for i in evaluation.instances]

    def test_graceful_or_truncate_under_limit_200_is_a_pass(self):
        # The name is misleading: an under-limit case answering normally is a pass, not a
        # failure, despite carrying the "graceful failure" oracle.
        result = make_result(status_code=200, confidence=0.9)
        meta = make_meta(
            oracle="endpoint_should_fail_gracefully_or_apply_documented_truncation",
            requires_baseline=False,
        )
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "pass"

    def test_graceful_or_truncate_fails_on_timeout(self):
        result = make_result(
            status_code=None, error="timeout: no response within 10s", latency_band="timeout",
            label=None, confidence=None,
        )
        meta = make_meta(
            oracle="endpoint_should_fail_gracefully_or_apply_documented_truncation",
            subfamily="oversized_10mb", requires_baseline=False,
        )
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_TIMEOUT]

    def test_stay_available_fails_regardless_of_status_code(self):
        # A 200 with a dead health check afterwards is still service unavailability.
        result = make_result(status_code=200, confidence=0.9, endpoint_alive_after=False)
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_SERVICE_UNAVAILABLE]

    def test_stay_available_pass_when_alive(self):
        result = make_result(status_code=500, response_body="", label=None, confidence=None)
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        # Still fails (the 5xx is cross-cutting) but not via service_unavailable.
        assert severity.FINDING_SERVICE_UNAVAILABLE not in [i.failure_mode for i in evaluation.instances]

    def test_no_leak_oracle_pass(self):
        result = make_result(status_code=422, response_body='{"detail":"bad input"}', label=None, confidence=None)
        meta = make_meta(oracle="error_response_must_not_leak_internals", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "pass"

    def test_no_leak_oracle_fails_on_leak(self):
        result = make_result(
            status_code=500, response_body="Traceback (most recent call last):", label=None, confidence=None
        )
        meta = make_meta(oracle="error_response_must_not_leak_internals", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert severity.FINDING_INFO_LEAK in [i.failure_mode for i in evaluation.instances]

    def test_diagnostic_oracle_never_evaluated_even_when_it_looks_terrible(self):
        result = make_result(
            status_code=500, response_body="Traceback (most recent call last):",
            endpoint_alive_after=False, label=None, confidence=None,
        )
        meta = make_meta(oracle="diagnostic_no_fixed_oracle", validity_tier="DIAGNOSTIC", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "diagnostic"
        assert evaluation.instances == []


class TestConnectionFailureHandling:
    def test_connection_failure_alone_is_scored(self):
        result = make_result(status_code=None, error="connection_error: boom", label=None, confidence=None)
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_CONNECTION_FAILURE]
        assert evaluation.is_connection_failure is True

    def test_connection_failure_with_health_failure_scores_service_unavailable(self):
        result = make_result(
            status_code=None, error="connection_error: boom", endpoint_alive_after=False,
            label=None, confidence=None,
        )
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.bucket == "fail"
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_SERVICE_UNAVAILABLE,
                                                                severity.FINDING_CONNECTION_FAILURE]

    @pytest.mark.parametrize(
        "error_text",
        [
            "connection_error: ConnectError: boom",
            "transport_error: RemoteProtocolError: boom",
            # Detection must not depend on the runner's exact error-message prefix, only
            # on the structural fact "no status code, and not a timeout".
            "ConnectionResetError: boom",
            "",
            None,
        ],
    )
    def test_connection_failure_detected_structurally_not_by_error_string(self, error_text):
        result = make_result(
            status_code=None, error=error_text, latency_band="normal", label=None, confidence=None
        )
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.is_connection_failure is True
        assert evaluation.bucket == "fail"

    def test_timeout_is_never_misclassified_as_a_connection_failure(self):
        result = make_result(
            status_code=None, error="timeout: no response within 10s", latency_band="timeout",
            label=None, confidence=None,
        )
        meta = make_meta(oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluation = analyze.evaluate_case(result, meta, None)
        assert evaluation.is_connection_failure is False
        assert [i.failure_mode for i in evaluation.instances] == [severity.FINDING_TIMEOUT]


class TestGrouping:
    def _evaluations(self, n_5xx=2, n_leak=1):
        evaluations = []
        for i in range(n_5xx):
            result = make_result(attack_id=f"homoglyph-{i}", status_code=500, response_body="", label=None, confidence=None)
            meta = make_meta(attack_id=f"homoglyph-{i}", subfamily="homoglyph", requires_baseline=False)
            evaluations.append(analyze.evaluate_case(result, meta, None))
        for i in range(n_leak):
            result = make_result(
                attack_id=f"homoglyph-leak-{i}", status_code=500,
                response_body="Traceback (most recent call last):", label=None, confidence=None,
            )
            meta = make_meta(attack_id=f"homoglyph-leak-{i}", subfamily="homoglyph", requires_baseline=False)
            evaluations.append(analyze.evaluate_case(result, meta, None))
        return evaluations

    def test_repeated_variants_group_into_one_finding(self):
        evaluations = self._evaluations(n_5xx=3, n_leak=0)
        findings, meta, groups = analyze.build_findings(evaluations, "v1")
        assert len(findings) == 1
        assert len(findings[0].evidence) == 3
        assert set(findings[0].evidence) == {"homoglyph-0", "homoglyph-1", "homoglyph-2"}

    def test_different_failure_modes_produce_separate_findings(self):
        evaluations = self._evaluations(n_5xx=2, n_leak=1)
        findings, meta, groups = analyze.build_findings(evaluations, "v1")
        failure_modes = {meta[f.finding_id]["failure_mode"] for f in findings}
        assert failure_modes == {severity.FINDING_UNHANDLED_5XX, severity.FINDING_INFO_LEAK}
        assert len(findings) == 2

    def test_every_finding_carries_remediation(self):
        evaluations = self._evaluations()
        findings, _, _ = analyze.build_findings(evaluations, "v1")
        for finding in findings:
            assert finding.remediation
            assert isinstance(finding.remediation, str)

    def test_grouping_scores_the_group_not_a_sum(self):
        evaluations = self._evaluations(n_5xx=5, n_leak=0)
        findings, _, _ = analyze.build_findings(evaluations, "v1")
        assert findings[0].severity_score == 70.0  # unhandled_5xx base, never 5 * 70


class TestCategoryStats:
    def test_two_of_ten_is_20_percent_not_2(self):
        evaluations = []
        for i in range(8):
            r = make_result(attack_id=f"p{i}", category="perturbation", label="joy", confidence=0.9)
            m = make_meta(attack_id=f"p{i}", family="perturbation", requires_baseline=False)
            evaluations.append(analyze.evaluate_case(r, m, None))
        for i in range(2):
            r = make_result(attack_id=f"f{i}", category="perturbation", status_code=500, response_body="", label=None, confidence=None)
            m = make_meta(attack_id=f"f{i}", family="perturbation", requires_baseline=False)
            evaluations.append(analyze.evaluate_case(r, m, None))
        stats = analyze.compute_category_stats(evaluations)
        assert stats["perturbation"]["eligible"] == 10
        assert stats["perturbation"]["failed"] == 2
        assert stats["perturbation"]["failure_rate"] == pytest.approx(0.2)

    def test_zero_eligible_gives_none_internally_and_na_in_summary(self):
        stats = analyze.compute_category_stats([])
        assert stats["boundary"]["failure_rate"] is None
        assert analyze.format_rate(stats["boundary"]["failure_rate"]) == "N/A"

    def test_diagnostic_and_review_excluded_from_denominator(self):
        r1 = make_result(attack_id="d1", category="truncation")
        m1 = make_meta(attack_id="d1", family="truncation", validity_tier="DIAGNOSTIC", requires_baseline=False)
        r2 = make_result(attack_id="r1", category="truncation", status_code=500, response_body="", label=None, confidence=None)
        m2 = make_meta(attack_id="r1", family="truncation", validity_tier="REVIEW", requires_baseline=False)
        evaluations = [analyze.evaluate_case(r1, m1, None), analyze.evaluate_case(r2, m2, None)]
        stats = analyze.compute_category_stats(evaluations)
        assert stats["truncation"]["eligible"] == 0
        assert stats["truncation"]["diagnostic"] == 1
        assert stats["truncation"]["review"] == 1
        assert stats["truncation"]["failure_rate"] is None

    def test_connection_failure_enters_category_failure_rate(self):
        r = make_result(attack_id="c1", category="malformed", status_code=None, error="connection_error: boom", label=None, confidence=None)
        m = make_meta(attack_id="c1", family="malformed", oracle="endpoint_should_stay_available", requires_baseline=False)
        evaluations = [analyze.evaluate_case(r, m, None)]
        stats = analyze.compute_category_stats(evaluations)
        assert stats["malformed"]["unevaluable"] == 0
        assert stats["malformed"]["eligible"] == 1
        assert stats["malformed"]["failed"] == 1


# ==========================================================================================
# compare.py -- coverage, fingerprints, resolution
# ==========================================================================================


def make_run_meta(planned_fp="fp1", manifest_sha="m1", planned=10, completed=10, missing=None, skipped=None):
    missing = missing or []
    skipped = skipped or []
    return {
        "fingerprints": {"planned_suite_sha256": planned_fp, "manifest_sha256": manifest_sha},
        "coverage": {
            "planned": planned, "completed": completed,
            "missing": len(missing), "skipped": len(skipped),
            "coverage_rate": completed / planned if planned else 0.0,
        },
        "case_ids": {
            "planned": [f"attack:x{i}" for i in range(planned)],
            "completed": [f"attack:x{i}" for i in range(planned) if f"attack:x{i}" not in missing and f"attack:x{i}" not in skipped],
            "missing": missing,
            "skipped": skipped,
            "limit_excluded": [],
        },
    }


class TestFingerprintChecks:
    def test_matching_fingerprint_does_not_imply_full_coverage(self):
        meta_v1 = make_run_meta(planned=10, completed=4)
        meta_v2 = make_run_meta(planned=10, completed=10)
        check = compare.check_fingerprints(meta_v1, meta_v2)
        assert check.planned_match is True
        # Coverage is a separate computation entirely.
        assert meta_v1["coverage"]["completed"] != meta_v2["coverage"]["completed"]

    def test_mismatched_planned_fingerprint_blocks_whole_suite_claim(self):
        meta_v1 = make_run_meta(planned_fp="fp1")
        meta_v2 = make_run_meta(planned_fp="fp2")
        check = compare.check_fingerprints(meta_v1, meta_v2)
        assert check.planned_match is False
        assert check.whole_suite_comparable is False

    def test_mismatched_manifest_hash_blocks_whole_suite_claim(self):
        meta_v1 = make_run_meta(manifest_sha="m1")
        meta_v2 = make_run_meta(manifest_sha="m2")
        check = compare.check_fingerprints(meta_v1, meta_v2)
        assert check.manifest_match is False
        assert check.whole_suite_comparable is False

    def test_planned_size_unaffected_by_a_limited_run(self):
        # A smoke run reduces `completed`, never `planned`.
        meta = make_run_meta(planned=1928, completed=40)
        assert meta["coverage"]["planned"] == 1928


class TestCoverageComparison:
    def test_matched_v1_only_v2_only_and_unavailable(self):
        meta_v1 = make_run_meta(planned=3, completed=3)
        meta_v1["case_ids"]["completed"] = ["attack:a", "attack:b", "attack:c"]
        meta_v2 = make_run_meta(planned=3, completed=2, missing=["attack:c"])
        meta_v2["case_ids"]["completed"] = ["attack:a", "attack:b"]
        result = compare.compare_coverage(meta_v1, meta_v2)
        assert result.matched == ["attack:a", "attack:b"]
        assert result.v1_only == ["attack:c"]
        assert result.v2_only == []
        assert "attack:c" in result.unavailable


class TestFindingResolution:
    def test_resolved_requires_all_evidence_completed_and_mode_gone(self):
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1", "a2"])
        # Both ids completed on V2 (positive proof), and neither shows the mode there.
        resolution = compare.resolve_finding_group(v1_group, {}, {"a1", "a2"})
        assert resolution.status == "resolved"

    def test_an_id_absent_from_v2_completed_is_unavailable_not_resolved(self):
        # The exact gap a completion-agnostic implementation would miss: "a1" is neither
        # explicitly missing nor skipped in this call, it simply never completed -- and
        # that must never look identical to a case V2 actually ran and fixed.
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1"])
        resolution = compare.resolve_finding_group(v1_group, {}, set())
        assert resolution.status == "unavailable"
        assert resolution.unavailable_ids == ["a1"]

    def test_remaining_when_any_evidence_still_shows_mode(self):
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1", "a2"])
        v2_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1"])
        resolution = compare.resolve_finding_group(
            v1_group, {v2_group.key: v2_group}, {"a1", "a2"}
        )
        assert resolution.status == "remaining"
        assert resolution.remaining_ids == ["a1"]

    def test_unavailable_when_evidence_not_completed_on_v2(self):
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1", "a2"])
        # a2 completed; a1 did not (whatever the reason -- missing, skipped, or absent).
        resolution = compare.resolve_finding_group(v1_group, {}, {"a2"})
        assert resolution.status == "unavailable"
        assert resolution.unavailable_ids == ["a1"]

    def test_unavailable_takes_priority_even_if_some_evidence_resolved(self):
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1", "a2"])
        # a1 completed and no longer shows the mode; a2 did not complete on V2.
        resolution = compare.resolve_finding_group(v1_group, {}, {"a1"})
        assert resolution.status == "unavailable"

    def test_different_v2_failure_mode_is_resolved_plus_newly_appearing(self):
        v1_group = compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1"])
        v2_group = compare.FindingGroupRef("encoding", "homoglyph", "info_leak", ["a1"])
        resolutions, newly_appearing = compare.compare_findings(
            [v1_group], [v2_group], {"a1"}, {"unhandled_5xx": {"a1"}},
            v1_completed_attack_ids={"a1"}, v1_evaluable_attack_ids_by_mode={"info_leak": {"a1"}},
        )
        assert resolutions[0].status == "resolved"
        assert newly_appearing == [v2_group]

    def test_newly_appearing_finding_with_no_v1_counterpart(self):
        v2_group = compare.FindingGroupRef("boundary", "under_limit", "slow_response", ["a9"])
        resolutions, newly_appearing = compare.compare_findings(
            [], [v2_group], {"a9"}, {}, v1_completed_attack_ids={"a9"},
            v1_evaluable_attack_ids_by_mode={"slow_response": {"a9"}},
        )
        assert newly_appearing == [v2_group]
        assert resolutions == []

    def test_unmatched_and_uncompleted_handled_without_crashing(self):
        resolutions, newly_appearing = compare.compare_findings([], [], set(), {})
        assert resolutions == []
        assert newly_appearing == []


class TestCompareVersionsIntegration:
    """compare_versions derives V2 completion straight from run_meta, not from the caller."""

    def test_completed_derived_from_run_meta_case_ids(self):
        meta_v1 = make_run_meta(planned=2, completed=2)
        meta_v1["case_ids"]["completed"] = ["attack:a1", "attack:a2"]
        meta_v2 = make_run_meta(planned=2, completed=1, missing=["attack:a2"])
        meta_v2["case_ids"]["completed"] = ["attack:a1"]

        v1_groups = [compare.FindingGroupRef("encoding", "homoglyph", "unhandled_5xx", ["a1", "a2"])]
        result = compare.compare_versions(
            meta_v1=meta_v1, meta_v2=meta_v2, v1_groups=v1_groups, v2_groups=[],
            v2_evaluable_attack_ids_by_mode={"unhandled_5xx": {"a1", "a2"}},
        )
        # a2 never completed on V2 (it's in run_meta's own missing list) -> unavailable,
        # not silently resolved.
        assert result.resolutions[0].status == "unavailable"
        assert result.resolutions[0].unavailable_ids == ["a2"]

    def test_fingerprint_mismatch_still_computes_resolutions_but_flags_incomparable(self):
        # compare_versions is a mechanical toolkit; withholding whole-suite claims on a
        # mismatch is analyze.py's presentation decision (see build_comparison_summary),
        # not compare.py's. It still surfaces the mismatch so the caller can act on it.
        meta_v1 = make_run_meta(planned_fp="fp1")
        meta_v2 = make_run_meta(planned_fp="fp2")
        result = compare.compare_versions(meta_v1=meta_v1, meta_v2=meta_v2, v1_groups=[],
                                          v2_groups=[], v2_evaluable_attack_ids_by_mode={})
        assert result.fingerprints.whole_suite_comparable is False


# ==========================================================================================
# end-to-end determinism and output shape
# ==========================================================================================


class TestEndToEnd:
    def _synthetic_manifest_and_results(self):
        manifest = {
            "flip1": make_meta(attack_id="flip1", family="perturbation", subfamily="typo", requires_baseline=True),
            "crash1": make_meta(
                attack_id="crash1", family="encoding", subfamily="homoglyph",
                oracle="endpoint_should_stay_available", requires_baseline=False,
            ),
            "diag1": make_meta(
                attack_id="diag1", family="truncation", subfamily="mid_sentence",
                oracle="diagnostic_no_fixed_oracle", validity_tier="DIAGNOSTIC", requires_baseline=True,
            ),
        }
        results = [
            make_baseline(baseline_id="b1", label="joy", confidence=0.95, version="v1"),
            make_result(attack_id="flip1", baseline_id="b1", category="perturbation", label="sadness", confidence=0.7, version="v1"),
            make_result(
                attack_id="crash1", baseline_id=None, category="encoding", status_code=500,
                response_body="", label=None, confidence=None, endpoint_alive_after=False, version="v1",
            ),
            make_result(
                attack_id="diag1", baseline_id="b1", category="truncation", label="joy", confidence=0.4, version="v1",
            ),
        ]
        return manifest, results

    def test_findings_carry_all_required_contract_fields(self):
        manifest, results = self._synthetic_manifest_and_results()
        analysis = analyze.analyze_version(results, manifest)
        for finding in analysis.findings:
            for attr in ("finding_id", "title", "category", "severity_score", "severity_tier",
                         "description", "remediation", "evidence"):
                assert getattr(finding, attr) not in (None, "")

    def test_summary_json_has_required_sections(self):
        manifest, results = self._synthetic_manifest_and_results()
        analysis = analyze.analyze_version(results, manifest)
        run_meta = make_run_meta(planned=4, completed=4)
        summary = analyze.build_version_summary(analysis, run_meta)
        for key in ("version", "coverage", "category_stats", "findings",
                    "diagnostic_observations", "review_cases"):
            assert key in summary
        assert any(obs["attack_id"] == "diag1" for obs in summary["diagnostic_observations"])

    def test_running_analysis_twice_is_deterministic(self):
        manifest, results = self._synthetic_manifest_and_results()
        first = analyze.analyze_version(list(results), dict(manifest))
        second = analyze.analyze_version(list(results), dict(manifest))
        assert [dataclasses.asdict(f) for f in first.findings] == [dataclasses.asdict(f) for f in second.findings]
        assert first.category_stats == second.category_stats
        assert first.finding_meta == second.finding_meta

    def test_missing_manifest_entry_raises_loudly(self):
        results = [make_result(attack_id="ghost")]
        with pytest.raises(ValueError):
            analyze.analyze_version(results, {})


class TestBaselineCensusAndDenominator:
    """The brief's "36 of 42 eligible" requirement, plus the check to run the moment a
    real run lands: how many clean baselines cleared 0.6."""

    def _mixed_baselines(self):
        # 4 confident, 2 below threshold -- the same shape as the real run's 36/42.
        rows = [make_baseline(baseline_id=f"ok-{i}", confidence=0.9) for i in range(4)]
        rows.append(make_baseline(baseline_id="handwritten-neutral-4", confidence=0.4655))
        rows.append(make_baseline(baseline_id="dataset-surprise-0", confidence=0.4906))
        return rows

    def test_census_counts_eligible_and_excluded(self):
        census = drift.baseline_confidence_census(self._mixed_baselines())
        assert census.total == 6
        assert census.eligible == 4
        assert census.below_threshold == 2
        assert [bid for bid, _ in census.below_threshold_ids] == [
            "handwritten-neutral-4", "dataset-surprise-0",
        ]

    def test_census_reports_baseline_with_no_prediction_separately(self):
        rows = [make_baseline(baseline_id="dead", label=None, confidence=None)]
        census = drift.baseline_confidence_census(rows)
        assert census.no_prediction_ids == ["dead"]
        assert census.eligible == 0 and census.below_threshold == 0

    def test_threshold_is_inclusive_at_exactly_060(self):
        census = drift.baseline_confidence_census([make_baseline(confidence=0.6)])
        assert census.eligible == 1

    def test_summary_text_states_reduced_denominator(self):
        census = drift.baseline_confidence_census(self._mixed_baselines())
        assert census.summary_text == "4 of 6 baselines eligible for flip scoring"

    def test_flip_rate_never_appears_without_its_baseline_denominator(self):
        manifest = {"a1": make_meta()}
        results = self._mixed_baselines() + [
            make_result(attack_id="a1", baseline_id="ok-0", label="sadness", confidence=0.8)
        ]
        analysis = analyze.analyze_version(results, manifest)
        block = analyze.build_drift_block(analysis.drift)
        assert "flip_rate" in block
        denominator = block["baseline_denominator"]
        assert denominator["eligible"] == 4
        assert denominator["total"] == 6
        assert denominator["threshold"] == 0.6
        assert denominator["statement"] == "4 of 6 baselines eligible for flip scoring"
        assert denominator["excluded_below_threshold"] == 2

    def test_confidence_change_is_recorded_for_flips(self):
        manifest = {"a1": make_meta()}
        results = [
            make_baseline(baseline_id="b1", label="joy", confidence=0.9),
            make_result(attack_id="a1", baseline_id="b1", label="sadness", confidence=0.7),
        ]
        analysis = analyze.analyze_version(results, manifest)
        block = analyze.build_drift_block(analysis.drift)
        per_flip = block["confidence_change"]["per_flip"]
        assert len(per_flip) == 1
        assert per_flip[0]["attack_id"] == "a1"
        assert per_flip[0]["delta"] == pytest.approx(-0.2)
        assert block["confidence_change"]["mean_delta_on_flips"] == pytest.approx(-0.2)

    def test_no_flips_gives_no_mean_delta(self):
        assert drift.DriftSummary().mean_flip_confidence_delta is None


class TestRequiredOutputSections:
    def test_limitation_notes_are_always_emitted(self):
        analysis = analyze.analyze_version([], {})
        summary = analyze.build_version_summary(analysis, make_run_meta())
        notes = " ".join(summary["limitations"]).lower()
        # The three the brief names explicitly.
        assert "no model-accuracy claim" in notes
        assert "no retraining" in notes and "non-improvement" in notes
        assert "process died" in notes or "process-death" in notes

    def test_reproducibility_count_is_separate_from_severity(self):
        evaluations = []
        for i in range(5):
            r = make_result(attack_id=f"h{i}", status_code=500, response_body="",
                            label=None, confidence=None)
            m = make_meta(attack_id=f"h{i}", subfamily="homoglyph", requires_baseline=False)
            evaluations.append(analyze.evaluate_case(r, m, None))
        findings, meta, _ = analyze.build_findings(evaluations, "v1")
        fid = findings[0].finding_id
        assert meta[fid]["affected_cases"] == 5
        assert findings[0].severity_score == 70.0  # unchanged by reproducing 5 times

    def test_operational_tracks_error_handling_gaps(self):
        r = make_result(attack_id="m1", status_code=200, confidence=0.9)
        m = make_meta(attack_id="m1", family="malformed",
                      oracle="request_should_be_rejected_cleanly", requires_baseline=False)
        stats = analyze.compute_operational_stats([analyze.evaluate_case(r, m, None)])
        assert stats["invalid_input_accepted"] == 1

    def test_availability_wording_avoids_process_death_claim(self):
        r = make_result(attack_id="d1", endpoint_alive_after=False)
        m = make_meta(attack_id="d1", oracle="endpoint_should_stay_available",
                      requires_baseline=False)
        findings, _, _ = analyze.build_findings([analyze.evaluate_case(r, m, None)], "v1")
        text = (findings[0].title + " " + findings[0].description).lower()
        # Must describe it as *observed* unavailability, explicitly disclaim process
        # death, and never call it a crash.
        assert "observed" in text and "unavailab" in text
        assert "not evidence of process death" in text
        assert "crash" not in text
        assert "process died" not in text

    def test_comparison_reports_flip_counts_and_unmatched_evidence(self):
        v1 = analyze.analyze_version([], {})
        v2 = analyze.analyze_version([], {})
        meta_v1 = make_run_meta(planned=2, completed=2)
        meta_v1["case_ids"]["completed"] = ["attack:a1", "attack:a2"]
        meta_v2 = make_run_meta(planned=2, completed=1, missing=["attack:a2"])
        meta_v2["case_ids"]["completed"] = ["attack:a1"]
        comp = analyze.build_comparison_summary(v1, v2, meta_v1, meta_v2)
        assert "v1_qualifying_flips" in comp["drift"]
        assert "v1_baseline_denominator" in comp["drift"]
        assert comp["coverage"]["v1_only"] == ["attack:a2"]
        assert "attack:a2" in comp["coverage"]["unavailable"]
        assert "limitations" in comp

    def test_validity_tier_census_preserved(self):
        r = make_result(attack_id="g1", status_code=500, response_body="",
                        label=None, confidence=None)
        m = make_meta(attack_id="g1", validity_tier="GOLD", requires_baseline=False)
        analysis_obj = analyze.analyze_version(
            [r], {"g1": m}
        )
        summary = analyze.build_version_summary(analysis_obj, make_run_meta())
        assert summary["validity_tier_census"].get("GOLD") == 1


class TestResultFileLoading:
    """A corrupt or truncated results file must fail loudly and informatively, never be
    silently skipped -- dropping rows would desynchronise the results from run_meta's
    coverage lists. Regression test for a real truncated file seen in a live run."""

    def _write(self, tmp_path, text):
        path = tmp_path / "results_v1.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def _valid_row(self):
        return json.dumps(dataclasses.asdict(make_result()))

    def test_valid_file_loads(self, tmp_path):
        path = self._write(tmp_path, self._valid_row() + "\n")
        assert len(analyze.load_results(path)) == 1

    def test_blank_lines_are_tolerated(self, tmp_path):
        path = self._write(tmp_path, self._valid_row() + "\n\n\n")
        assert len(analyze.load_results(path)) == 1

    def test_trailing_fragment_raises_naming_file_and_line(self, tmp_path):
        # Exactly the shape seen live: complete rows followed by a stray fragment.
        path = self._write(tmp_path, self._valid_row() + "\ne}\n")
        with pytest.raises(ValueError) as excinfo:
            analyze.load_results(path)
        message = str(excinfo.value)
        assert "line 2" in message
        assert "e}" in message
        assert "truncated" in message

    def test_malformed_line_is_never_silently_skipped(self, tmp_path):
        path = self._write(tmp_path, self._valid_row() + "\nnot json\n" + self._valid_row() + "\n")
        with pytest.raises(ValueError):
            analyze.load_results(path)

    def test_row_not_matching_runresult_raises(self, tmp_path):
        path = self._write(tmp_path, json.dumps({"unexpected": 1}) + "\n")
        with pytest.raises(ValueError) as excinfo:
            analyze.load_results(path)
        assert "RunResult" in str(excinfo.value)


class TestComparisonWithholdsOnFingerprintMismatch:
    """The brief: 'If the fingerprints differ, do not make whole-suite equivalence claims
    at all.' A flag alongside the claims is not enough -- the claims themselves must be
    withheld, or a report template will render them anyway."""

    def test_mismatched_fingerprint_omits_resolution_and_rate_claims(self):
        v1_analysis = analyze.analyze_version([], {})
        v2_analysis = analyze.analyze_version([], {})
        meta_v1 = make_run_meta(planned_fp="fp1", manifest_sha="m1")
        meta_v2 = make_run_meta(planned_fp="fp2", manifest_sha="m1")

        summary = analyze.build_comparison_summary(v1_analysis, v2_analysis, meta_v1, meta_v2)

        assert summary["fingerprints"]["whole_suite_comparable"] is False
        assert "comparison_withheld_reason" in summary
        for forbidden_key in (
            "findings_resolved", "findings_remaining", "findings_unavailable",
            "findings_newly_appearing", "category_failure_rates", "drift", "operational",
        ):
            assert forbidden_key not in summary

    def test_matching_fingerprint_includes_full_comparison(self):
        v1_analysis = analyze.analyze_version([], {})
        v2_analysis = analyze.analyze_version([], {})
        meta_v1 = make_run_meta(planned_fp="fp1", manifest_sha="m1")
        meta_v2 = make_run_meta(planned_fp="fp1", manifest_sha="m1")

        summary = analyze.build_comparison_summary(v1_analysis, v2_analysis, meta_v1, meta_v2)

        assert summary["fingerprints"]["whole_suite_comparable"] is True
        assert "comparison_withheld_reason" not in summary
        assert "findings_resolved" in summary
        assert "category_failure_rates" in summary


class TestComparisonEvidenceEligibility:
    """Recorded completion is not proof that a weakness could be evaluated."""

    def _summary(self, v2_rows, *, mode="prediction_flip", v2_manifest=None):
        manifest = {"a1": make_meta()}
        v1_attack = make_result(label="sadness") if mode == "prediction_flip" else make_result(
            status_code=500, label=None, confidence=None, response_body=""
        )
        v1 = analyze.analyze_version([make_baseline(), v1_attack], manifest)
        v2 = analyze.analyze_version(v2_rows, v2_manifest or manifest)
        meta = make_run_meta(planned=2, completed=2)
        meta["case_ids"]["completed"] = ["baseline:b1", "attack:a1"]
        return analyze.build_comparison_summary(v1, v2, meta, meta)

    @pytest.mark.parametrize("changes", [
        dict(status_code=None, label=None, confidence=None, error="connection_error: test"),
        dict(status_code=None, label=None, confidence=None, error="transport_error: test"),
        dict(status_code=None, label=None, confidence=None, latency_band="timeout", error="timeout: test"),
        dict(status_code=200, label=None, confidence=None, response_body="{}"),
        dict(status_code=422, label=None, confidence=None, response_body='{"detail":[]}'),
    ])
    def test_unusable_v2_prediction_never_resolves_flip(self, changes):
        summary = self._summary([make_baseline(version="v2"), make_result(version="v2", **changes)])
        assert ["encoding", "homoglyph", "prediction_flip"] not in summary["findings_resolved"]
        assert summary["findings_unavailable"] == [{
            "key": ["encoding", "homoglyph", "prediction_flip"], "unavailable_ids": ["a1"]
        }]

    @pytest.mark.parametrize("baselines", [[], [make_baseline(version="v2", label=None, confidence=None)],
                                             [make_baseline(version="v2", confidence=0.4)]])
    def test_unusable_clean_reference_never_resolves_flip(self, baselines):
        summary = self._summary(baselines + [make_result(version="v2")])
        assert summary["findings_unavailable"][0]["unavailable_ids"] == ["a1"]

    @pytest.mark.parametrize("mode", ["prediction_flip", "unhandled_5xx"])
    def test_metadata_completion_without_result_is_unavailable(self, mode):
        summary = self._summary([make_baseline(version="v2")], mode=mode)
        assert summary["findings_unavailable"][0]["key"][2] == mode
        assert summary["findings_resolved"] == []

    @pytest.mark.parametrize("tier", ["REVIEW", "DIAGNOSTIC"])
    def test_unscored_v2_case_never_resolves_finding(self, tier):
        summary = self._summary(
            [make_baseline(version="v2"), make_result(version="v2")],
            mode="unhandled_5xx", v2_manifest={"a1": make_meta(validity_tier=tier)},
        )
        assert summary["findings_unavailable"][0]["unavailable_ids"] == ["a1"]

    def test_connection_failure_does_not_resolve_server_error(self):
        summary = self._summary([make_result(version="v2", status_code=None, label=None,
                                             confidence=None, error="connection_error: test")],
                                mode="unhandled_5xx")
        assert summary["findings_unavailable"][0]["key"][2] == "unhandled_5xx"

    @pytest.mark.parametrize("label,expected", [("joy", "findings_resolved"), ("sadness", "findings_remaining")])
    def test_usable_predictions_still_resolve_or_remain(self, label, expected):
        summary = self._summary([make_baseline(version="v2"), make_result(version="v2", label=label)])
        assert len(summary[expected]) == 1
        assert summary["findings_unavailable"] == []

    def test_clean_rejection_can_resolve_server_error_without_a_prediction(self):
        summary = self._summary([make_result(version="v2", status_code=422, label=None,
                                             confidence=None, response_body='{"detail":[]}')],
                                mode="unhandled_5xx")
        assert summary["findings_resolved"] == [["encoding", "homoglyph", "unhandled_5xx"]]

    def test_changed_observable_failure_mode_still_resolves_and_appears(self):
        summary = self._summary([make_result(version="v2", status_code=400, label=None,
                                             confidence=None, response_body="Traceback (most recent call last)")],
                                mode="unhandled_5xx")
        assert summary["findings_resolved"] == [["encoding", "homoglyph", "unhandled_5xx"]]
        assert summary["findings_newly_appearing"] == [["encoding", "homoglyph", "info_leak"]]


    def test_partly_unevaluable_group_is_not_resolved(self):
        manifest = {aid: make_meta(attack_id=aid) for aid in ("a1", "a2")}
        v1 = analyze.analyze_version([make_baseline()] + [
            make_result(attack_id=aid, label="sadness") for aid in manifest
        ], manifest)
        v2 = analyze.analyze_version([
            make_baseline(version="v2"), make_result(attack_id="a1", version="v2"),
            make_result(attack_id="a2", version="v2", status_code=None, label=None,
                        confidence=None, error="connection_error: test"),
        ], manifest)
        meta = make_run_meta(planned=3, completed=3)
        meta["case_ids"]["completed"] = ["baseline:b1", "attack:a1", "attack:a2"]
        summary = analyze.build_comparison_summary(v1, v2, meta, meta)
        assert summary["findings_resolved"] == []
        assert summary["findings_unavailable"] == [{
            "key": ["encoding", "homoglyph", "prediction_flip"], "unavailable_ids": ["a2"]
        }]

    def test_health_failure_remains_observable_after_connection_failure(self):
        manifest = {"a1": make_meta()}
        rows = [make_result(status_code=None, label=None, confidence=None,
                            error="connection_error: test", endpoint_alive_after=False)]
        v1 = analyze.analyze_version(rows, manifest)
        v2 = analyze.analyze_version([dataclasses.replace(rows[0], version="v2")], manifest)
        meta = make_run_meta(planned=1, completed=1)
        meta["case_ids"]["completed"] = ["attack:a1"]
        summary = analyze.build_comparison_summary(v1, v2, meta, meta)
        assert summary["findings_remaining"] == [{
            "key": ["encoding", "homoglyph", "connection_failure"], "remaining_ids": ["a1"]
        }, {
            "key": ["encoding", "homoglyph", "service_unavailable"], "remaining_ids": ["a1"]
        }]
        assert summary["findings_unavailable"] == []

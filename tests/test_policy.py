"""CI policy tests (Task 3 item 6). Owner: Khalid.

Covers the matrix the acceptance checks require: pass, all-rejecting candidate,
constant/wrong clean output, 5xx, leaks, timeouts, partial candidate failure,
missing/truncated evidence, bad identity, and invalid/empty policy.
"""

import pytest

from contract import (
    CHECK_ERROR,
    CHECK_FAIL,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_PASS,
    OUTCOME_POLICY_FAILURE,
    RunResult,
)

from analysis import policy as policy_mod

LABELS = ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")
BASELINES = ["b1", "b2", "b3"]


def scores(top="joy"):
    return {label: (0.7 if label == top else 0.05) for label in LABELS}


def baseline_row(baseline_id, label="joy", **overrides):
    fields = dict(
        case_type="baseline", attack_id=None, baseline_id=baseline_id, category=None,
        version="v2", status_code=200, response_body='{"label":"joy"}', error=None,
        label=label, confidence=0.7, all_scores=scores(label), latency_ms=10.0,
        latency_band="normal", endpoint_alive_after=True,
        target_id="emotion_v2", suite_id="core",
    )
    fields.update(overrides)
    return RunResult(**fields)


def attack_row(attack_id, **overrides):
    fields = dict(
        case_type="attack", attack_id=attack_id, baseline_id=None, category="malformed",
        version="v2", status_code=422, response_body='{"detail":[]}', error=None,
        label=None, confidence=None, all_scores=None, latency_ms=8.0,
        latency_band="normal", endpoint_alive_after=True,
        target_id="emotion_v2", suite_id="core",
    )
    fields.update(overrides)
    return RunResult(**fields)


def make_rows(**overrides):
    rows = [baseline_row(b) for b in BASELINES] + [attack_row("mal.broken_json")]
    return rows


def make_policy(**overrides):
    document = {
        "policy_id": "ci_core_v1",
        "policy_version": "1.0.0",
        "policy_sha256": "a" * 64,
        "status": "frozen",
        "case_set_id": "ci_core_v1",
        "suite_id": "core",
        "candidate_target_id": "emotion_v2",
        "reference_id": "approved_clean_reference_v1",
        "expected_labels": list(LABELS),
        "expected_identity": {"target_id": "emotion_v2", "model_revision": "d" * 40},
        "selection": {
            "selection_sha256": "b" * 64,
            "manifest_sha256": "c" * 64,
            "case_ids": [f"baseline:{b}" for b in BASELINES] + ["attack:mal.broken_json"],
        },
        "clean_reference": {b: "joy" for b in BASELINES},
        "baseline_truth": {b: "joy" for b in BASELINES},
        "must_reject_case_ids": ["attack:mal.broken_json"],
    }
    document.update(overrides)
    return document


def make_meta(**overrides):
    meta = {
        "target_id": "emotion_v2",
        "model": {"revision": "d" * 40},
        "fingerprints": {"selection_sha256": "b" * 64, "manifest_sha256": "c" * 64},
    }
    meta.update(overrides)
    return meta


def run(policy=None, rows=None, meta=None):
    return policy_mod.evaluate_policy(
        policy=make_policy() if policy is None else policy,
        analysis={"schema_version": 3},
        run_metas={"emotion_v2": make_meta() if meta is None else meta},
        results_by_target={"emotion_v2": make_rows() if rows is None else rows},
    )


def check(outcome, check_id):
    return next(c for c in outcome.checks if c.check_id == check_id)


class TestPass:
    def test_clean_candidate_passes(self):
        outcome = run()
        assert outcome.outcome == OUTCOME_PASS
        assert outcome.exit_code == 0

    def test_a_pass_still_records_what_it_checked(self):
        outcome = run()
        assert outcome.checks
        assert all(c.reason for c in outcome.checks)

    def test_pass_claim_is_bounded(self):
        assert "not production certification" in run().summary["claim"]

    def test_ground_truth_accuracy_is_informational_only(self):
        outcome = run()
        assert check(outcome, policy_mod.CHECK_BASELINE_ACCURACY).blocking is False

    def test_flip_and_slow_counts_never_block(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", latency_band="slow", latency_ms=3000.0)
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_PASS
        assert check(outcome, policy_mod.CHECK_SLOW).blocking is False


class TestCandidateDefects:
    def test_server_error_is_a_policy_failure(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", status_code=500, label=None, confidence=None,
                               all_scores=None, response_body="")
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert outcome.exit_code == 1
        assert check(outcome, policy_mod.CHECK_NO_SERVER_ERRORS).status == CHECK_FAIL

    def test_timeout_is_a_policy_failure(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", status_code=None, latency_band="timeout",
                               label=None, confidence=None, all_scores=None,
                               response_body="", error="timeout: no response")
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert check(outcome, policy_mod.CHECK_NO_TIMEOUTS).status == CHECK_FAIL

    def test_transport_failure_is_a_policy_failure(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", status_code=None, label=None, confidence=None,
                               all_scores=None, response_body="",
                               error="connection_error: boom")
        assert run(rows=rows).outcome == OUTCOME_POLICY_FAILURE

    def test_leak_signature_is_a_policy_failure(self):
        rows = make_rows()
        rows[0] = baseline_row(
            "b1", response_body='Traceback (most recent call last):\n  File "/home/x/app.py"')
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert check(outcome, policy_mod.CHECK_NO_LEAKS).status == CHECK_FAIL

    def test_health_failure_is_a_policy_failure_without_claiming_process_death(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", endpoint_alive_after=False)
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert "not proof of process death" in check(outcome, policy_mod.CHECK_HEALTH).reason

    def test_all_rejecting_candidate_cannot_pass(self):
        # An endpoint that rejects everything fails the clean-response requirement.
        rows = [baseline_row(b, status_code=422, label=None, confidence=None,
                             all_scores=None, response_body='{"detail":[]}')
                for b in BASELINES] + [attack_row("mal.broken_json")]
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert check(outcome, policy_mod.CHECK_CLEAN_RESPONSES).status == CHECK_FAIL

    def test_constant_output_disagrees_with_the_reference(self):
        rows = [baseline_row(b, label="anger", all_scores=scores("anger"))
                for b in BASELINES] + [attack_row("mal.broken_json")]
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert check(outcome, policy_mod.CHECK_CLEAN_AGREEMENT).status == CHECK_FAIL

    def test_wrong_clean_label_on_one_baseline_fails(self):
        rows = make_rows()
        rows[1] = baseline_row("b2", label="sadness", all_scores=scores("sadness"))
        assert run(rows=rows).outcome == OUTCOME_POLICY_FAILURE

    def test_partial_candidate_failure_still_fails(self):
        rows = make_rows()
        rows[2] = baseline_row("b3", status_code=500, label=None, confidence=None,
                               all_scores=None, response_body="")
        assert run(rows=rows).outcome == OUTCOME_POLICY_FAILURE

    def test_missing_response_is_never_counted_as_a_rejection(self):
        rows = [baseline_row(b) for b in BASELINES] + [
            attack_row("mal.broken_json", status_code=None, response_body="",
                       latency_band="timeout", error="timeout: no response")]
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_POLICY_FAILURE
        assert check(outcome, policy_mod.CHECK_REJECTIONS).status == CHECK_FAIL

    def test_label_outside_declared_space_is_incoherent(self):
        rows = make_rows()
        rows[0] = baseline_row("b1", label="POSITIVE", all_scores={"POSITIVE": 0.9})
        assert run(rows=rows).outcome == OUTCOME_POLICY_FAILURE


class TestExecutionErrors:
    def test_draft_policy_cannot_pass(self):
        outcome = run(policy=make_policy(status="draft"))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert outcome.exit_code == 2
        assert "draft" in check(outcome, policy_mod.CHECK_POLICY_VALID).reason

    def test_unresolved_selection_hashes_cannot_pass(self):
        outcome = run(policy=make_policy(
            selection={"case_ids": ["baseline:b1"], "selection_sha256": "", "manifest_sha256": ""}))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert "unresolved" in check(outcome, policy_mod.CHECK_POLICY_VALID).reason

    def test_empty_selection_cannot_pass(self):
        outcome = run(policy=make_policy(
            selection={"case_ids": [], "selection_sha256": "b" * 64, "manifest_sha256": "c" * 64}))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR

    def test_invalid_policy_object_is_an_execution_error(self):
        outcome = run(policy={"policy_id": "x"})
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR

    def test_missing_evidence_is_an_execution_error_not_a_pass(self):
        outcome = policy_mod.evaluate_policy(
            policy=make_policy(), analysis={}, run_metas={}, results_by_target={})
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert check(outcome, policy_mod.CHECK_CANDIDATE_IDENTITY).status == CHECK_ERROR

    def test_truncated_evidence_is_an_execution_error(self):
        rows = [baseline_row("b1")]  # selection expects four cases
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert check(outcome, policy_mod.CHECK_COMPLETION).status == CHECK_ERROR

    def test_duplicate_recorded_case_is_an_execution_error(self):
        rows = make_rows() + [baseline_row("b1")]
        outcome = run(rows=rows)
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR

    def test_wrong_model_revision_is_an_execution_error(self):
        outcome = run(meta=make_meta(model={"revision": "e" * 40}))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert "model revision" in check(outcome, policy_mod.CHECK_CANDIDATE_IDENTITY).reason

    def test_wrong_selection_hash_is_an_execution_error(self):
        outcome = run(meta=make_meta(
            fingerprints={"selection_sha256": "f" * 64, "manifest_sha256": "c" * 64}))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR

    def test_reference_covering_nothing_is_an_execution_error(self):
        outcome = run(policy=make_policy(clean_reference={}))
        assert outcome.outcome == OUTCOME_EXECUTION_ERROR
        assert check(outcome, policy_mod.CHECK_CLEAN_AGREEMENT).status == CHECK_ERROR

    def test_structural_error_takes_precedence_over_a_candidate_defect(self):
        # A 5xx is present, but the evidence is also incomplete: the untrustworthy
        # evidence wins, because a gate that cannot say what it checked has not judged.
        rows = [baseline_row("b1", status_code=500, label=None, confidence=None,
                             all_scores=None, response_body="")]
        assert run(rows=rows).outcome == OUTCOME_EXECUTION_ERROR


class TestPurity:
    def test_policy_module_performs_no_io(self):
        import inspect
        source = inspect.getsource(policy_mod)
        for forbidden in ("open(", "requests.", "httpx.", "subprocess", "urllib",
                          "Path(", "socket"):
            assert forbidden not in source, f"policy must be pure; found {forbidden}"

    def test_policy_imports_no_model_or_endpoint(self):
        import inspect
        source = inspect.getsource(policy_mod)
        for forbidden in ("transformers", "torch", "endpoint.model", "attacks"):
            assert forbidden not in source

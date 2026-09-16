"""Identity and label-space safety for analysis (Task 3, item 1). Owner: Khalid.

The rule under test is CONTRACTS.md section 1: a new run records its identity explicitly,
and nothing infers a model from ``version``, defaults an unknown identity to emotion, or
falls back to emotion after a malformed new run. Blank identity is supported only for
recognised historical artifacts.
"""

import pytest

from contract import RunResult

from analysis import drift
from analysis.validation import (
    EMOTION_LABELS,
    PROVENANCE_DECLARED,
    PROVENANCE_INFERRED_LEGACY,
    resolve_identity,
    validate_rows,
)

SENTIMENT_LABELS = ("NEGATIVE", "POSITIVE")


def sentiment_row(**overrides) -> RunResult:
    fields = dict(
        case_type="attack", attack_id="a1", baseline_id="b1", category="encoding",
        version="v1", status_code=200, response_body="{}", error=None,
        label="POSITIVE", confidence=0.9,
        all_scores={"NEGATIVE": 0.1, "POSITIVE": 0.9},
        latency_ms=10.0, latency_band="normal", endpoint_alive_after=True,
        target_id="sentiment_v1", suite_id="core",
    )
    fields.update(overrides)
    return RunResult(**fields)


def sentiment_baseline(**overrides) -> RunResult:
    fields = dict(
        case_type="baseline", attack_id=None, baseline_id="b1", category=None,
        label="NEGATIVE", confidence=0.95,
        all_scores={"NEGATIVE": 0.95, "POSITIVE": 0.05},
    )
    fields.update(overrides)
    return sentiment_row(**fields)


def legacy_row(**overrides) -> RunResult:
    fields = dict(
        case_type="baseline", attack_id=None, baseline_id="b1", category=None,
        version="v1", status_code=200, response_body="{}", error=None,
        label="joy", confidence=0.9, all_scores=None,
        latency_ms=5.0, latency_band="normal", endpoint_alive_after=True,
    )
    fields.update(overrides)
    return RunResult(**fields)


def invariant_manifest(attack_id="a1") -> dict:
    return {attack_id: dict(
        attack_id=attack_id, family="encoding", subfamily="homoglyph", relation="invariant",
        oracle="label_should_match_baseline", source="test", validity_tier="SILVER",
        requires_baseline=True,
    )}


class TestDeclaredLabelSpace:
    def test_uppercase_sentiment_labels_pass_validation(self):
        rows = [sentiment_baseline(), sentiment_row()]
        assert validate_rows(rows, labels=SENTIMENT_LABELS) == "v1"

    def test_uppercase_sentiment_labels_pass_through_drift(self):
        # drift is the second entry point into validate_rows; fixing only the top-level
        # caller would still reject a legitimate sentiment prediction here.
        rows = [sentiment_baseline(), sentiment_row()]
        summary = drift.compute_drift(rows, invariant_manifest(), labels=SENTIMENT_LABELS)
        assert summary.eligible == 1
        assert summary.qualifying_flips == 1

    def test_declared_identity_without_labels_refuses_to_guess(self):
        rows = [sentiment_baseline(), sentiment_row()]
        with pytest.raises(ValueError, match="no label space"):
            validate_rows(rows)

    def test_declared_identity_never_falls_back_to_emotion_in_drift(self):
        rows = [sentiment_baseline(), sentiment_row()]
        with pytest.raises(ValueError, match="no label space"):
            drift.compute_drift(rows, invariant_manifest())

    def test_sentiment_labels_rejected_against_emotion_space(self):
        rows = [sentiment_baseline()]
        with pytest.raises(ValueError, match="outside the declared label space"):
            validate_rows(rows, labels=EMOTION_LABELS)

    def test_identity_records_declared_provenance(self):
        identity = resolve_identity([sentiment_baseline()], labels=SENTIMENT_LABELS)
        assert identity.target_id == "sentiment_v1"
        assert identity.provenance == PROVENANCE_DECLARED
        assert identity.is_legacy is False


class TestOneIdentityPerFile:
    def test_mixed_target_ids_rejected(self):
        rows = [sentiment_baseline(), sentiment_row(target_id="emotion_v2")]
        with pytest.raises(ValueError, match="exactly one"):
            validate_rows(rows, labels=SENTIMENT_LABELS)

    def test_mixed_suite_ids_rejected(self):
        rows = [sentiment_baseline(), sentiment_row(suite_id="oces")]
        with pytest.raises(ValueError, match="exactly one"):
            validate_rows(rows, labels=SENTIMENT_LABELS)

    def test_declared_target_disagreeing_with_rows_rejected(self):
        with pytest.raises(ValueError, match="disagrees with rows"):
            resolve_identity([sentiment_baseline()], labels=SENTIMENT_LABELS,
                             target_id="emotion_v1")

    def test_unknown_suite_id_rejected(self):
        with pytest.raises(ValueError, match="unknown suite_id"):
            resolve_identity([sentiment_baseline(suite_id="not_a_suite")],
                             labels=SENTIMENT_LABELS)

    def test_duplicate_case_keys_still_rejected(self):
        rows = [sentiment_row(), sentiment_row()]
        with pytest.raises(ValueError, match="duplicate result case key"):
            validate_rows(rows, labels=SENTIMENT_LABELS)


class TestLegacyRouting:
    def test_legacy_rows_resolve_as_inferred_emotion(self):
        identity = resolve_identity([legacy_row()])
        assert identity.target_id == "emotion_v1"
        assert identity.labels == EMOTION_LABELS
        assert identity.provenance == PROVENANCE_INFERRED_LEGACY
        assert identity.is_legacy is True

    def test_legacy_v2_maps_to_emotion_v2(self):
        identity = resolve_identity([legacy_row(version="v2")])
        assert identity.target_id == "emotion_v2"

    def test_legacy_inference_is_marked_not_declared(self):
        # The v1 -> emotion_v1 mapping is a recorded inference, never a declaration.
        assert resolve_identity([legacy_row()]).provenance != PROVENANCE_DECLARED

    def test_empty_run_keeps_its_expected_version_without_crashing(self):
        assert validate_rows([], "v1") == "v1"


class TestScoreVector:
    def test_unknown_label_in_scores_rejected(self):
        row = sentiment_baseline(all_scores={"NEGATIVE": 0.5, "joy": 0.5})
        with pytest.raises(ValueError, match="outside the declared space"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_non_finite_score_rejected(self):
        row = sentiment_baseline(all_scores={"NEGATIVE": float("nan"), "POSITIVE": 0.5})
        with pytest.raises(ValueError, match="finite number"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_score_outside_unit_interval_rejected(self):
        row = sentiment_baseline(all_scores={"NEGATIVE": 1.5, "POSITIVE": 0.5})
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_incomplete_vector_rejected_for_declared_data(self):
        row = sentiment_baseline(all_scores={"POSITIVE": 0.05})
        with pytest.raises(ValueError, match="complete score vector"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_prediction_without_scores_rejected_for_declared_data(self):
        row = sentiment_baseline(all_scores=None)
        with pytest.raises(ValueError, match="without all_scores"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_legacy_rows_are_not_required_to_carry_a_complete_vector(self):
        # Historical rows predate the rule; demanding a full vector would reject evidence
        # that is not actually corrupt.
        assert validate_rows([legacy_row(all_scores=None)], "v1") == "v1"

    def test_absent_prediction_may_omit_scores(self):
        row = sentiment_baseline(label=None, confidence=None, all_scores=None,
                                 status_code=500, response_body="")
        assert validate_rows([row], labels=SENTIMENT_LABELS) == "v1"


class TestRequestBodyEvidence:
    def test_valid_request_body_evidence_accepted(self):
        row = sentiment_baseline(request_body_bytes=31, request_body_sha256="a" * 64)
        assert validate_rows([row], labels=SENTIMENT_LABELS) == "v1"

    def test_negative_body_length_rejected(self):
        row = sentiment_baseline(request_body_bytes=-1)
        with pytest.raises(ValueError, match="request_body_bytes"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_malformed_body_digest_rejected(self):
        row = sentiment_baseline(request_body_sha256="not-a-sha")
        with pytest.raises(ValueError, match="request_body_sha256"):
            validate_rows([row], labels=SENTIMENT_LABELS)

    def test_historical_null_body_evidence_is_legitimate(self):
        # None means unavailable and never zero; historical rows are always None.
        assert validate_rows([legacy_row()], "v1") == "v1"


class TestSchemaV3Envelope:
    """The v3 document shape (CONTRACTS section 6.1)."""

    def _doc(self):
        from analysis import analyze
        return analyze.run_analysis_from_dir("artifacts/benchmark_v6/run")

    def test_envelope_keys(self):
        doc = self._doc()
        assert doc["schema_version"] == 3
        assert doc["contracts_version"] == "3.0.0"
        for key in ("run_identity", "evaluations", "limitations"):
            assert key in doc

    def test_summaries_are_keyed_by_target_id_not_version(self):
        block = self._doc()["evaluations"][0]
        assert sorted(block["summaries"]) == ["emotion_v1", "emotion_v2"]
        assert block["targets"] == ["emotion_v1", "emotion_v2"]

    def test_canonical_evaluation_id(self):
        # "emotion.core", never "emotion_7.core".
        assert self._doc()["evaluations"][0]["evaluation_id"] == "emotion.core"

    def test_legacy_provenance_is_marked_inferred_not_declared(self):
        block = self._doc()["evaluations"][0]
        identity = block["summaries"]["emotion_v1"]["identity"]
        assert identity["provenance"] == PROVENANCE_INFERRED_LEGACY
        assert identity["declared"]["target_id"] is None
        assert "inferred" in identity

    def test_paired_block_carries_a_comparison(self):
        assert self._doc()["evaluations"][0]["comparison"] is not None

    def test_legacy_v2_view_preserves_the_published_numbers(self):
        import json
        from analysis import analyze
        view = analyze.legacy_v2_view(self._doc())
        published = json.loads(
            open("artifacts/benchmark_v6/analysis/analysis.json", encoding="utf-8").read()
        )
        assert view["schema_version"] == 2
        for version in ("summary_v1", "summary_v2"):
            assert view[version]["drift"]["qualifying_flips"] == \
                published[version]["drift"]["qualifying_flips"]
            assert view[version]["operational"]["unhandled_5xx"] == \
                published[version]["operational"]["unhandled_5xx"]
            assert len(view[version]["findings"]) == len(published[version]["findings"])


class TestSingleTargetComparisonIsNull:
    """Acceptance check 4: single-target output has comparison null and no fabricated
    comparison metrics."""

    def test_single_block_comparison_is_null_and_present(self):
        from analysis import analyze
        block = analyze.build_evaluation_block(
            evaluation_id="sentiment.core", kind="single", task_id="sentiment_2",
            suite_id="core", targets=["sentiment_v1"],
            summaries={"sentiment_v1": {"target_id": "sentiment_v1"}}, comparison=None,
        )
        assert "comparison" in block
        assert block["comparison"] is None

    def test_single_block_refuses_a_fabricated_comparison(self):
        from analysis import analyze
        with pytest.raises(ValueError, match="cannot carry a comparison"):
            analyze.build_evaluation_block(
                evaluation_id="sentiment.core", kind="single", task_id="sentiment_2",
                suite_id="core", targets=["sentiment_v1"],
                summaries={"sentiment_v1": {}},
                comparison={"improvement": 0.5},
            )

    def test_paired_block_requires_two_targets(self):
        from analysis import analyze
        with pytest.raises(ValueError, match="exactly two targets"):
            analyze.build_evaluation_block(
                evaluation_id="emotion.core", kind="paired", task_id="emotion_7",
                suite_id="core", targets=["emotion_v1"],
                summaries={"emotion_v1": {}}, comparison={},
            )

    def test_summaries_must_match_the_target_list(self):
        from analysis import analyze
        with pytest.raises(ValueError, match="summaries keys must match"):
            analyze.build_evaluation_block(
                evaluation_id="sentiment.core", kind="single", task_id="sentiment_2",
                suite_id="core", targets=["sentiment_v1"],
                summaries={"emotion_v1": {}}, comparison=None,
            )

    def test_single_target_document_has_no_v2_projection(self):
        from analysis import analyze
        doc = {"evaluations": [analyze.build_evaluation_block(
            evaluation_id="sentiment.core", kind="single", task_id="sentiment_2",
            suite_id="core", targets=["sentiment_v1"],
            summaries={"sentiment_v1": {}}, comparison=None)]}
        with pytest.raises(ValueError, match="no v2 representation"):
            analyze.legacy_v2_view(doc)

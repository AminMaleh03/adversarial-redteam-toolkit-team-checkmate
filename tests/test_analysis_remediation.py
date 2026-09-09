"""Regression and file-boundary integration tests for the independent PR #6 review."""

import dataclasses
import hashlib
import json
import subprocess
import sys

import pytest

from analysis import analyze, compare, drift, severity
from analysis.validation import case_key
from contract import RunResult


def row(version="v1", aid="a1", **changes):
    values = dict(case_type="attack", attack_id=aid, baseline_id="b1", category="encoding",
                  version=version, status_code=200, response_body='{"label":"joy"}', error=None,
                  label="joy", confidence=.9, all_scores={}, latency_ms=100.,
                  latency_band="normal", endpoint_alive_after=True)
    values.update(changes)
    return RunResult(**values)


def clean(version="v1", **changes):
    return row(version, case_type="baseline", attack_id=None, category=None, **changes)


def manifest():
    return {aid: dict(attack_id=aid, family="encoding", subfamily="homoglyph",
                     oracle=drift.ORACLE_LABEL_MATCH_BASELINE, validity_tier="SILVER",
                     relation="invariant", source="regression", requires_baseline=True)
            for aid in ("a1", "a2")}


def metadata(rows, version, digest="a" * 64):
    planned = ["baseline:b1", "attack:a1", "attack:a2"]
    completed = [case_key(r) for r in rows]
    ids = dict(planned=planned, selected=planned, completed=completed,
               missing=[k for k in planned if k not in completed], skipped=[], limit_excluded=[])
    return dict(version=version, fingerprints=dict(planned_suite_sha256="b" * 64,
                                                   manifest_sha256=digest), case_ids=ids,
                coverage={**{k: len(v) for k, v in ids.items()},
                          "coverage_rate": round(len(completed) / len(planned), 6)})


def summary(v1_rows, v2_rows):
    return analyze.build_comparison_summary(
        analyze.analyze_version(v1_rows, manifest()), analyze.analyze_version(v2_rows, manifest()),
        metadata(v1_rows, "v1"), metadata(v2_rows, "v2"))


@pytest.fixture
def artifacts(tmp_path):
    entries = manifest()
    paths = {"manifest_path": tmp_path / "manifest.json"}
    paths["manifest_path"].write_text(json.dumps(entries), encoding="utf8")
    digest = hashlib.sha256(paths["manifest_path"].read_bytes()).hexdigest()
    for version in ("v1", "v2"):
        rows = [clean(version), row(version), row(version, "a2")]
        paths[f"results_{version}_path"] = tmp_path / f"results_{version}.jsonl"
        paths[f"results_{version}_path"].write_text(
            "".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in rows), encoding="utf8")
        paths[f"meta_{version}_path"] = tmp_path / f"run_meta_{version}.json"
        paths[f"meta_{version}_path"].write_text(json.dumps(metadata(rows, version, digest)), encoding="utf8")
    return paths


def update_json(path, change):
    data = json.loads(path.read_text(encoding="utf8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf8")


def test_persistent_group_moves_to_different_case():
    result = summary([clean(), row(label="sadness"), row(aid="a2")],
                     [clean("v2"), row("v2"), row("v2", "a2", label="sadness")])
    assert result["findings_resolved"] == []
    assert result["findings_remaining"][0]["remaining_ids"] == ["a2"]
    assert result["finding_comparisons"][0]["improved_ids"] == ["a1"]
    assert result["findings_newly_appearing"] == []


def test_positive_persistence_survives_missing_other_evidence():
    result = summary([clean(), row(label="sadness"), row(aid="a2", label="sadness")],
                     [clean("v2"), row("v2", "a2", label="sadness")])
    detail = result["finding_comparisons"][0]
    assert detail["status"] == "remaining"
    assert detail["remaining_ids"] == ["a2"]
    assert detail["unavailable_ids"] == ["a1"]


@pytest.mark.parametrize("v1_rows", [[], [row()], [clean(confidence=.4), row()],
    [clean(), row(status_code=422, label=None, confidence=None)],
    [clean(), row(status_code=None, label=None, confidence=None, error="reset")]])
def test_unusable_v1_never_establishes_new_flip(v1_rows):
    result = summary(v1_rows, [clean("v2"), row("v2", label="sadness")])
    assert result["findings_newly_appearing"] == []
    assert result["inconclusive_new_findings"] == [
        {"key": ["encoding", "homoglyph", "prediction_flip"], "unavailable_ids": ["a1"]}]


def test_new_group_has_only_proven_regression_ids():
    result = summary([clean(), row()], [clean("v2"), row("v2", label="sadness"),
                                       row("v2", "a2", label="sadness")])
    assert result["new_finding_evidence"][0]["regression_ids"] == ["a1"]
    assert result["inconclusive_new_findings"][0]["unavailable_ids"] == ["a2"]


def test_completion_without_v1_evaluability_cannot_prove_regression():
    group = compare.FindingGroupRef("encoding", "homoglyph", "prediction_flip", ["a1"])
    result = compare.compare_versions(meta_v1=metadata([row()], "v1"),
        meta_v2=metadata([row("v2")], "v2"), v1_groups=[], v2_groups=[group],
        v2_evaluable_attack_ids_by_mode={"prediction_flip": {"a1"}})
    assert result.newly_appearing == []
    assert result.inconclusive_new == [group]


def test_timeout_does_not_resolve_unobserved_http_failure():
    result = summary([row(status_code=500, label=None, confidence=None)],
                     [row("v2", status_code=None, label=None, confidence=None,
                          latency_band="timeout", latency_ms=10000.)])
    assert result["findings_resolved"] == []
    assert result["findings_unavailable"][0]["key"][2] == "unhandled_5xx"


def test_connection_failure_finding_and_drift_unevaluability_are_separate():
    result = analyze.analyze_version([clean(), row(status_code=None, label=None,
                                      confidence=None, error="connection reset")], manifest())
    finding, = result.findings
    assert (finding.severity_score, finding.severity_tier) == (70., "High")
    assert finding.remediation and finding.evidence == ["a1"]
    assert result.operational["connection_failures"] == 1
    assert result.operational["service_unavailable"] == 0
    assert result.category_stats["encoding"]["failed"] == 1
    assert result.drift.eligible == 0


@pytest.mark.parametrize("tier", ["GOLD", "SILVER", "REVIEW", "DIAGNOSTIC"])
def test_diagnostic_oracle_always_excluded_by_case_evaluator(tier):
    entry = {**manifest()["a1"], "oracle": drift.ORACLE_DIAGNOSTIC, "validity_tier": tier}
    result = analyze.evaluate_case(row(status_code=500, endpoint_alive_after=False), entry, None)
    assert result.bucket == "diagnostic" and result.instances == []


@pytest.mark.parametrize("field,value", [("oracle", "typo"), ("validity_tier", "typo"),
    ("family", "unknown"), ("attack_id", "wrong"), ("subfamily", ""),
    ("source", None), ("requires_baseline", "true"), ("relation", "unknown")])
def test_invalid_manifest_fails_before_scoring(artifacts, field, value):
    update_json(artifacts["manifest_path"], lambda m: m["a1"].update({field: value}))
    with pytest.raises(ValueError, match="manifest"):
        analyze.run_analysis(**artifacts)


def test_valid_but_altered_manifest_hash_is_rejected(artifacts):
    update_json(artifacts["manifest_path"], lambda m: m["a1"].update(validity_tier="GOLD"))
    with pytest.raises(ValueError, match="actual manifest SHA-256"):
        analyze.run_analysis(**artifacts)


@pytest.mark.parametrize("tier", ["GOLD", "SILVER", "REVIEW"])
def test_registered_diagnostic_oracle_tier_difference_is_preserved_and_excluded(tier):
    entries = manifest()
    entries["a1"].update(oracle=drift.ORACLE_DIAGNOSTIC, validity_tier=tier)
    result = analyze.analyze_version([row(status_code=500)], entries)
    assert result.findings == []
    assert result.diagnostic_observations[0]["validity_tier"] == tier
    assert result.diagnostic_observations[0]["tier_differs_from_diagnostic"] is True


def test_v2_metadata_hash_is_also_verified(artifacts):
    update_json(artifacts["meta_v2_path"], lambda m: m["fingerprints"].update(manifest_sha256="c" * 64))
    with pytest.raises(ValueError, match="v2: actual manifest"):
        analyze.run_analysis(**artifacts)


@pytest.mark.parametrize("rows", [[clean(), clean("v2"), row()], [clean(), clean(), row()],
                                  [clean(), row(), row()]])
def test_ambiguous_identity_rejected_by_drift_and_orchestrator(rows):
    for function in (drift.compute_drift, analyze.analyze_version):
        with pytest.raises(ValueError, match="version|duplicate"):
            function(rows, manifest())


def test_direct_pair_rejects_cross_version_reference():
    with pytest.raises(ValueError, match="mismatched"):
        drift.evaluate_pair("a1", "b1", "v1", clean("v2"), row(), manifest()["a1"])


@pytest.mark.parametrize("change", [lambda m: m.update(version="v1"),
    lambda m: m["coverage"].update(completed=99),
    lambda m: m["coverage"].update(coverage_rate=.5),
    lambda m: m["case_ids"]["completed"].reverse(),
    lambda m: m["case_ids"]["completed"].pop(),
    lambda m: m["case_ids"]["planned"].append("attack:a1")])
def test_invalid_metadata_rejected(artifacts, change):
    update_json(artifacts["meta_v2_path"], change)
    with pytest.raises(ValueError):
        analyze.run_analysis(**artifacts)


def test_swapped_result_files_rejected(artifacts):
    artifacts["results_v1_path"], artifacts["results_v2_path"] = artifacts["results_v2_path"], artifacts["results_v1_path"]
    with pytest.raises(ValueError, match="version"):
        analyze.run_analysis(**artifacts)


def test_missing_actual_row_does_not_inherit_metadata_completion(artifacts):
    path = artifacts["results_v2_path"]
    path.write_text(path.read_text(encoding="utf8").splitlines()[0] + "\n", encoding="utf8")
    with pytest.raises(ValueError, match="actual result rows"):
        analyze.run_analysis(**artifacts)


def test_legitimate_partial_run_keeps_inconclusive_evidence(artifacts):
    v1 = [clean(), row(label="sadness"), row(aid="a2")]
    v2 = [clean("v2")]
    for version, rows in (("v1", v1), ("v2", v2)):
        artifacts[f"results_{version}_path"].write_text(
            "".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in rows), encoding="utf8")
        digest = hashlib.sha256(artifacts["manifest_path"].read_bytes()).hexdigest()
        artifacts[f"meta_{version}_path"].write_text(json.dumps(metadata(rows, version, digest)), encoding="utf8")
    result = analyze.run_analysis(**artifacts)
    assert result["comparison"]["findings_resolved"] == []
    assert result["comparison"]["findings_unavailable"][0]["unavailable_ids"] == ["a1"]


@pytest.mark.parametrize("key", ["manifest_path", "meta_v1_path", "results_v1_path"])
def test_duplicate_json_keys_rejected(artifacts, key):
    artifacts[key].write_text('{"duplicate":1,"duplicate":2}\n', encoding="utf8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        analyze.run_analysis(**artifacts)


@pytest.mark.parametrize("changes", [dict(confidence=float("nan")), dict(confidence=1.1),
    dict(latency_ms=float("inf")), dict(status_code="500"), dict(endpoint_alive_after="false")])
def test_invalid_result_values_rejected(changes):
    with pytest.raises(ValueError):
        analyze.analyze_version([row(**changes)], manifest())


@pytest.mark.parametrize("value", ["/home/alice/data.txt", "C:\\Users\\alice\\data.txt",
    "Traceback (most recent call last)", {"file": "/etc/passwd"}, ["uvicorn.server"]])
def test_reflected_validation_input_is_not_a_leak(value):
    body = json.dumps({"detail": [{"type": "extra_forbidden", "loc": ["body", "/home/user/field"],
        "msg": "Extra inputs are not permitted", "input": value}]})
    evaluation = analyze.evaluate_case(row(status_code=422, response_body=body,
        label=None, confidence=None), manifest()["a1"], None)
    assert evaluation.instances == []


@pytest.mark.parametrize("body", [
    {"input": "/home/server/secrets"},
    {"detail": [{"type": "error", "loc": ["body"], "msg": "/home/server/secrets", "input": "safe"}]},
    {"detail": [{"type": "error", "loc": ["body"], "msg": "bad", "input": "safe"}], "debug": "Traceback (most recent call last)"},
])
def test_real_server_diagnostics_remain_detectable(body):
    assert analyze.detect_leak(json.dumps(body), 422) == "stack_or_path"


@pytest.mark.parametrize("confidence", [.999999999, .9999999999, .99999999])
def test_instance_and_group_tiers_preserve_sub_boundary_scores(confidence):
    score, tier = severity.compute_severity("prediction_flip", clean_confidence=confidence)
    assert score < 60 and tier == "Medium"
    assert severity.score_group([score]) == (score, "Medium")
    result = analyze.analyze_version([clean(confidence=confidence), row(label="sadness")], manifest())
    assert result.findings[0].severity_score < 60
    assert result.findings[0].severity_tier == "Medium"


def test_comparison_rates_include_counts_and_na():
    result = summary([clean(), row(label="sadness")], [clean("v2"), row("v2")])
    assert result["category_failure_rates"]["encoding"] == {
        "v1": {"failed": 1, "eligible": 1, "rate": 1.0},
        "v2": {"failed": 0, "eligible": 1, "rate": 0.0}}
    assert result["category_failure_rates"]["boundary"]["v1"] == {
        "failed": 0, "eligible": 0, "rate": "N/A"}


def test_valid_files_produce_deterministic_serializable_report_input(artifacts):
    first = analyze.run_analysis(**artifacts)
    second = analyze.run_analysis(**artifacts)
    assert first == second
    assert first["schema_version"] == 2
    json.dumps(first, default=dataclasses.asdict, allow_nan=False)
    for version in ("v1", "v2"):
        assert first[f"summary_{version}"]["version"] == version


def test_different_planned_fingerprints_withhold_all_comparison_claims(artifacts):
    update_json(artifacts["meta_v2_path"], lambda m: m["fingerprints"].update(planned_suite_sha256="c" * 64))
    comparison = analyze.run_analysis(**artifacts)["comparison"]
    assert "comparison_withheld_reason" in comparison
    for key in ("finding_comparisons", "new_finding_evidence", "inconclusive_new_findings", "category_failure_rates"):
        assert key not in comparison


def test_flat_cli_emits_report_schema(artifacts):
    process = subprocess.run([sys.executable, "-m", "analysis.analyze",
                              str(artifacts["manifest_path"].parent)],
                             check=True, capture_output=True, text=True)
    output = json.loads(process.stdout)
    assert set(output) == {"schema_version", "summary_v1", "summary_v2", "comparison"}
    assert output["schema_version"] == 2


def test_nested_runner_layout_checks_both_manifests(artifacts, tmp_path):
    base = tmp_path / "nested"
    for version in ("v1", "v2"):
        folder = base / version
        folder.mkdir(parents=True)
        for name in ("manifest_path", f"results_{version}_path", f"meta_{version}_path"):
            source = artifacts[name]
            (folder / source.name).write_bytes(source.read_bytes())
    assert analyze.run_analysis_from_dir(base) == analyze.run_analysis(**artifacts)
    update_json(base / "v2" / "manifest.json", lambda m: m["a1"].update(validity_tier="GOLD"))
    with pytest.raises(ValueError, match="manifest files differ"):
        analyze.run_analysis_from_dir(base)


def test_valid_limit_and_skip_metadata_is_supported(artifacts):
    rows = [clean("v2")]
    artifacts["results_v2_path"].write_text(json.dumps(dataclasses.asdict(rows[0])) + "\n", encoding="utf8")
    digest = hashlib.sha256(artifacts["manifest_path"].read_bytes()).hexdigest()
    meta = metadata(rows, "v2", digest)
    meta["case_ids"].update(selected=["baseline:b1"], missing=[], skipped=["attack:a1"],
                            limit_excluded=["attack:a2"])
    meta["coverage"].update(selected=1, missing=0, skipped=1, limit_excluded=1)
    artifacts["meta_v2_path"].write_text(json.dumps(meta), encoding="utf8")
    result = analyze.run_analysis(**artifacts)
    assert result["comparison"]["coverage"]["unavailable"] == ["attack:a1", "attack:a2"]


def test_empty_recorded_run_is_labelled_with_its_expected_version(artifacts):
    artifacts["results_v2_path"].write_text("", encoding="utf8")
    digest = hashlib.sha256(artifacts["manifest_path"].read_bytes()).hexdigest()
    artifacts["meta_v2_path"].write_text(json.dumps(metadata([], "v2", digest)), encoding="utf8")
    result = analyze.run_analysis(**artifacts)
    assert result["summary_v2"]["version"] == "v2"
    assert result["summary_v2"]["drift"]["flip_rate"] == "N/A"


def test_missing_required_manifest_field_is_rejected(artifacts):
    update_json(artifacts["manifest_path"], lambda m: m["a1"].pop("oracle"))
    with pytest.raises(ValueError, match="oracle"):
        analyze.run_analysis(**artifacts)


@pytest.mark.parametrize("change", [lambda m: m["case_ids"]["planned"].reverse(),
    lambda m: m["case_ids"].update(missing=["attack:a1"]),
    lambda m: m["case_ids"].update(skipped=["attack:a1"])])
def test_inconsistent_plan_and_partitions_are_rejected(artifacts, change):
    def mutate(meta):
        change(meta)
        meta["coverage"].update({k: len(v) for k,v in meta["case_ids"].items()})
    update_json(artifacts["meta_v2_path"], mutate)
    with pytest.raises(ValueError, match="partition|planned case IDs"):
        analyze.run_analysis(**artifacts)


@pytest.mark.parametrize("changes", [dict(category="whitespace"), dict(baseline_id=None),
                                    dict(baseline_id="missing")])
def test_result_manifest_join_mismatch_is_rejected(artifacts, changes):
    rows = [clean("v2"), row("v2", **changes), row("v2", "a2")]
    artifacts["results_v2_path"].write_text(
        "".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in rows), encoding="utf8")
    with pytest.raises(ValueError, match="disagrees|unplanned"):
        analyze.run_analysis(**artifacts)


def test_non_success_prediction_cannot_enter_baseline_census():
    result = drift.baseline_confidence_census([clean(status_code=500)])
    assert result.eligible == 0
    assert result.no_prediction_ids == ["b1"]

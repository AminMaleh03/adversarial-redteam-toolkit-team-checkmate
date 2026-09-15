"""Tests for runner/gate.py.

Offline and model-free by construction. The orchestrator and the pure policy are
the two things the gate depends on and neither is this module's to implement, so
both are replaced by doubles here -- named ``fake_*`` and confined to this file.

Read that as the limit of what these tests prove. They prove the gate turns a
``GateOutcome`` into the right exit code, writes the right file, and refuses to
reach a verdict when it cannot. They do not prove any policy is correct, that
``emotion_v2`` passes anything, or that the pipeline runs end to end. That
evidence comes from a real integrated run and is reported separately.

    .venv/bin/python -m pytest tests/test_gate.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from contract import (
    CHECK_ERROR,
    CHECK_FAIL,
    CHECK_PASS,
    EXIT_CODE_BY_OUTCOME,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_PASS,
    OUTCOME_POLICY_FAILURE,
    CheckResult,
    GateOutcome,
)
from runner import gate

GATE_FIXTURES = ROOT / "tests" / "fixtures" / "stage3" / "gate"
POLICY_DOC = {
    "policy_id": "ci_emotion_v2_core_selection",
    "policy_version": "1.0.0",
    "suite_id": "core",
    "case_set_id": "ci_core_v1",
    "status": "frozen",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def outcome_from_fixture(name: str) -> GateOutcome:
    """Rebuild a GateOutcome from one of the shared gate fixtures.

    The fixtures are the agreed shape, so a double that returns one is returning
    something the contract actually permits -- ``GateOutcome.__post_init__`` would
    reject it otherwise, and that check is doing real work in these tests.
    """
    document = json.loads((GATE_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    document.pop("_synthetic", None)
    document["checks"] = [CheckResult(**check) for check in document["checks"]]
    return GateOutcome(**document)


def write_policy(tmp_path: Path, document: dict | None = None) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document or POLICY_DOC, indent=2), encoding="utf-8")
    return path


def write_run(tmp_path: Path, *, rows: list[dict] | None = None,
              meta: dict | None = None, target_id: str = "emotion_v2") -> Path:
    """A minimal but structurally real target directory: run_meta + results."""
    target_dir = tmp_path / "run" / target_id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "run_meta.json").write_text(
        json.dumps(meta if meta is not None else {"target_id": target_id}),
        encoding="utf-8",
    )
    rows = rows if rows is not None else [
        {
            "case_type": "baseline", "attack_id": None, "baseline_id": "dataset-anger-0",
            "category": None, "version": "v2", "status_code": 200,
            "response_body": "{}", "error": None, "label": "anger", "confidence": 0.9,
            "all_scores": {"anger": 0.9}, "latency_ms": 12.0, "latency_band": "normal",
            "endpoint_alive_after": True, "target_id": target_id, "suite_id": "core",
            "request_body_bytes": 31, "request_body_sha256": "ab" * 32,
        }
    ]
    (target_dir / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return target_dir


def install_doubles(monkeypatch, tmp_path, *, outcome=None, policy_error=None,
                    experiment=None, target_dirs=None, analysis=None,
                    policy_module_missing=False):
    """Put a fake orchestrator and a fake pure policy in front of the gate."""
    calls: dict = {}

    target_dir = write_run(tmp_path)
    resolved_dirs = target_dirs if target_dirs is not None else {"emotion_v2": str(target_dir)}

    def default_experiment(mode, run_name=None, results_root=None,
                           progress_callback=None, *, evaluation_ids=None,
                           html_only=False):
        calls["experiment"] = {
            "mode": mode, "run_name": run_name, "results_root": results_root,
            "evaluation_ids": evaluation_ids, "html_only": html_only,
        }
        return {
            "mode": mode,
            "run_id": "cafef00dbeef",
            "run_dir": tmp_path / "run",
            "status": "COMPLETE",
            "analysis": analysis if analysis is not None else {"schema_version": 3},
            "report_dir": tmp_path / "report",
            "report_html": tmp_path / "report" / "report.html",
            "report_pdf": None,
            "evaluations": [
                {"evaluation_id": "ci.emotion", "kind": "single",
                 "task_id": "emotion_7", "suite_id": "core",
                 "case_set_id": "ci_core_v1", "target_dirs": resolved_dirs}
            ],
        }

    fake_run_all = types.ModuleType("run_all")
    fake_run_all.run_experiment = experiment or default_experiment
    monkeypatch.setitem(sys.modules, "run_all", fake_run_all)

    if policy_module_missing:
        monkeypatch.setitem(sys.modules, "analysis.policy", None)
    else:
        def evaluate_policy(*, policy, analysis, run_metas, results_by_target):
            calls["policy"] = {
                "policy": policy, "analysis": analysis,
                "run_metas": run_metas, "results_by_target": results_by_target,
            }
            if policy_error is not None:
                raise policy_error
            return outcome

        fake_policy = types.ModuleType("analysis.policy")
        fake_policy.evaluate_policy = evaluate_policy
        monkeypatch.setitem(sys.modules, "analysis.policy", fake_policy)
        import analysis as analysis_pkg
        monkeypatch.setattr(analysis_pkg, "policy", fake_policy, raising=False)

    return calls


def invoke(tmp_path, *flags, policy: Path | None = None) -> tuple[int, dict | None]:
    out_dir = tmp_path / "out"
    policy_path = policy if policy is not None else write_policy(tmp_path)
    code = gate.main(["--policy", str(policy_path), "--out", str(out_dir), *flags])
    result_path = out_dir / gate.GATE_RESULT_NAME
    document = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return code, document


# ==========================================================================
# 1. a real outcome becomes the right exit code
# ==========================================================================


@pytest.mark.parametrize("fixture, expected_outcome, expected_code", [
    ("gate_pass", OUTCOME_PASS, 0),
    ("gate_policy_failure", OUTCOME_POLICY_FAILURE, 1),
    ("gate_execution_error", OUTCOME_EXECUTION_ERROR, 2),
    ("gate_all_rejecting", None, None),
    ("gate_wrong_clean_output", None, None),
])
def test_each_gate_fixture_exits_with_its_own_code(
    monkeypatch, tmp_path, fixture, expected_outcome, expected_code
):
    outcome = outcome_from_fixture(fixture)
    install_doubles(monkeypatch, tmp_path, outcome=outcome)
    code, document = invoke(tmp_path)

    # The last two fixtures assert against themselves: whatever outcome they
    # record, the exit code must be the contract's mapping of it and nothing else.
    assert code == (expected_code if expected_code is not None
                    else EXIT_CODE_BY_OUTCOME[outcome.outcome])
    assert document["outcome"] == (expected_outcome or outcome.outcome)
    assert document["exit_code"] == code


def test_pass_is_only_ever_the_policys_pass(monkeypatch, tmp_path):
    """0 is reachable from exactly one place: a real GateOutcome saying pass."""
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    assert invoke(tmp_path)[0] == 0
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_policy_failure"))
    assert invoke(tmp_path)[0] == 1


def test_exit_code_survives_an_unwritable_destination(monkeypatch, tmp_path):
    """Report generation and file writing must never change the verdict."""
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_policy_failure"))
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    code = gate.main(["--policy", str(write_policy(tmp_path)), "--out", str(blocked / "out")])
    assert code == 1


# ==========================================================================
# 2. what the gate hands the policy
# ==========================================================================


def test_the_policy_receives_parsed_runresults_not_paths(monkeypatch, tmp_path):
    calls = install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    invoke(tmp_path)

    handed = calls["policy"]
    assert set(handed) == {"policy", "analysis", "run_metas", "results_by_target"}
    rows = handed["results_by_target"]["emotion_v2"]
    assert [row.case_type for row in rows] == ["baseline"]
    assert rows[0].target_id == "emotion_v2"
    # Request-byte evidence reaches the policy as recorded, not recomputed.
    assert rows[0].request_body_bytes == 31
    assert handed["run_metas"]["emotion_v2"]["target_id"] == "emotion_v2"


def test_the_internal_ci_evaluation_is_what_gets_run(monkeypatch, tmp_path):
    calls = install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    invoke(tmp_path, "--html-only")
    assert calls["experiment"]["mode"] == "ci"
    assert calls["experiment"]["evaluation_ids"] == ["ci.emotion"]
    assert calls["experiment"]["html_only"] is True


def test_the_gate_supplies_the_artifact_paths_the_policy_cannot_know(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    _, document = invoke(tmp_path)
    artifacts = document["artifacts"]
    # The measured path, not the one the policy document happened to carry: the
    # fixture's authored "results/ci/emotion_v2/results.jsonl" must not survive
    # into a result that claims to name where this run actually wrote.
    assert artifacts["raw_results"]["emotion_v2"].endswith("emotion_v2/results.jsonl")
    assert str(tmp_path) in artifacts["raw_results"]["emotion_v2"]
    # An absent optional PDF is null, never a path that was not produced.
    assert artifacts["report_pdf"] is None


# ==========================================================================
# 3. everything that must be exit 2 rather than a verdict
# ==========================================================================


@pytest.mark.parametrize("prepare, expected_check", [
    pytest.param(
        lambda tmp_path: {"policy": tmp_path / "absent.json"},
        gate.CHECK_POLICY_READABLE, id="missing policy file",
    ),
])
def test_an_unreadable_policy_is_execution_error(monkeypatch, tmp_path, prepare, expected_check):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    code, document = invoke(tmp_path, **prepare(tmp_path))
    assert code == 2
    assert document["outcome"] == OUTCOME_EXECUTION_ERROR
    assert document["checks"][0]["check_id"] == expected_check
    assert document["checks"][0]["reason"]


def test_a_policy_that_is_not_json_is_execution_error(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code, document = invoke(tmp_path, policy=broken)
    assert code == 2
    assert "not valid JSON" in document["checks"][0]["reason"]


def test_a_missing_policy_module_is_execution_error_not_a_pass(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, policy_module_missing=True)
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_POLICY_MODULE
    # The whole point: no local stand-in policy exists to fall back to.
    assert document["outcome"] == OUTCOME_EXECUTION_ERROR


def test_an_orchestration_failure_is_execution_error(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("v2 endpoint failed its preflight health check")
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"),
                    experiment=boom)
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_ORCHESTRATION
    assert "preflight" in document["checks"][0]["reason"]


def test_an_orchestrator_without_the_stage3_signature_is_execution_error(monkeypatch, tmp_path):
    def legacy(mode, run_name=None, results_root=None, progress_callback=None):
        raise AssertionError("must not be called with the legacy signature")
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"),
                    experiment=legacy)
    code, document = invoke(tmp_path)
    assert code == 2
    assert "CONTRACTS.md 8" in document["checks"][0]["reason"]


def test_a_run_with_no_evaluations_index_is_execution_error(monkeypatch, tmp_path):
    def unindexed(*args, **kwargs):
        return {"run_dir": tmp_path / "run", "analysis": {"schema_version": 3}}
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"),
                    experiment=unindexed)
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_ORCHESTRATION


def test_missing_per_target_evidence_is_execution_error(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"),
                    target_dirs={"emotion_v2": str(tmp_path / "nowhere")})
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_EVIDENCE


def test_a_malformed_results_row_is_unusable_evidence_not_a_smaller_denominator(
    monkeypatch, tmp_path
):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    # Corrupt the row AFTER the doubles have written their well-formed run.
    (tmp_path / "run" / "emotion_v2" / "results.jsonl").write_text(
        '{"case_type": "baseline", "unexpected_field": 1}\n', encoding="utf-8"
    )
    code, document = invoke(tmp_path)
    assert code == 2
    assert "line 1" in document["checks"][0]["reason"]


def test_a_run_with_no_analysis_is_execution_error(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"),
                    analysis={})
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_EVIDENCE


def test_a_raising_policy_is_execution_error(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path,
                    policy_error=ValueError("policy status is draft"))
    code, document = invoke(tmp_path)
    assert code == 2
    assert document["checks"][0]["check_id"] == gate.CHECK_POLICY_CONTRACT
    assert "draft" in document["checks"][0]["reason"]


def test_a_policy_returning_the_wrong_type_is_execution_error(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome={"outcome": "pass", "exit_code": 0})
    code, document = invoke(tmp_path)
    assert code == 2
    assert "GateOutcome" in document["checks"][0]["reason"]


def test_error_paths_fabricate_no_candidate_or_reference_evidence(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, policy_module_missing=True)
    _, document = invoke(tmp_path)
    assert document["candidate"] == {}
    assert document["reference"] == {}
    # Empty means unknown. A placeholder hash here would be indistinguishable
    # from a real one in the CI log.
    assert document["selection_sha256"] == ""


# ==========================================================================
# 4. a trustworthy candidate failure is not an execution error
# ==========================================================================


def test_a_partial_run_with_complete_records_still_reaches_the_policy(monkeypatch, tmp_path):
    """An endpoint that died mid-suite is data, not a broken gate.

    run_experiment preserves that as a PARTIAL result and returns normally; the
    policy calls it a failure and the gate reports exit 1. Turning it into exit 2
    would lose the distinction between "the candidate is bad" and "we could not
    tell", which is the distinction the two codes exist for.
    """
    def partial(*args, **kwargs):
        target_dir = write_run(tmp_path)
        return {
            "mode": "ci", "run_id": "cafef00dbeef", "run_dir": tmp_path / "run",
            "status": "PARTIAL", "analysis": {"schema_version": 3},
            "report_dir": tmp_path / "report",
            "report_html": tmp_path / "report" / "report.html", "report_pdf": None,
            "evaluations": [{"evaluation_id": "ci.emotion",
                             "target_dirs": {"emotion_v2": str(target_dir)}}],
        }
    install_doubles(monkeypatch, tmp_path,
                    outcome=outcome_from_fixture("gate_policy_failure"),
                    experiment=partial)
    code, document = invoke(tmp_path)
    assert code == 1
    assert document["outcome"] == OUTCOME_POLICY_FAILURE
    assert any(check["status"] == CHECK_FAIL for check in document["checks"])


# ==========================================================================
# 5. structure: no second policy, no reverse import, no model on --help
# ==========================================================================


def test_help_loads_neither_a_model_nor_the_orchestrator():
    """--help must be instant and side-effect free, in a clean interpreter."""
    probe = (
        "import sys, runner.gate as g\n"
        "p = g.build_parser()\n"
        "p.format_help()\n"
        "loaded = [m for m in ('torch', 'transformers', 'run_all', 'endpoint.model')"
        " if m in sys.modules]\n"
        "print(loaded)\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout


def test_the_gate_defines_no_policy_of_its_own():
    source = (ROOT / "runner" / "gate.py").read_text(encoding="utf-8")
    assert "def evaluate_policy" not in source
    # The shared contract types, not a competing local copy.
    assert "class GateOutcome" not in source
    assert "class CheckResult" not in source


def test_run_all_never_imports_the_gate():
    source = (ROOT / "run_all.py").read_text(encoding="utf-8")
    assert "runner.gate" not in source
    assert "from runner import gate" not in source


def test_heavy_imports_are_deferred_out_of_module_scope():
    source = (ROOT / "runner" / "gate.py").read_text(encoding="utf-8")
    header = source.split("def ", 1)[0]
    for deferred in ("import run_all", "import analysis.policy"):
        assert deferred not in header, f"{deferred} must be deferred into a function"


def test_gate_result_carries_every_contract_field(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    _, document = invoke(tmp_path)
    reference = json.loads((GATE_FIXTURES / "gate_pass.json").read_text(encoding="utf-8"))
    reference.pop("_synthetic")
    assert set(document) == set(reference)
    assert document["schema_version"] == 1


def test_a_failing_check_is_readable_in_the_written_file(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_policy_failure"))
    _, document = invoke(tmp_path)
    failing = [c for c in document["checks"] if c["status"] == CHECK_FAIL]
    assert failing and all(c["reason"] for c in failing)
    passing = [c for c in document["checks"] if c["status"] == CHECK_PASS]
    # reason is required even when passing -- a gate that cannot say what it
    # checked has not passed.
    assert passing and all(c["reason"] for c in passing)


def test_an_execution_error_check_is_always_present_on_error_paths(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, policy_module_missing=True)
    _, document = invoke(tmp_path)
    assert any(check["status"] == CHECK_ERROR for check in document["checks"])


def test_an_error_path_still_names_the_policy_whose_bytes_were_read(monkeypatch, tmp_path):
    """Which policy was attempted is a fact about this process, not an invention."""
    install_doubles(monkeypatch, tmp_path, policy_module_missing=True)
    policy_path = write_policy(tmp_path)
    _, document = invoke(tmp_path, policy=policy_path)
    import hashlib
    assert document["policy_id"] == POLICY_DOC["policy_id"]
    assert document["policy_version"] == POLICY_DOC["policy_version"]
    assert document["policy_sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest()
    assert document["suite_id"] == "core"
    assert document["case_set_id"] == "ci_core_v1"
    # Still nothing invented about the candidate or the reference.
    assert document["candidate"] == {} and document["reference"] == {}


def test_a_policy_that_cannot_even_be_read_names_no_policy_identity(monkeypatch, tmp_path):
    install_doubles(monkeypatch, tmp_path, outcome=outcome_from_fixture("gate_pass"))
    _, document = invoke(tmp_path, policy=tmp_path / "absent.json")
    assert document["policy_id"] == ""
    assert document["policy_sha256"] == ""

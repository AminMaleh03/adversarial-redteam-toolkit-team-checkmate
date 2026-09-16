"""Targeted tests for run_all.py orchestration wiring.

Not a re-test of the runner/analysis/report themselves (those have their own suites) --
just the V3-specific behaviors: demo-only attack exclusion, and the strict separation
between run_experiment() (never touches a browser) and the CLI layer (the only place
webbrowser.open is allowed to be called).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_all  # noqa: E402
from contract import EVAL_KIND_PAIRED  # noqa: E402


def test_demo_excluded_attack_ids_contains_oversized_10mb():
    # The one explicitly authorized selection-level exclusion; nothing else.
    assert run_all.DEMO_EXCLUDED_ATTACK_IDS == ("malformed.oversized_10mb",)


def test_run_suite_passes_skip_and_limit_flags_to_the_runner(monkeypatch, tmp_path):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(run_all.runner_mod, "main", fake_main)
    exit_code = run_all.run_suite(
        "v1", "http://127.0.0.1:9", tmp_path / "out",
        attack_limit=50, skip=("malformed.oversized_10mb",),
    )
    assert exit_code == 0
    argv = captured["argv"]
    assert argv[argv.index("--limit") + 1] == "50"
    assert argv.count("--skip") == 1
    assert argv[argv.index("--skip") + 1] == "malformed.oversized_10mb"


def test_run_suite_with_no_skip_omits_the_flag_entirely(monkeypatch, tmp_path):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(run_all.runner_mod, "main", fake_main)
    run_all.run_suite("v1", "http://127.0.0.1:9", tmp_path / "out", attack_limit=None, skip=())
    assert "--skip" not in captured["argv"]
    assert "--limit" not in captured["argv"]  # full mode: no limit either


@pytest.fixture
def mocked_experiment(monkeypatch):
    """Stub every side-effecting collaborator of run_experiment() except the logic under
    test: which skip list and attack_limit reach run_suite for each mode, and whether
    anything in the orchestration layer ever touches a browser.
    """
    calls = []

    class FakeHandle:
        url = "http://127.0.0.1:0"

        def stop(self):
            pass

    def fake_run_suite(version, target, out_dir, *, attack_limit, skip=()):
        calls.append({"version": version, "attack_limit": attack_limit, "skip": tuple(skip)})
        return 0

    monkeypatch.setattr(run_all, "start_endpoint", lambda version, run_dir: FakeHandle())
    monkeypatch.setattr(run_all, "run_suite", fake_run_suite)
    monkeypatch.setattr(run_all, "load_baseline", lambda: [])
    monkeypatch.setattr(run_all, "build_full_suite", lambda baselines: [])
    monkeypatch.setattr(run_all, "compute_demo_attack_limit", lambda baselines, attacks: 42)
    monkeypatch.setattr(
        run_all, "run_analysis_and_report",
        lambda run_dir, idx, *, html_only, mode, progress_callback=None: {
            "analysis": {"summary_v1": {"coverage": {}}, "summary_v2": {"coverage": {}}, "comparison": {}},
            "demo_evidence": {}, "report_dir": run_dir / "report", "pdf_ok": True,
        },
    )
    monkeypatch.setattr(run_all, "print_demo_summary", lambda *a, **k: None)
    monkeypatch.setattr(run_all, "print_full_summary", lambda *a, **k: None)

    browser_calls = []
    monkeypatch.setattr(run_all.webbrowser, "open", lambda *a, **k: browser_calls.append(a) or True)
    return calls, browser_calls


def test_run_experiment_demo_mode_skips_10mb_and_limits_attacks(mocked_experiment, tmp_path):
    calls, browser_calls = mocked_experiment
    run_all.run_experiment(mode="demo", run_name="unit_demo", results_root=tmp_path)
    assert len(calls) == 2  # v1 and v2
    for call in calls:
        assert call["skip"] == run_all.DEMO_EXCLUDED_ATTACK_IDS
        assert call["attack_limit"] == 42
    assert browser_calls == []  # run_experiment() itself must never open a browser


def test_run_experiment_full_mode_has_no_skip_and_no_limit(mocked_experiment, tmp_path):
    calls, browser_calls = mocked_experiment
    run_all.run_experiment(mode="full", run_name="unit_full", results_root=tmp_path)
    assert len(calls) == 2
    for call in calls:
        assert call["skip"] == ()
        assert call["attack_limit"] is None
    assert browser_calls == []


def test_run_experiment_with_no_callback_behaves_exactly_as_before(mocked_experiment, tmp_path):
    # V3 callers (the CLI, existing tests) never pass progress_callback -- it must default
    # to a silent no-op, not raise, not change what gets returned.
    calls, browser_calls = mocked_experiment
    result = run_all.run_experiment(mode="demo", run_name="no_cb", results_root=tmp_path)
    assert result["mode"] == "demo"
    assert len(calls) == 2
    assert browser_calls == []


def test_run_experiment_emits_expected_stage_sequence(mocked_experiment, tmp_path):
    events = []
    run_all.run_experiment(
        mode="demo", run_name="stage_seq", results_root=tmp_path,
        progress_callback=lambda stage, message: events.append(stage),
    )
    # run_analysis_and_report is mocked wholesale by mocked_experiment, so only the
    # outer orchestration stages appear here; its own analyzing/generating_results
    # emission is covered separately below against the real function.
    assert events == [
        "initializing", "starting_v1", "attacking_v1", "starting_v2", "attacking_v2", "complete",
    ]


def test_run_analysis_and_report_emits_analyzing_then_generating_results(monkeypatch, tmp_path):
    monkeypatch.setattr(run_all, "VERIFIED_FULL_REPORT_DIR", tmp_path / "no_such_verified_dir")
    # run_analysis_from_dir now returns the v3 envelope (schema_version 3, evaluations[]);
    # run_all.run_analysis_and_report projects it through the official legacy_v2_view()
    # adapter, so the stub here must be a minimal but genuine v3 paired evaluation block,
    # not the pre-v3 {"schema_version": 2, ...} shape legacy_v2_view no longer accepts.
    monkeypatch.setattr(
        run_all.analysis_mod, "run_analysis_from_dir",
        lambda run_dir: {
            "schema_version": 3,
            "evaluations": [{
                "kind": EVAL_KIND_PAIRED,
                "targets": ["emotion_v1", "emotion_v2"],
                "summaries": {"emotion_v1": {}, "emotion_v2": {}},
                "comparison": {},
            }],
        },
    )
    monkeypatch.setattr(
        run_all, "build_demo_evidence",
        lambda run_dir, analysis, attack_index: {
            "literal_crash_case_available": False, "featured_failure": None,
            "featured_prediction_flip": None, "crash_status_note": None, "notes": [],
        },
    )

    def fake_generate_report(raw, report_dir, *, html_only, mode):
        report_dir.mkdir(parents=True)
        (report_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(run_all.report_mod, "generate_report", fake_generate_report)

    events = []
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_all.run_analysis_and_report(
        run_dir, {}, html_only=False, mode="demo",
        progress_callback=lambda stage, message: events.append(stage),
    )
    assert events == ["analyzing", "generating_results"]


def test_registry_experiment_accepts_relative_results_root(monkeypatch, tmp_path):
    class PlannedStop(RuntimeError):
        pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        run_all, "_plan_evaluation",
        lambda *args, **kwargs: (_ for _ in ()).throw(PlannedStop("planned stop")),
    )

    with pytest.raises(PlannedStop, match="planned stop"):
        run_all.run_experiment(
            mode="ci",
            run_name="relative_root",
            results_root=Path("relative-results"),
            evaluation_ids=["ci.emotion"],
            html_only=True,
        )

    run_dirs = list((tmp_path / "relative-results").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    document = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    target_dirs = document["evaluations"][0]["target_dirs"]
    assert target_dirs == {"emotion_v2": "runs/ci_emotion/emotion_v2"}
    assert not Path(target_dirs["emotion_v2"]).is_absolute()
    assert (run_dir / Path(target_dirs["emotion_v2"]).parent).is_dir()


# ------------------------------------------------------------------------------------------
# v6.2: application-commit provenance is obtained once, reused, and honestly explained
# ------------------------------------------------------------------------------------------


def test_run_json_records_the_real_forty_char_application_commit(monkeypatch, tmp_path):
    class PlannedStop(RuntimeError):
        pass

    synthetic_sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    assert len(synthetic_sha) == 40
    monkeypatch.setattr(
        run_all.runner_mod, "code_provenance",
        lambda root: {"app_commit": synthetic_sha, "dirty": False},
    )
    monkeypatch.setattr(
        run_all, "_plan_evaluation",
        lambda *args, **kwargs: (_ for _ in ()).throw(PlannedStop("planned stop")),
    )
    with pytest.raises(PlannedStop):
        run_all.run_experiment(
            mode="ci", run_name="commit_check", results_root=tmp_path,
            evaluation_ids=["ci.emotion"], html_only=True,
        )
    run_dir = next((tmp_path).iterdir())
    document = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert document["app_commit"] == synthetic_sha
    assert len(document["app_commit"]) == 40


def test_app_commit_unavailable_reason_is_none_when_commit_present():
    assert run_all._app_commit_unavailable_reason({"app_commit": "a" * 40, "dirty": False}) is None


def test_app_commit_unavailable_reason_explains_missing_provenance_explicitly():
    reason = run_all._app_commit_unavailable_reason({"app_commit": None, "dirty": None})
    assert reason
    assert "git" in reason.lower()
    # Must never look like a silent "unknown", a branch name, or a remote head standing in.
    assert reason not in ("unknown", "main", "HEAD", "origin/main")


def test_app_commit_unavailable_reason_never_invents_a_commit_from_empty_string():
    # An empty string is falsy, same as None -- must still produce an explicit reason,
    # never render as if a (blank) commit were recorded.
    reason = run_all._app_commit_unavailable_reason({"app_commit": "", "dirty": None})
    assert reason


# ------------------------------------------------------------------------------------------
# v6.2: report limitations must not leak paired-only (V1/V2 hardening) wording into a
# sentiment-only (single-target) run.
# ------------------------------------------------------------------------------------------

_PAIRED_ONLY_NOTE = "V2's defenses are application-layer only; no retraining was done."


def _real_registry():
    return run_all.target_registry.load_registry()


def test_applicable_limitations_excludes_paired_only_note_for_sentiment_only_run():
    assert any(_PAIRED_ONLY_NOTE in note for note in run_all.analysis_mod.LIMITATION_NOTES)
    blocks = [{
        "kind": "single",
        "targets": ["sentiment_v1"],
        "summaries": {"sentiment_v1": {"limitations": list(run_all.analysis_mod.LIMITATION_NOTES)}},
    }]
    notes = run_all._applicable_limitations(blocks, _real_registry())
    assert not any("V2's defenses are application-layer only" in note for note in notes)
    assert not any("hardening" in note.lower() for note in notes)
    assert len(notes) == len(run_all.analysis_mod.LIMITATION_NOTES) - 1


def test_applicable_limitations_keeps_paired_only_note_when_a_paired_evaluation_exists():
    blocks = [
        {"kind": "paired", "targets": ["emotion_v1", "emotion_v2"],
         "summaries": {
             "emotion_v1": {"limitations": list(run_all.analysis_mod.LIMITATION_NOTES)},
             "emotion_v2": {"limitations": list(run_all.analysis_mod.LIMITATION_NOTES)},
         }},
        {"kind": "single", "targets": ["sentiment_v1"],
         "summaries": {"sentiment_v1": {"limitations": list(run_all.analysis_mod.LIMITATION_NOTES)}}},
    ]
    notes = run_all._applicable_limitations(blocks, _real_registry())
    assert any("V2's defenses are application-layer only" in note for note in notes)
    # Deduplicated across both evaluations, not doubled.
    assert len(notes) == len(run_all.analysis_mod.LIMITATION_NOTES)


def test_applicable_limitations_keeps_paired_only_note_for_single_kind_hardened_target():
    # Regression guard: the CI gate's own ci.emotion evaluation is "single" kind (it tests
    # emotion_v2 alone against an approved clean-output reference, never a live V1 -- see
    # endpoint/targets.json) but is still genuinely about a hardened target. Gating on
    # evaluation "kind" alone (rather than registry.target(...).hardened) would wrongly strip
    # this note from every CI gate report and broke the real CI run once during development.
    blocks = [{
        "kind": "single", "targets": ["emotion_v2"],
        "summaries": {"emotion_v2": {"limitations": list(run_all.analysis_mod.LIMITATION_NOTES)}},
    }]
    notes = run_all._applicable_limitations(blocks, _real_registry())
    assert any("V2's defenses are application-layer only" in note for note in notes)
    assert len(notes) == len(run_all.analysis_mod.LIMITATION_NOTES)


def test_applicable_limitations_preserves_order_and_dedupes():
    blocks = [{
        "kind": "paired", "targets": ["emotion_v1", "emotion_v2"],
        "summaries": {
            "emotion_v1": {"limitations": ["a", "b"]},
            "emotion_v2": {"limitations": ["b", "c"]},
        },
    }]
    assert run_all._applicable_limitations(blocks, _real_registry()) == ["a", "b", "c"]


def test_release_workflow_prepares_results_and_preserves_gate_exit_code():
    workflow = (ROOT / ".github" / "workflows" / "release-gate.yml").read_text(
        encoding="utf-8"
    )
    mkdir = workflow.index("mkdir -p results")
    producer = workflow.index("python -m runner.gate")
    tee = workflow.index("tee results/gate.log")
    capture = workflow.index("code=${PIPESTATUS[0]}")
    record = workflow.index('echo "$code" > results/gate-exit-code.txt')
    enforce = workflow.index("code=$(cat results/gate-exit-code.txt 2>/dev/null || echo 2)")
    assert mkdir < producer < tee < capture < record < enforce
    assert 'test "$code" -eq 0' in workflow[enforce:]


def test_cli_opens_browser_by_default_but_not_with_no_open(monkeypatch, tmp_path):
    report_html = tmp_path / "report.html"
    report_html.write_text("<html></html>", encoding="utf-8")
    fake_result = {"report_html": report_html}
    monkeypatch.setattr(run_all, "run_experiment", lambda **kw: fake_result)
    opened = []
    monkeypatch.setattr(run_all.webbrowser, "open", lambda uri: opened.append(uri) or True)

    assert run_all.main(["--mode", "demo", "--run-name", "x"]) == 0
    assert len(opened) == 1
    assert opened[0] == report_html.resolve().as_uri()

    opened.clear()
    assert run_all.main(["--mode", "demo", "--run-name", "y", "--no-open"]) == 0
    assert opened == []

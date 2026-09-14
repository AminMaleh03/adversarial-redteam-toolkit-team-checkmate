"""Tests for the Stage 3 common foundation.

Owner: Ahsan (foundation tests and common fixtures).

Scope on purpose: this file tests the things the foundation actually ships -- the shared
contract types, the static registry, attack-registry isolation, the preserved benchmark
evidence, and the coherence of the fixture pack. It does NOT test analysis v3, the policy,
the sentiment endpoint or the gate, because none of those exist yet. A test that asserts
a not-yet-written feature works is how a foundation ends up claiming readiness it does not
have.

Nothing here loads model weights or touches the network.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import contract  # noqa: E402
from attacks import metadata as md  # noqa: E402
from contract import (  # noqa: E402
    AttackCase, CheckResult, ContractError, GateOutcome, ModelSpec, RunResult,
)
from endpoint.targets import (  # noqa: E402
    TargetConfigError, load_registry, missing_requirements, require_runnable,
)

FIXTURES = ROOT / "tests" / "fixtures" / "stage3"
BENCH = ROOT / "artifacts" / "benchmark_v6"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ======================================================================================
# contract additions
# ======================================================================================


class TestRunResultAdditions:
    def test_existing_positional_construction_still_works(self):
        """The whole point of appending with defaults: old call sites keep working."""
        r = RunResult(
            "baseline", None, "b1", None, "v1", 200, "{}", None, "joy", 0.9,
            {"joy": 0.9}, 1.0, "normal", True,
        )
        assert r.target_id == ""
        assert r.suite_id == ""
        assert r.request_body_bytes is None
        assert r.request_body_sha256 is None

    def test_field_order_is_append_only(self):
        from dataclasses import fields

        names = [f.name for f in fields(RunResult)]
        original = [
            "case_type", "attack_id", "baseline_id", "category", "version",
            "status_code", "response_body", "error", "label", "confidence",
            "all_scores", "latency_ms", "latency_band", "endpoint_alive_after",
        ]
        assert names[: len(original)] == original, "existing fields were reordered"
        assert names[len(original):] == [
            "target_id", "suite_id", "request_body_bytes", "request_body_sha256",
        ]

    def test_historical_rows_load_without_the_new_fields(self):
        """Every preserved benchmark row must still construct."""
        line = (BENCH / "run" / "results_v1.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        r = RunResult(**json.loads(line))
        assert r.target_id == ""
        assert r.request_body_sha256 is None

    def test_other_contracts_are_structurally_unchanged(self):
        from dataclasses import fields

        assert [f.name for f in fields(contract.BaselineCase)] == [
            "baseline_id", "text", "label", "source",
        ]
        assert [f.name for f in fields(contract.AttackCase)] == [
            "attack_id", "baseline_id", "category", "original_text", "attacked_text",
            "is_raw", "raw_body", "raw_headers",
        ]
        assert [f.name for f in fields(contract.Finding)] == [
            "finding_id", "title", "category", "severity_score", "severity_tier",
            "description", "remediation", "evidence",
        ]

    def test_contracts_version(self):
        assert contract.CONTRACTS_VERSION == "3.0.0"


class TestModelSpec:
    @pytest.mark.parametrize(
        "revision",
        ["main", "0e1cd91", "", "0e1cd914e3d46199ed785853e12b57304e04178", "z" * 40],
    )
    def test_rejects_anything_that_is_not_a_real_pin(self, revision):
        with pytest.raises(ContractError):
            ModelSpec(
                model_id="m", revision=revision, tokenizer_id="m",
                tokenizer_revision="0" * 40, labels=("A",), max_sequence_length=512,
            )

    def test_rejects_empty_and_duplicate_label_space(self):
        with pytest.raises(ContractError):
            ModelSpec("m", "0" * 40, "m", "0" * 40, (), 512)
        with pytest.raises(ContractError):
            ModelSpec("m", "0" * 40, "m", "0" * 40, ("A", "A"), 512)


class TestGateOutcome:
    def _checks(self, status="pass"):
        return [CheckResult("c1", status, "reason text")]

    def _build(self, outcome, exit_code, checks):
        return GateOutcome(
            outcome=outcome, exit_code=exit_code, policy_id="p", policy_version="1",
            policy_sha256="h", candidate={}, reference={}, suite_id="core",
            case_set_id="ci_core_v1", selection_sha256="s", checks=checks,
        )

    def test_exit_code_must_match_outcome(self):
        assert self._build("pass", 0, self._checks()).exit_code == 0
        for outcome, wrong in (("pass", 1), ("policy_failure", 0), ("execution_error", 1)):
            with pytest.raises(ContractError):
                self._build(outcome, wrong, self._checks("fail"))

    def test_zero_checks_is_never_a_result(self):
        with pytest.raises(ContractError):
            self._build("pass", 0, [])

    def test_pass_cannot_coexist_with_a_failing_blocking_check(self):
        with pytest.raises(ContractError):
            self._build("pass", 0, [CheckResult("c1", "fail", "it failed")])

    def test_all_not_applicable_is_not_a_pass(self):
        with pytest.raises(ContractError):
            self._build("pass", 0, [CheckResult("c1", "not_applicable", "skipped")])

    def test_policy_failure_needs_an_actual_failure(self):
        with pytest.raises(ContractError):
            self._build("policy_failure", 1, self._checks("pass"))

    def test_execution_error_needs_an_errored_check(self):
        with pytest.raises(ContractError):
            self._build("execution_error", 2, self._checks("fail"))

    def test_informational_check_does_not_block_a_pass(self):
        outcome = self._build("pass", 0, [
            CheckResult("blocking", "pass", "ok"),
            CheckResult("flip_rate", "fail", "informational only", blocking=False),
        ])
        assert outcome.outcome == "pass"

    def test_check_requires_a_reason(self):
        with pytest.raises(ContractError):
            CheckResult("c1", "pass", "")


# ======================================================================================
# registry
# ======================================================================================


class TestRegistry:
    def test_loads_without_importing_any_model(self):
        """Importing the registry must never drag in transformers, torch or the model."""
        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "from endpoint.targets import load_registry;"
            "r = load_registry();"
            "assert r.registry_version;"
            "bad = [m for m in ('torch','transformers','endpoint.model') if m in sys.modules];"
            "print('LOADED:' + ','.join(bad))" % ROOT
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
        )
        assert out.returncode == 0, out.stderr
        assert "LOADED:\n" in out.stdout or out.stdout.strip() == "LOADED:", out.stdout

    def test_declares_the_five_agreed_evaluations(self):
        r = load_registry()
        assert sorted(r.evaluations) == [
            "ci.emotion", "emotion.core", "emotion.oces", "sentiment.core",
            "sentiment.oces",
        ]

    def test_evaluation_shapes(self):
        r = load_registry()
        assert r.evaluation("emotion.core").kind == "paired"
        assert r.evaluation("emotion.core").target_ids == ("emotion_v1", "emotion_v2")
        assert r.evaluation("emotion.oces").kind == "paired"
        assert r.evaluation("emotion.oces").suite_id == "oces"
        assert r.evaluation("sentiment.core").kind == "single"
        assert r.evaluation("sentiment.core").target_ids == ("sentiment_v1",)
        assert r.evaluation("sentiment.oces").kind == "single"
        ci = r.evaluation("ci.emotion")
        assert ci.kind == "single" and ci.target_ids == ("emotion_v2",)
        assert ci.suite_id == "core", "CI is a selection of core, not a third suite"
        assert ci.case_set_id == "ci_core_v1"
        assert ci.mode == "ci"

    def test_no_suite_is_named_ci_core(self):
        r = load_registry()
        assert all(e.suite_id in ("core", "oces") for e in r.evaluations.values())

    def test_oces_declares_exactly_the_two_agreed_families(self):
        r = load_registry()
        for evaluation_id in ("emotion.oces", "sentiment.oces"):
            assert r.evaluation(evaluation_id).declared_families == (
                "oces.paraphrase", "oces.distractor",
            )

    def test_baseline_file_override_resolution(self):
        r = load_registry()
        assert r.baseline_file_for("emotion.core") == "baseline/baseline.json"
        assert r.baseline_file_for("emotion.oces") == "baseline/oces/emotion_seeds.json"
        assert r.baseline_file_for("sentiment.core") == "baseline/sentiment_baseline.json"
        assert (
            r.baseline_file_for("sentiment.oces") == "baseline/oces/sentiment_seeds.json"
        )
        assert r.baseline_file_for("ci.emotion") == "baseline/baseline.json"

    def test_pins_are_real_and_label_spaces_are_exact(self):
        r = load_registry()
        emotion = r.model_for("emotion_v2")
        assert emotion.revision == "0e1cd914e3d46199ed785853e12b57304e04178b"
        assert emotion.labels == (
            "anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise",
        )
        sentiment = r.model_for("sentiment_v1")
        assert sentiment.model_id == (
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
        )
        assert sentiment.revision == "714eb0fa89d2f80546fda750413ed43d93601a13"
        assert sentiment.labels == ("NEGATIVE", "POSITIVE"), "label case is load-bearing"
        assert sentiment.max_sequence_length == 512

    def test_sentiment_uses_version_v1_but_a_distinct_target_id(self):
        r = load_registry()
        assert r.target("sentiment_v1").version == "v1"
        assert r.target("emotion_v1").version == "v1"
        assert r.target("sentiment_v1").target_id != r.target("emotion_v1").target_id

    def test_module_paths_are_recorded_not_imported(self):
        r = load_registry()
        assert r.target("sentiment_v1").module == "endpoint.sentiment_v1"
        assert not (ROOT / "endpoint" / "sentiment_v1.py").exists(), (
            "this test is meaningless once Task 2 lands the module; update it then"
        )
        assert r.target("sentiment_v1").app_path == "endpoint.sentiment_v1:app"

    def test_unknown_ids_raise_rather_than_returning_none(self):
        r = load_registry()
        for call in (
            lambda: r.target("nope"),
            lambda: r.evaluation("nope"),
            lambda: r.model_for("nope"),
            lambda: r.task_for("nope"),
        ):
            with pytest.raises(ContractError):
                call()

    def test_existing_emotion_path_is_runnable_today(self):
        """The foundation must not break the existing emotion experiment."""
        r = load_registry()
        assert missing_requirements(r, "emotion.core") == []
        assert missing_requirements(r, "ci.emotion") == []
        require_runnable(r, "emotion.core")

    def test_future_task_files_are_missing_but_do_not_break_loading(self):
        r = load_registry()
        assert missing_requirements(r, "sentiment.core"), (
            "Task 2/4 files should still be absent at foundation time"
        )
        with pytest.raises(TargetConfigError):
            require_runnable(r, "sentiment.core")

    @pytest.mark.parametrize(
        "mutate,expected",
        [
            (lambda d: d["models"]["emotion_distilroberta"].__setitem__("revision", "main"),
             "40-hex"),
            (lambda d: d["tasks"]["emotion_7"].__setitem__("model_ref", "ghost"),
             "not a configured model"),
            (lambda d: d["targets"]["emotion_v2"].__setitem__("task_id", "ghost"),
             "not a configured task"),
            (lambda d: d["targets"]["emotion_v2"].__setitem__("port", 8000),
             "collides"),
            (lambda d: d["evaluations"]["emotion.core"].__setitem__(
                "target_ids", ["emotion_v1", "sentiment_v1"]), "cannot mix tasks"),
            (lambda d: d["evaluations"]["emotion.core"].__setitem__("kind", "single"),
             "requires exactly 1"),
            (lambda d: d["evaluations"]["ci.emotion"].__setitem__("suite_id", "ci_core"),
             "unknown suite"),
            (lambda d: d["tasks"]["emotion_7"].__setitem__(
                "baseline_file", "../../etc/passwd"), "must not escape"),
            (lambda d: d["targets"]["emotion_v2"].__setitem__("module", "endpoint/v2.py"),
             "dotted module path"),
        ],
    )
    def test_invalid_registries_are_rejected_with_a_useful_message(
        self, tmp_path, mutate, expected
    ):
        data = load_json(ROOT / "endpoint" / "targets.json")
        mutate(data)
        path = tmp_path / "targets.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TargetConfigError) as excinfo:
            load_registry(path)
        assert expected in str(excinfo.value)

    def test_unparseable_registry_is_an_error_not_an_empty_registry(self, tmp_path):
        path = tmp_path / "targets.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(TargetConfigError):
            load_registry(path)
        with pytest.raises(TargetConfigError):
            load_registry(tmp_path / "does_not_exist.json")

    def test_registry_records_its_own_source_hash(self):
        r = load_registry()
        assert r.source_sha256 == sha256_file(ROOT / "endpoint" / "targets.json")


# ======================================================================================
# attack registry isolation
# ======================================================================================


def _case(attack_id: str) -> AttackCase:
    return AttackCase(
        attack_id=attack_id, baseline_id=None, category="malformed",
        original_text=None, attacked_text="payload-" + attack_id, is_raw=False,
    )


def _meta(attack_id: str) -> md.AttackMetadata:
    return md.AttackMetadata(
        attack_id=attack_id, family="malformed", subfamily="fixture",
        relation=md.REL_SCHEMA, oracle=md.ORACLE_REQUEST_REJECTED,
        source="foundation test", validity_tier=md.TIER_GOLD,
    )


@pytest.fixture
def clean_registry():
    before_manifest = dict(md._MANIFEST)
    before_fingerprints = dict(md._FINGERPRINTS)
    md.reset()
    yield
    md._MANIFEST.clear()
    md._MANIFEST.update(before_manifest)
    md._FINGERPRINTS.clear()
    md._FINGERPRINTS.update(before_fingerprints)


class TestScopedRegistry:
    def test_clears_on_entry(self, clean_registry):
        """Snapshot-and-restore alone is not enough -- the scope must start empty."""
        md.register(_case("outer"), _meta("outer"))
        with md.scoped_registry():
            assert md.manifest() == {}
            assert md._FINGERPRINTS == {}

    def test_restores_exactly_on_exit(self, clean_registry):
        md.register(_case("outer"), _meta("outer"))
        expected_manifest = dict(md._MANIFEST)
        expected_fingerprints = dict(md._FINGERPRINTS)
        with md.scoped_registry():
            md.register(_case("inner"), _meta("inner"))
        assert md._MANIFEST == expected_manifest
        assert md._FINGERPRINTS == expected_fingerprints, (
            "the fingerprint registry must be restored too, or a later reused-id check "
            "either misses a real collision or invents one"
        )

    def test_nested_scopes(self, clean_registry):
        md.register(_case("outer"), _meta("outer"))
        with md.scoped_registry():
            md.register(_case("mid"), _meta("mid"))
            with md.scoped_registry():
                assert md.manifest() == {}
                md.register(_case("inner"), _meta("inner"))
                assert set(md.manifest()) == {"inner"}
            assert set(md.manifest()) == {"mid"}
        assert set(md.manifest()) == {"outer"}

    def test_restores_after_an_exception(self, clean_registry):
        md.register(_case("outer"), _meta("outer"))
        expected = dict(md._MANIFEST)
        with pytest.raises(RuntimeError):
            with md.scoped_registry():
                md.register(_case("inner"), _meta("inner"))
                raise RuntimeError("build blew up")
        assert md._MANIFEST == expected

    def test_two_task_builds_do_not_contaminate_each_other(self, clean_registry):
        """emotion -> sentiment -> emotion, with no leakage in either direction."""
        manifests = []
        for name in ("emotion", "sentiment", "emotion"):
            with md.scoped_registry():
                md.register(_case(f"{name}.a"), _meta(f"{name}.a"))
                md.register(_case(f"{name}.b"), _meta(f"{name}.b"))
                manifests.append(set(md.manifest()))
        assert manifests[0] == {"emotion.a", "emotion.b"}
        assert manifests[1] == {"sentiment.a", "sentiment.b"}
        assert manifests[2] == {"emotion.a", "emotion.b"}
        assert md.manifest() == {}

    def test_existing_callers_are_unaffected(self, clean_registry):
        """register/manifest/reset behave exactly as before outside the context."""
        md.register(_case("plain"), _meta("plain"))
        assert set(md.manifest()) == {"plain"}
        md.reset()
        assert md.manifest() == {}


# ======================================================================================
# preserved benchmark evidence
# ======================================================================================


class TestPreservedEvidence:
    EXPECTED = {
        "run/manifest.json":
            "0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717",
        "run/results_v1.jsonl":
            "f617ac34a1a0148ee4507491effcf89183fbc3c5c385416f0a554ef1a4ebcb82",
        "run/results_v2.jsonl":
            "0b37eb18b91521ea6bb0228462a1cf3fef85c2580e0d178a2502bac50a79273f",
        "run/run_meta_v1.json":
            "e32d8a68409ea6df301b296cfdfaa0fcc57ea1d104e6cb10f94140308ea67c04",
        "run/run_meta_v2.json":
            "646170e1143d9a8d6130baa9899432130c626fcaeb394428824c629bdc8ca276",
        "run/demo_evidence.json":
            "ecdf11d687076082b4b40ea64e2eb1e1a178860ba4b59393e78e409dfeb85792",
        "analysis/analysis.json":
            "12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da",
        "analysis/export_meta.json":
            "e1212b048a380f59f56c2cd926fd79cf7464afe7ca937651952d04b0afa042e5",
        "source/baseline.json":
            "78ea8914dd7aeade060a10d9a14671c3ed455cbe9a3ae087b63ab448db7c0ace",
    }

    @pytest.mark.parametrize("rel,expected", sorted(EXPECTED.items()))
    def test_bytes_are_preserved_exactly(self, rel, expected):
        """Catches line-ending conversion on checkout, which silently breaks every hash."""
        assert sha256_file(BENCH / rel) == expected

    def test_preserved_analysis_matches_the_published_report(self):
        published = ROOT / "artifacts" / "verified_full_report"
        meta = load_json(published / "export_meta.json")
        assert sha256_file(BENCH / "analysis" / "analysis.json") == meta["source_sha256"]

    def test_published_report_bytes_match_their_own_recorded_hashes(self):
        """Regression guard for the CRLF bug this foundation fixed."""
        published = ROOT / "artifacts" / "verified_full_report"
        meta = load_json(published / "export_meta.json")
        for name, expected in meta["files"].items():
            assert sha256_file(published / name) == expected, (
                f"{name} does not match its recorded hash -- .gitattributes may have "
                "stopped pinning artifacts/"
            )

    def test_recorded_manifest_hash_matches_the_preserved_manifest_file(self):
        meta = load_json(BENCH / "run" / "run_meta_v1.json")
        assert meta["fingerprints"]["manifest_sha256"] == sha256_file(
            BENCH / "run" / "manifest.json"
        )

    def test_both_versions_share_one_planned_fingerprint_and_order(self):
        v1 = load_json(BENCH / "run" / "run_meta_v1.json")
        v2 = load_json(BENCH / "run" / "run_meta_v2.json")
        assert (
            v1["fingerprints"]["planned_suite_sha256"]
            == v2["fingerprints"]["planned_suite_sha256"]
            == "7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430"
        )
        assert v1["case_ids"]["planned"] == v2["case_ids"]["planned"]
        assert len(v1["case_ids"]["planned"]) == 1928

    def test_provenance_records_the_limitations_rather_than_hiding_them(self):
        text = (BENCH / "PROVENANCE.md").read_text(encoding="utf-8")
        assert "not independently attested by the run itself" in text
        assert "no sender-recorded request-byte evidence" in text

    def test_defense_freeze_point_still_matches_the_checked_in_file(self):
        """Lamei authors OCES against this exact hash; it must not drift silently."""
        assert sha256_file(ROOT / "endpoint" / "v2.py") == (
            "cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e"
        )


# ======================================================================================
# frozen CI inputs
# ======================================================================================


class TestFrozenCiSelection:
    @pytest.fixture(scope="class")
    def case_set(self):
        return load_json(ROOT / "analysis" / "case_sets" / "ci_core_v1.json")

    @pytest.fixture(scope="class")
    def reference(self):
        return load_json(
            ROOT / "analysis" / "policies" / "ci_core_v1_clean_reference.json"
        )

    def test_identity(self, case_set):
        assert case_set["case_set_id"] == "ci_core_v1"
        assert case_set["suite_id"] == "core"

    def test_counts_are_derived_from_the_id_lists(self, case_set):
        counts = case_set["counts"]
        assert counts["baselines"] == len(case_set["baseline_ids"]) == 42
        assert counts["standalone_attacks"] == len(case_set["standalone_attack_ids"]) == 32
        assert counts["derived_attacks"] == len(case_set["derived_attack_ids"]) == 88
        assert counts["total_cases"] == 162 == sum(
            counts[k] for k in ("baselines", "standalone_attacks", "derived_attacks")
        )

    def test_no_duplicates(self, case_set):
        every = (
            case_set["baseline_ids"]
            + case_set["standalone_attack_ids"]
            + case_set["derived_attack_ids"]
        )
        assert len(set(every)) == len(every)

    def test_the_only_exclusion_is_actually_excluded(self, case_set):
        assert [e["attack_id"] for e in case_set["exclusions"]] == [
            "malformed.oversized_10mb"
        ]
        assert "malformed.oversized_10mb" not in case_set["standalone_attack_ids"]
        assert all(e["reason"] for e in case_set["exclusions"])

    def test_derived_cases_belong_to_the_declared_baselines(self, case_set):
        covered = set(case_set["derived_baseline_coverage"])
        assert covered == {"dataset-anger-0", "dataset-anger-1"}
        assert all(a.split(".")[0] in covered for a in case_set["derived_attack_ids"])

    def test_every_selected_case_exists_in_the_source_manifest_or_baseline(self, case_set):
        """No frozen id may point at a case that does not exist."""
        manifest = load_json(BENCH / "run" / "manifest.json")
        for attack_id in (
            case_set["standalone_attack_ids"] + case_set["derived_attack_ids"]
        ):
            assert attack_id in manifest, f"{attack_id} is not in the source manifest"
        planned = set(load_json(BENCH / "run" / "run_meta_v1.json")["case_ids"]["planned"])
        for baseline_id in case_set["baseline_ids"]:
            assert f"baseline:{baseline_id}" in planned

    def test_every_derived_case_has_its_clean_reference(self, case_set, reference):
        assert set(case_set["baseline_ids"]) == set(reference["top_labels"])
        for attack_id in case_set["derived_attack_ids"]:
            assert attack_id.split(".")[0] in reference["top_labels"]

    def test_reference_labels_come_from_the_preserved_v2_rows(self, reference):
        assert reference["source"]["evidence_sha256"] == sha256_file(
            BENCH / "run" / "results_v2.jsonl"
        )
        rows = {
            json.loads(line)["baseline_id"]: json.loads(line)
            for line in (BENCH / "run" / "results_v2.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and json.loads(line)["case_type"] == "baseline"
        }
        for baseline_id, entry in reference["top_labels"].items():
            assert rows[baseline_id]["label"] == entry["top_label"]
            assert rows[baseline_id]["confidence"] == entry["confidence"]

    def test_reference_is_labelled_as_a_regression_reference_not_ground_truth(
        self, reference
    ):
        assert reference["status"] == "regression_reference_not_ground_truth"
        assert "NOT a correctness certification" in reference["note"]

    def test_no_unresolvable_hash_was_invented(self, case_set):
        """Manifest/coverage hashes that need a future run must be absent, not guessed."""
        blob = json.dumps(case_set)
        assert "coverage_map_sha256" not in blob
        assert "0000000000" not in blob


# ======================================================================================
# fixture pack coherence
# ======================================================================================


class TestFixturePack:
    @pytest.fixture(scope="class")
    def expected(self):
        return load_json(FIXTURES / "expected_analysis_v3.json")

    @pytest.fixture(scope="class")
    def run_index(self):
        return load_json(FIXTURES / "runs" / "run.json")

    def test_manifest_hashes_are_real(self):
        manifest = load_json(FIXTURES / "MANIFEST.json")
        assert manifest["files"], "fixture manifest is empty"
        for rel, expected_hash in manifest["files"].items():
            assert sha256_file(FIXTURES / rel) == expected_hash, rel

    def test_no_placeholders_anywhere(self):
        for path in sorted(FIXTURES.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".jsonl"):
                text = path.read_text(encoding="utf-8")
                for forbidden in ("...", "PLACEHOLDER", "TODO"):
                    assert forbidden not in text, f"{path.name} contains {forbidden!r}"

    def test_run_index_covers_every_evaluation_and_target_dir(self, expected, run_index):
        indexed = {e["evaluation_id"] for e in run_index["evaluations"]}
        assert indexed == {b["evaluation_id"] for b in expected["evaluations"]}
        for entry in run_index["evaluations"]:
            for rel in entry["target_dirs"].values():
                assert (FIXTURES / rel / "results.jsonl").is_file()
                assert (FIXTURES / rel / "run_meta.json").is_file()

    def test_single_target_comparison_is_null_everywhere(self, expected):
        singles = [b for b in expected["evaluations"] if b["kind"] == "single"]
        assert singles, "no single-target evaluation in the fixture pack"
        for block in singles:
            assert "comparison" in block, "comparison must be present, not omitted"
            assert block["comparison"] is None, "it must be null, not {} and not a figure"

    def test_paired_delta_uses_the_common_denominator(self, expected):
        for block in expected["evaluations"]:
            if block["kind"] != "paired":
                continue
            comparison = block["comparison"]
            common = comparison["common_eligible_case_ids"]
            assert comparison["common_denominator"] == len(common)
            for target_id, r in comparison["flip_rate_on_common"].items():
                assert r["denominator"] == len(common), (
                    "a paired delta must not mix differently filtered populations"
                )

    def test_rates_carry_their_numerator_and_denominator(self, expected):
        def walk(node):
            if isinstance(node, dict):
                if set(node) >= {"numerator", "denominator", "rate"}:
                    n, d, r = node["numerator"], node["denominator"], node["rate"]
                    if d:
                        assert r == round(n / d, 6)
                        assert 0.0 <= r <= 1.0
                    else:
                        assert r is None, "zero denominator must be null, never 0.0"
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(expected)

    def test_nested_finding_object_is_preserved(self, expected):
        seen = 0
        for block in expected["evaluations"]:
            for summary in block["summaries"].values():
                for entry in summary["findings"]:
                    seen += 1
                    finding = entry["finding"]
                    assert set(finding) == {
                        "finding_id", "title", "category", "severity_score",
                        "severity_tier", "description", "remediation", "evidence",
                    }
                    contract.Finding(**finding)
                    assert "remediation_detail" in entry
                    assert "remediation_detail" not in finding
        assert seen, "no findings in the fixture pack"

    def test_remediation_verification_targets_the_right_thing(self, expected):
        for block in expected["evaluations"]:
            for target_id, summary in block["summaries"].items():
                for entry in summary["findings"]:
                    detail = entry["remediation_detail"]
                    verification = detail["verification"]
                    assert verification["target_id"] == target_id
                    assert verification["command"]
                    assert verification["includes_baselines"] is True
                    case_set = verification.get("case_set_file")
                    assert case_set and (ROOT / case_set).is_file()

    def test_a_remediation_example_declares_missing_evidence(self, expected):
        details = [
            entry["remediation_detail"]
            for block in expected["evaluations"]
            for summary in block["summaries"].values()
            for entry in summary["findings"]
        ]
        assert any(d["unavailable_evidence"] for d in details), (
            "at least one example must show how missing evidence is declared"
        )
        assert any(d["diagnosis_confidence"] == "supported" for d in details)

    def test_sentiment_rows_keep_the_uppercase_label_space(self):
        path = FIXTURES / "runs" / "sentiment_core" / "sentiment_v1" / "results.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["label"] is not None:
                assert row["label"] in ("NEGATIVE", "POSITIVE")
            if row["all_scores"]:
                assert set(row["all_scores"]) == {"NEGATIVE", "POSITIVE"}

    def test_every_new_row_carries_identity_and_request_byte_evidence(self):
        for path in FIXTURES.glob("runs/*/*/results.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                assert row["target_id"], f"{path}: row without target_id"
                assert row["suite_id"] in ("core", "oces")
                assert isinstance(row["request_body_bytes"], int)
                assert len(row["request_body_sha256"]) == 64
                RunResult(**row)

    def test_run_meta_hashes_match_the_result_bytes(self):
        for meta_path in FIXTURES.glob("runs/*/*/run_meta.json"):
            meta = load_json(meta_path)
            assert meta["fingerprints"]["results_sha256"] == sha256_file(
                meta_path.parent / "results.jsonl"
            )

    def test_oces_uses_only_the_two_agreed_families(self, expected):
        blocks = [b for b in expected["evaluations"] if b["oces"]]
        assert blocks, "no oces evaluation in the fixture pack"
        for block in blocks:
            assert block["oces"]["families"] == ["oces.paraphrase", "oces.distractor"]
            blob = json.dumps(block)
            assert "negation" not in blob
            assert "0.15" not in blob

    def test_every_planned_oces_case_has_a_per_target_status(self, expected):
        allowed = {
            "meets_expectation", "violates_expectation", "excluded", "unevaluable",
            "not_executed",
        }
        for block in expected["evaluations"]:
            if not block["oces"]:
                continue
            planned = set(block["oces"]["planned_attack_ids"])
            for data in block["oces"]["by_target"].values():
                assert set(data["per_case"]) == planned
                for entry in data["per_case"].values():
                    assert entry["status"] in allowed

    def test_oces_exposure_statement_does_not_claim_independence(self, expected):
        for block in expected["evaluations"]:
            if not block["oces"]:
                continue
            statement = block["oces"]["exposure_statement"]
            assert "authored after" in statement
            assert "NOT a blind holdout" in statement

    def test_coverage_buckets_partition_the_selected_attacks(self, expected):
        for block in expected["evaluations"]:
            coverage = block["coverage"]
            if not coverage:
                continue
            assert sum(coverage["counts"].values()) == coverage["selected_attacks"]
            every = [k for v in coverage["buckets"].values() for k in v]
            assert len(set(every)) == len(every), "a case is in two buckets"

    def test_gate_fixtures_satisfy_the_real_contract(self):
        names = sorted(p.name for p in (FIXTURES / "gate").glob("*.json"))
        assert names == [
            "gate_all_rejecting.json", "gate_execution_error.json", "gate_pass.json",
            "gate_policy_failure.json", "gate_wrong_clean_output.json",
        ]
        for path in (FIXTURES / "gate").glob("*.json"):
            raw = load_json(path)
            outcome = GateOutcome(
                outcome=raw["outcome"], exit_code=raw["exit_code"],
                policy_id=raw["policy_id"], policy_version=raw["policy_version"],
                policy_sha256=raw["policy_sha256"], candidate=raw["candidate"],
                reference=raw["reference"], suite_id=raw["suite_id"],
                case_set_id=raw["case_set_id"],
                selection_sha256=raw["selection_sha256"],
                checks=[CheckResult(**{k: c[k] for k in (
                    "check_id", "status", "reason", "evidence_refs", "observed",
                    "threshold", "blocking")}) for c in raw["checks"]],
                summary=raw["summary"], artifacts=raw["artifacts"],
                exclusions=raw["exclusions"], schema_version=raw["schema_version"],
            )
            assert outcome.exit_code == contract.EXIT_CODE_BY_OUTCOME[outcome.outcome]

    def test_the_three_exit_codes_are_all_represented(self):
        codes = {
            load_json(p)["exit_code"] for p in (FIXTURES / "gate").glob("*.json")
        }
        assert codes == {0, 1, 2}

    def test_gate_references_the_real_committed_artifacts(self):
        raw = load_json(FIXTURES / "gate" / "gate_pass.json")
        assert raw["reference"]["sha256"] == sha256_file(
            ROOT / "analysis" / "policies" / "ci_core_v1_clean_reference.json"
        )
        assert raw["selection_sha256"] == sha256_file(
            ROOT / "analysis" / "case_sets" / "ci_core_v1.json"
        )

    def test_stale_status_fixture_is_actually_stale(self):
        stale = load_json(FIXTURES / "api" / "status_stale.json")
        current = load_json(FIXTURES / "api" / "status_complete.json")
        assert stale["run_id"] != current["run_id"]
        assert stale["evaluation_id"] != current["evaluation_id"]

    def test_negative_fixtures_all_have_a_recorded_reason(self):
        reasons = load_json(FIXTURES / "negative" / "_reasons.json")["reasons"]
        files = {
            p.name for p in (FIXTURES / "negative").glob("*")
            if p.name != "_reasons.json"
        }
        assert files == set(reasons)
        assert all(reasons.values())

    def test_negative_mixed_identity_really_mixes_identity(self):
        path = FIXTURES / "negative" / "mixed_identity.jsonl"
        ids = {
            json.loads(line)["target_id"]
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        }
        assert len(ids) > 1

    def test_negative_truncated_file_does_not_parse(self):
        lines = (FIXTURES / "negative" / "truncated.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[-1])

    def test_negative_wrong_label_space_is_not_merely_a_case_difference(self):
        path = FIXTURES / "negative" / "wrong_label_space.jsonl"
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert row["label"] not in ("NEGATIVE", "POSITIVE")
        assert row["label"].upper() in ("NEGATIVE", "POSITIVE"), (
            "the point of this fixture is that case-folding would wrongly accept it"
        )

    def test_genuine_legacy_fixture_is_labelled_genuine_and_traceable(self):
        payload = load_json(FIXTURES / "legacy" / "genuine_v2_analysis.json")
        provenance = payload["_provenance"]
        assert provenance["genuine"] is True
        assert provenance["is_synthetic"] is False
        assert payload["schema_version"] == 2
        assert provenance["source_results_v1_sha256"] == sha256_file(
            BENCH / "run" / "results_v1.jsonl"
        )

    def test_synthetic_fixtures_say_they_are_synthetic(self, expected):
        assert expected["_synthetic"]["is_synthetic"] is True
        for path in sorted(FIXTURES.glob("runs/*/*/run_meta.json")):
            assert load_json(path)["_synthetic"]["is_synthetic"] is True

    def test_pack_stays_small_and_offline(self):
        total = sum(
            p.stat().st_size for p in FIXTURES.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        assert total < 1_000_000, f"fixture pack grew to {total} bytes"

    def test_builder_is_deterministic(self, tmp_path):
        """A rebuild must reproduce identical bytes, or a diff means nothing."""
        before = {
            p.relative_to(FIXTURES).as_posix(): sha256_file(p)
            for p in sorted(FIXTURES.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }
        result = subprocess.run(
            [sys.executable, str(FIXTURES / "build_fixtures.py")],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        after = {
            p.relative_to(FIXTURES).as_posix(): sha256_file(p)
            for p in sorted(FIXTURES.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }
        assert before == after

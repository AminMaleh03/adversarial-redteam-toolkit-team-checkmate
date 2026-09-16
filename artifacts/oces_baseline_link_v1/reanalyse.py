"""Reproduce only the corrected OCES block from immutable recorded responses.

Run from the repository root: python artifacts/oces_baseline_link_v1/reanalyse.py
No endpoints, model inference, new attack generation, or scoring-rule changes.
"""
import ast
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import run_all


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    registry = run_all.target_registry.load_registry()
    source = (ROOT / "run_all.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "_oces_block")
    function = ast.get_source_segment(source, node)
    record = {
        "correction": "Resolve the clean result from the recorded attack baseline_id, not attack metadata.",
        "original_code_commit": "724799c",
        "corrected_function_sha256": hashlib.sha256(function.encode()).hexdigest(),
        "reanalysis_script_sha256": sha(Path(__file__)),
        "scope": "Only evaluations[0].oces changed; run_identity still identifies original inference.",
        "model_inference_repeated": False,
        "evaluations": {},
    }
    for task in ("emotion", "sentiment"):
        evaluation_id = task + ".oces"
        bundle = ROOT / "artifacts" / (task + "_oces_v1")
        analysis_path = bundle / "analysis" / "analysis.json"
        original = json.loads(analysis_path.read_bytes())
        corrected = json.loads(analysis_path.read_bytes())
        inputs = {p.relative_to(ROOT).as_posix(): sha(p)
                  for p in sorted((bundle / "run").rglob("*")) if p.is_file()}
        with tempfile.TemporaryDirectory(prefix="redlab-oces-reanalysis-") as tmp:
            copied_run = Path(tmp) / "run"
            shutil.copytree(bundle / "run", copied_run)
            block = run_all._oces_block(registry, registry.evaluation(evaluation_id), copied_run)
        # The copied snapshot must agree with the original frozen authoring evidence.
        assert block["provenance"] == original["evaluations"][0]["oces"]["provenance"]
        corrected["evaluations"][0]["oces"] = block
        path = OUT / (task + ".analysis.json")
        path.write_text(json.dumps(corrected, indent=2) + "\n", encoding="utf-8", newline="\n")
        restored = json.loads(path.read_bytes())
        restored["evaluations"][0]["oces"] = original["evaluations"][0]["oces"]
        assert restored == original
        for target, summary in block["summaries"].items():
            drift = original["evaluations"][0]["summaries"][target]["drift"]
            assert summary["violation_rate"]["denominator"] == drift["eligible_comparisons"]
            assert summary["violation_rate"]["numerator"] == drift["qualifying_flips"]
        record["evaluations"][evaluation_id] = {
            "original_analysis": analysis_path.relative_to(ROOT).as_posix(),
            "original_analysis_sha256": sha(analysis_path),
            "corrected_analysis": path.relative_to(ROOT).as_posix(),
            "corrected_analysis_sha256": sha(path),
            "preserved_inputs_sha256": inputs,
            "statuses": {t: s["statuses"] for t, s in block["summaries"].items()},
        }
    (OUT / "correction.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v["statuses"] for k, v in record["evaluations"].items()}, indent=2))


if __name__ == "__main__":
    main()

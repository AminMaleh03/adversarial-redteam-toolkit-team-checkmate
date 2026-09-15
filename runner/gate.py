"""The release gate. Turns one real CI evaluation into exit 0, 1 or 2.

    python -m runner.gate --policy analysis/policies/ci_core_v1.json --out results/ci

What it does, in order:

    1. read the policy file and hash the exact bytes it read;
    2. call ``run_all.run_experiment`` for the internal ``ci`` evaluation -- the
       orchestrator runs the endpoint and the runner, this module does not
       re-implement either;
    3. collect the produced analysis, every target's ``run_meta.json`` and every
       target's parsed ``RunResult`` rows;
    4. hand all of it to ``analysis.policy.evaluate_policy``, which is pure and is
       the only thing that decides pass or fail;
    5. write ``gate_result.json`` and return ``GateOutcome.exit_code``.

Three rules this module exists to enforce, and they are the ones easiest to lose:

**The decision is not made here.** There is no policy logic in this file, no
threshold, no recalibration, no "skip the hard cases when CI is red". A policy that
cannot be loaded, or an evaluation that could not run, produces an
``execution_error`` -- never a pass, and never a quiet fail either, because "the
candidate is bad" and "we could not tell" are different claims.

**The exit code reaches the shell.** ``main`` returns it and ``__main__`` passes it
to ``sys.exit``. Nothing after the evaluation -- report generation, an optional PDF,
writing this file -- may swallow it. A gate that returns 0 because the HTML rendered
is worse than no gate.

**Imports go one way.** ``runner.gate`` imports ``run_all``; ``run_all`` must never
import ``runner.gate``. The gate calls the orchestrator, not the reverse. Both heavy
imports here are deferred into the function that needs them, so ``--help``, an
offline test and every error path load no model and no orchestrator.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract import (  # noqa: E402
    CHECK_ERROR,
    CHECK_NOT_APPLICABLE,
    EXIT_CODE_BY_OUTCOME,
    OUTCOME_EXECUTION_ERROR,
    CheckResult,
    ContractError,
    GateOutcome,
    RunResult,
)

DEFAULT_EVALUATION = "ci.emotion"
GATE_RESULT_NAME = "gate_result.json"

# Check ids this module may produce itself. Every one of them is a statement about
# whether the gate could run at all -- never about the candidate's behaviour, which
# is entirely the policy's business.
CHECK_POLICY_READABLE = "gate_policy_readable"
CHECK_ORCHESTRATION = "gate_orchestration"
CHECK_EVIDENCE = "gate_evidence"
CHECK_POLICY_MODULE = "gate_policy_module"
CHECK_POLICY_CONTRACT = "gate_policy_contract"


class GateExecutionError(Exception):
    """The gate could not reach a verdict. Carries the check that says why.

    ``context`` carries only what was genuinely established before the failure --
    the identity of the policy whose bytes were actually read, and nothing else.
    It is never used to fill in a candidate or a reference.
    """

    def __init__(self, check: CheckResult, context: dict | None = None) -> None:
        super().__init__(check.reason)
        self.check = check
        self.context = dict(context or {})


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------


def execution_error(
    check: CheckResult,
    *,
    policy_id: str = "",
    policy_version: str = "",
    policy_sha256: str = "",
    suite_id: str = "",
    case_set_id: str = "",
    artifacts: dict | None = None,
) -> GateOutcome:
    """An honest "could not evaluate", with nothing invented to fill the shape.

    ``candidate`` and ``reference`` stay empty. They describe evidence, and in this
    path there is none worth describing: a gate that prints a candidate identity it
    never verified is exactly the failure mode the policy contract forbids. The same
    goes for ``selection_sha256`` -- empty means unknown, and no placeholder hash is
    substituted for it.
    """
    return GateOutcome(
        outcome=OUTCOME_EXECUTION_ERROR,
        exit_code=EXIT_CODE_BY_OUTCOME[OUTCOME_EXECUTION_ERROR],
        policy_id=policy_id,
        policy_version=policy_version,
        policy_sha256=policy_sha256,
        candidate={},
        reference={},
        suite_id=suite_id,
        case_set_id=case_set_id,
        selection_sha256="",
        checks=[check],
        summary={
            "blocking_checks": 1 if check.blocking else 0,
            "passed": 0,
            "failed": 0,
            "errored": 1,
            "claim": (
                "The gate did not reach a verdict. This is not a candidate failure "
                "and it is not a pass; no policy check was evaluated against real "
                "evidence."
            ),
        },
        artifacts=dict(artifacts or {}),
    )


def outcome_to_dict(outcome: GateOutcome) -> dict:
    """Serialise for ``gate_result.json``. Field order follows the contract's."""
    payload = dataclasses.asdict(outcome)
    # dataclasses.asdict already recursed into the CheckResults; keep the key order
    # the fixtures use so a diff against tests/fixtures/stage3/gate/* stays readable.
    payload["schema_version"] = outcome.schema_version
    ordered = {"schema_version": payload.pop("schema_version")}
    ordered.update(payload)
    return ordered


def write_gate_result(out_dir: Path, outcome: GateOutcome) -> Path | None:
    """Write ``gate_result.json``, and say so honestly if the destination will not.

    Never raises. A gate that crashed while reporting that it crashed would return
    an exception's exit code instead of the outcome's, which is the one thing the
    exit code must not depend on.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / GATE_RESULT_NAME
        path.write_text(
            json.dumps(outcome_to_dict(outcome), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path
    except OSError as exc:
        print(
            f"could not write {out_dir / GATE_RESULT_NAME}: {exc}\n"
            f"outcome was {outcome.outcome} (exit {outcome.exit_code}); "
            "the exit code is unaffected.",
            file=sys.stderr,
        )
        return None


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


def load_policy(path: Path) -> tuple[dict, str]:
    """Read the policy and hash the exact bytes read. No interpretation here.

    Whether the policy is draft, frozen, complete or self-contradictory is
    ``evaluate_policy``'s call, not this function's -- including the rule that a
    draft policy must raise rather than pass.
    """
    import hashlib

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_POLICY_READABLE,
                status=CHECK_ERROR,
                reason=f"cannot read the policy file {path}: {exc}",
                evidence_refs=[str(path)],
            )
        ) from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_POLICY_READABLE,
                status=CHECK_ERROR,
                reason=f"the policy file {path} is not valid JSON: {exc}",
                evidence_refs=[str(path)],
            )
        ) from exc
    if not isinstance(document, dict):
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_POLICY_READABLE,
                status=CHECK_ERROR,
                reason=f"the policy file {path} must contain a JSON object",
                evidence_refs=[str(path)],
            )
        )
    return document, hashlib.sha256(raw).hexdigest()


def parse_results(path: Path) -> list[RunResult]:
    """One ``RunResult`` per line, or an error naming the line that broke.

    Rows are never repaired and never skipped. A results file the gate cannot read
    in full is unusable evidence, and unusable evidence is exit 2 -- silently
    dropping a malformed row would shrink the denominator of every rate computed
    from it.
    """
    rows: list[RunResult] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(RunResult(**json.loads(line)))
            except (ValueError, TypeError) as exc:
                raise GateExecutionError(
                    CheckResult(
                        check_id=CHECK_EVIDENCE,
                        status=CHECK_ERROR,
                        reason=(
                            f"{path} line {number} is not a RunResult: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        evidence_refs=[str(path)],
                    )
                ) from exc
    return rows


def collect_evidence(result: dict, evaluation_id: str) -> dict:
    """Gather what ``evaluate_policy`` needs out of what the orchestrator returned.

    ``run_experiment`` reports where it wrote things; this reads them back from
    disk rather than trusting in-memory summaries, because the policy's identity
    and hash checks are about the artifacts a reviewer can open later.

    Raises :class:`GateExecutionError` -- never returns a partial dict. A missing
    ``run_meta.json`` or an unreadable results file is exactly the "missing or
    unusable evidence" the contract maps to exit 2.
    """
    evaluations = result.get("evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=(
                    "run_all.run_experiment returned no 'evaluations' index, so the "
                    "gate cannot tell which directory holds which target's evidence. "
                    "This is the CONTRACTS.md 8 orchestration contract (run_id plus "
                    "evaluations[] with target_dirs); it is Ahsan's to land and is "
                    "not something this module may guess at."
                ),
                evidence_refs=[str(result.get("run_dir", ""))],
                observed=sorted(result),
            )
        )

    entry = next(
        (item for item in evaluations
         if isinstance(item, dict) and item.get("evaluation_id") == evaluation_id),
        None,
    )
    if entry is None:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=(
                    f"the run reported no evaluation {evaluation_id!r}; it reported "
                    f"{[item.get('evaluation_id') for item in evaluations if isinstance(item, dict)]}"
                ),
                observed=evaluation_id,
            )
        )

    target_dirs = entry.get("target_dirs") or {}
    if not isinstance(target_dirs, dict) or not target_dirs:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=(
                    f"evaluation {evaluation_id!r} reported no target_dirs, so there "
                    "is no per-target evidence to score."
                ),
            )
        )

    run_metas: dict[str, dict] = {}
    results_by_target: dict[str, list[RunResult]] = {}
    raw_paths: dict[str, str] = {}
    for target_id, directory in sorted(target_dirs.items()):
        target_dir = Path(directory)
        meta_path = target_dir / "run_meta.json"
        results_path = target_dir / "results.jsonl"
        for required in (meta_path, results_path):
            if not required.is_file():
                raise GateExecutionError(
                    CheckResult(
                        check_id=CHECK_EVIDENCE,
                        status=CHECK_ERROR,
                        reason=f"{target_id}: required evidence {required} is missing",
                        evidence_refs=[str(required)],
                    )
                )
        try:
            run_metas[target_id] = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateExecutionError(
                CheckResult(
                    check_id=CHECK_EVIDENCE,
                    status=CHECK_ERROR,
                    reason=f"{target_id}: {meta_path} is unreadable: {exc}",
                    evidence_refs=[str(meta_path)],
                )
            ) from exc
        results_by_target[target_id] = parse_results(results_path)
        raw_paths[target_id] = str(results_path)

    analysis = result.get("analysis")
    if not isinstance(analysis, dict) or not analysis:
        raise GateExecutionError(
            CheckResult(
                check_id=CHECK_EVIDENCE,
                status=CHECK_ERROR,
                reason=(
                    "the run produced no analysis document, so there is nothing for "
                    "the policy's semantic checks to read."
                ),
            )
        )

    report_dir = result.get("report_dir")
    artifacts = {
        "analysis_json": str(Path(report_dir) / "analysis.json") if report_dir else None,
        "report_html": str(result.get("report_html")) if result.get("report_html") else None,
        # None, not a path, when the optional PDF did not render. html_only stays
        # supported; a missing PDF is not missing gate evidence.
        "report_pdf": str(result["report_pdf"]) if result.get("report_pdf") else None,
        "raw_results": raw_paths,
        "run_dir": str(result.get("run_dir", "")) or None,
    }
    return {
        "analysis": analysis,
        "run_metas": run_metas,
        "results_by_target": results_by_target,
        "artifacts": artifacts,
    }


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


def run_gate(args: argparse.Namespace) -> GateOutcome:
    """Execute the evaluation and evaluate the policy against what it produced."""
    policy_path = Path(args.policy)
    policy, policy_sha256 = load_policy(policy_path)
    policy_id = str(policy.get("policy_id", ""))
    policy_version = str(policy.get("policy_version", ""))
    suite_id = str(policy.get("suite_id", ""))
    case_set_id = str(policy.get("case_set_id", ""))

    # Established facts, carried onto the error paths below. The policy bytes were
    # really read and really hashed; saying which policy was attempted is a
    # statement about this process, not a claim about the candidate.
    identity = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
        "suite_id": suite_id,
        "case_set_id": case_set_id,
    }

    def fail(check: CheckResult) -> GateExecutionError:
        return GateExecutionError(check, identity)

    # Deferred: importing run_all pulls in the orchestrator, the analysis and the
    # report stack. --help and every offline test must not pay for that, and the
    # reverse edge (run_all importing this module) must never exist.
    try:
        import run_all
    except Exception as exc:                       # noqa: BLE001
        raise fail(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=f"cannot import run_all: {type(exc).__name__}: {exc}",
            )
        ) from exc

    try:
        import analysis.policy as policy_module
    except Exception as exc:                       # noqa: BLE001
        raise fail(
            CheckResult(
                check_id=CHECK_POLICY_MODULE,
                status=CHECK_ERROR,
                reason=(
                    f"cannot import analysis.policy: {type(exc).__name__}: {exc}. "
                    "The gate has no policy of its own and will not invent one: "
                    "a stand-in that returned success would make this CLI look "
                    "complete while checking nothing."
                ),
            )
        ) from exc

    evaluate_policy = getattr(policy_module, "evaluate_policy", None)
    if not callable(evaluate_policy):
        raise fail(
            CheckResult(
                check_id=CHECK_POLICY_MODULE,
                status=CHECK_ERROR,
                reason="analysis.policy defines no callable evaluate_policy",
            )
        )

    try:
        result = run_all.run_experiment(
            "ci",
            run_name=args.run_name,
            results_root=Path(args.results_root) if args.results_root else None,
            evaluation_ids=[args.evaluation],
            html_only=args.html_only,
        )
    except TypeError as exc:
        raise fail(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=(
                    f"run_all.run_experiment does not accept the CONTRACTS.md 8 "
                    f"signature yet ({exc}). The gate will not fall back to the "
                    "two-target emotion flow: that would score a different "
                    "evaluation than the policy names."
                ),
            )
        ) from exc
    except Exception as exc:                       # noqa: BLE001
        # Orchestration-level failure: the endpoint never came up, the preflight
        # failed, the run could not be published. That is exit 2. A candidate that
        # behaved badly does NOT arrive here -- run_experiment preserves those as
        # data and returns normally, and the policy calls them a failure.
        raise fail(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=(
                    f"the {args.evaluation} evaluation did not complete: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        ) from exc

    evidence = collect_evidence(result, args.evaluation)

    try:
        outcome = evaluate_policy(
            policy=policy,
            analysis=evidence["analysis"],
            run_metas=evidence["run_metas"],
            results_by_target=evidence["results_by_target"],
        )
    except Exception as exc:                       # noqa: BLE001
        raise fail(
            CheckResult(
                check_id=CHECK_POLICY_CONTRACT,
                status=CHECK_ERROR,
                reason=(
                    f"evaluate_policy raised {type(exc).__name__}: {exc}. A policy "
                    "that cannot be evaluated has not been passed."
                ),
            )
        ) from exc

    if not isinstance(outcome, GateOutcome):
        raise fail(
            CheckResult(
                check_id=CHECK_POLICY_CONTRACT,
                status=CHECK_ERROR,
                reason=(
                    "evaluate_policy returned "
                    f"{type(outcome).__name__}, not a contract.GateOutcome"
                ),
            )
        )

    # The paths are ours to supply -- the pure policy has no file access and cannot
    # know where anything was written, so the measured paths win over anything the
    # policy carried. Keys the policy added that we do not produce are kept. A null
    # here means "not produced": an optional PDF that did not render must not be
    # reported as a path to a file nobody can open.
    merged = dict(outcome.artifacts or {})
    merged.update(evidence["artifacts"])
    outcome.artifacts = merged
    if not outcome.policy_sha256:
        outcome.policy_sha256 = policy_sha256
    if not outcome.policy_id:
        outcome.policy_id = policy_id
    if not outcome.policy_version:
        outcome.policy_version = policy_version
    if not outcome.suite_id:
        outcome.suite_id = suite_id
    if not outcome.case_set_id:
        outcome.case_set_id = case_set_id
    return outcome


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runner.gate",
        description="Run the CI evaluation and turn the policy result into an exit code.",
        epilog=(
            "exit 0 = the named policy passed on real evidence; "
            "1 = a well-recorded candidate failure; "
            "2 = the gate could not reach a verdict (configuration, readiness, "
            "missing or unusable evidence)."
        ),
    )
    parser.add_argument("--policy", required=True, metavar="PATH",
                        help="policy JSON document to evaluate against")
    parser.add_argument("--out", required=True, metavar="DIR",
                        help=f"directory to write {GATE_RESULT_NAME} into")
    parser.add_argument("--evaluation", default=DEFAULT_EVALUATION, metavar="ID",
                        help=f"registry evaluation to run (default {DEFAULT_EVALUATION})")
    parser.add_argument("--html-only", action="store_true",
                        help="skip the optional PDF; a missing PDF is not missing gate evidence")
    parser.add_argument("--run-name", default=None, metavar="NAME",
                        help="output subdirectory under the results root")
    parser.add_argument("--results-root", default=None, metavar="DIR",
                        help="where the run directory is created (default: the orchestrator's)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return the gate's exit code. Never returns 0 for anything but a real pass."""
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)

    try:
        outcome = run_gate(args)
    except GateExecutionError as exc:
        outcome = execution_error(exc.check, **exc.context)
    except Exception as exc:                       # noqa: BLE001
        # Anything unanticipated is still exit 2 with a readable reason, because the
        # alternative is a traceback and an exit code nobody configured.
        outcome = execution_error(
            CheckResult(
                check_id=CHECK_ORCHESTRATION,
                status=CHECK_ERROR,
                reason=f"unhandled {type(exc).__name__}: {exc}",
                observed=traceback.format_exc(limit=6),
            )
        )

    written = write_gate_result(out_dir, outcome)
    print(f"gate      {outcome.outcome}  exit {outcome.exit_code}")
    if written is not None:
        print(f"result    {written}")
    for check in outcome.checks:
        if check.status != CHECK_NOT_APPLICABLE:
            marker = "x" if check.status in ("fail", "error") else "."
            print(f"  [{marker}] {check.check_id}: {check.reason}")
    return outcome.exit_code


if __name__ == "__main__":
    # The whole point. The exit code is the product; nothing downstream of the
    # evaluation is allowed to replace it.
    sys.exit(main())

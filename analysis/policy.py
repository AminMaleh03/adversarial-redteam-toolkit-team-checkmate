"""The pure CI policy: recorded evidence in, a GateOutcome out.

Pure means pure. No file, process, network or model I/O happens here; everything the
policy judges is passed in already parsed. ``results_by_target`` carries the parsed
``RunResult`` rows so operational checks can inspect **every selected request**, including
ones excluded from semantic scoring, without changing how the historical report scored
anything.

What a pass claims
------------------
That this candidate revision met this named, versioned policy on this frozen selection.
Not general accuracy, not multilingual robustness, not resistance to every adversarial
input, and not production readiness.

Outcome discipline
------------------
Infrastructure, configuration, invalid evidence or an unresolved (draft) policy produce
``execution_error``. A well-recorded candidate defect produces ``policy_failure``.
Structural errors take precedence when the results cannot be trusted, because a gate that
cannot say what it checked has not passed. Zero executed checks is never a pass.
"""

from __future__ import annotations

import re

from contract import (
    CHECK_ERROR,
    CHECK_FAIL,
    CHECK_NOT_APPLICABLE,
    CHECK_PASS,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_PASS,
    OUTCOME_POLICY_FAILURE,
    CheckResult,
    GateOutcome,
)

CHECK_POLICY_VALID = "policy_valid"
CHECK_CANDIDATE_IDENTITY = "candidate_identity"
CHECK_SELECTION_INTEGRITY = "selection_integrity"
CHECK_COMPLETION = "selection_completion"
CHECK_CLEAN_RESPONSES = "clean_responses_coherent"
CHECK_CLEAN_AGREEMENT = "clean_label_agreement"
CHECK_NO_SERVER_ERRORS = "no_server_errors"
CHECK_NO_TIMEOUTS = "no_timeouts_or_transport_failures"
CHECK_HEALTH = "health_after_every_request"
CHECK_NO_LEAKS = "no_leak_signatures"
CHECK_REJECTIONS = "documented_rejection_behaviour"
CHECK_BASELINE_ACCURACY = "ground_truth_baseline_accuracy"
CHECK_FLIP_RATE = "attack_flip_rate"
CHECK_SLOW = "slow_responses"

ALLOWED_REJECTION_STATUSES = (400, 413, 415, 422)

LEAK_MARKERS = ("Traceback (most recent call last)", "site-packages", 'File "')
_WIN_PATH = re.compile(r"[A-Za-z]:\\")
_UNIX_PATH = re.compile(r"(?<![\w.])/(?:home|usr|var|Users|etc|opt)/")

LEAK_DETECTOR_LIMITS = (
    "Signature-based: it detects stack traces, absolute filesystem paths and internal "
    "module names. It does not prove the absence of disclosure, and ordinary validation "
    "output is deliberately not counted."
)


class PolicyError(ValueError):
    """The policy document itself cannot be used."""


def _check(check_id, status, reason, **kwargs) -> CheckResult:
    return CheckResult(check_id=check_id, status=status, reason=reason, **kwargs)


def _validate_policy(policy: dict) -> list:
    """A draft policy never passes, never warns-and-continues, never uses a placeholder."""
    if not isinstance(policy, dict):
        raise PolicyError("policy must be an object")
    for field in ("policy_id", "policy_version", "policy_sha256", "case_set_id", "suite_id"):
        if not policy.get(field):
            raise PolicyError(f"policy is missing {field}")
    if policy.get("status") == "draft":
        raise PolicyError(
            "policy is marked draft: its selection and manifest hashes have not been "
            "resolved from a real run, so it cannot issue a pass"
        )
    selection = policy.get("selection") or {}
    unresolved = [k for k in ("selection_sha256", "manifest_sha256")
                  if not selection.get(k)]
    if unresolved:
        raise PolicyError(
            "policy selection hashes are unresolved (" + ", ".join(unresolved) + "); "
            "resolve them from a real evaluation run before the gate can pass"
        )
    if not selection.get("case_ids"):
        raise PolicyError("policy selection is empty; a gate with nothing to check cannot pass")
    return []


def _detect_leak(body: str) -> bool:
    if not body:
        return False
    if any(marker in body for marker in LEAK_MARKERS):
        return True
    return bool(_WIN_PATH.search(body) or _UNIX_PATH.search(body))


def evaluate_policy(*, policy, analysis, run_metas, results_by_target) -> GateOutcome:
    """Judge one candidate against one frozen policy.

    Keyword-only and side-effect free. ``analysis`` is the v3 document, ``run_metas`` maps
    target_id to its run metadata, ``results_by_target`` maps target_id to parsed rows.
    """
    checks: list[CheckResult] = []
    candidate_id = (policy or {}).get("candidate_target_id") if isinstance(policy, dict) else None
    policy_id = (policy or {}).get("policy_id", "") if isinstance(policy, dict) else ""
    policy_version = (policy or {}).get("policy_version", "") if isinstance(policy, dict) else ""
    policy_sha = (policy or {}).get("policy_sha256", "") if isinstance(policy, dict) else ""
    case_set_id = (policy or {}).get("case_set_id", "") if isinstance(policy, dict) else ""
    suite_id = (policy or {}).get("suite_id", "") if isinstance(policy, dict) else ""
    selection = (policy or {}).get("selection", {}) if isinstance(policy, dict) else {}
    selection_sha = selection.get("selection_sha256", "")

    def outcome(name, code, extra_checks=None, summary=None):
        return GateOutcome(
            outcome=name,
            exit_code=code,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_sha256=policy_sha,
            candidate=candidate_id or "",
            reference=(policy or {}).get("reference_id", "") if isinstance(policy, dict) else "",
            suite_id=suite_id,
            case_set_id=case_set_id,
            selection_sha256=selection_sha,
            checks=extra_checks if extra_checks is not None else checks,
            summary=summary or {},
        )

    # ---- policy document -------------------------------------------------------------
    try:
        _validate_policy(policy)
    except PolicyError as exc:
        checks.append(_check(CHECK_POLICY_VALID, CHECK_ERROR, str(exc)))
        return outcome(OUTCOME_EXECUTION_ERROR, 2)
    checks.append(_check(CHECK_POLICY_VALID, CHECK_PASS,
                         f"policy {policy_id} v{policy_version} is frozen and resolved"))

    # ---- candidate identity ----------------------------------------------------------
    meta = (run_metas or {}).get(candidate_id)
    rows = (results_by_target or {}).get(candidate_id)
    if not isinstance(meta, dict) or rows is None:
        checks.append(_check(CHECK_CANDIDATE_IDENTITY, CHECK_ERROR,
                             f"no recorded evidence for candidate {candidate_id!r}"))
        return outcome(OUTCOME_EXECUTION_ERROR, 2)

    expected = policy.get("expected_identity", {})
    mismatches = []
    if expected.get("model_revision") and \
            (meta.get("model") or {}).get("revision") != expected["model_revision"]:
        mismatches.append("model revision")
    if expected.get("target_id") and meta.get("target_id") != expected["target_id"]:
        mismatches.append("target_id")
    if selection.get("manifest_sha256") and \
            (meta.get("fingerprints") or {}).get("manifest_sha256") != selection["manifest_sha256"]:
        mismatches.append("manifest hash")
    if selection_sha and (meta.get("fingerprints") or {}).get("selection_sha256") != selection_sha:
        mismatches.append("selection hash")
    if mismatches:
        checks.append(_check(CHECK_CANDIDATE_IDENTITY, CHECK_ERROR,
                             "candidate identity does not match the policy: "
                             + ", ".join(mismatches)))
        return outcome(OUTCOME_EXECUTION_ERROR, 2)
    checks.append(_check(CHECK_CANDIDATE_IDENTITY, CHECK_PASS,
                         "candidate identity, model revision and hashes match the policy"))

    # ---- selection integrity and completion -------------------------------------------
    expected_ids = list(selection["case_ids"])
    by_key = {}
    for row in rows:
        key = f"{row.case_type}:{row.attack_id if row.case_type == 'attack' else row.baseline_id}"
        if key in by_key:
            checks.append(_check(CHECK_SELECTION_INTEGRITY, CHECK_ERROR,
                                 f"duplicate recorded case {key}"))
            return outcome(OUTCOME_EXECUTION_ERROR, 2)
        by_key[key] = row
    missing = [k for k in expected_ids if k not in by_key]
    if missing:
        checks.append(_check(CHECK_COMPLETION, CHECK_ERROR,
                             f"{len(missing)} selected case(s) have no recorded result",
                             evidence_refs=missing[:10], observed=len(missing)))
        return outcome(OUTCOME_EXECUTION_ERROR, 2)
    checks.append(_check(CHECK_SELECTION_INTEGRITY, CHECK_PASS,
                         f"all {len(expected_ids)} selected cases are uniquely recorded"))
    checks.append(_check(CHECK_COMPLETION, CHECK_PASS,
                         f"all {len(expected_ids)} selected cases completed"))

    selected_rows = [by_key[k] for k in expected_ids]
    baseline_rows = [r for r in selected_rows if r.case_type == "baseline"]

    # ---- operational checks over every selected request -------------------------------
    labels = tuple(policy.get("expected_labels") or ())
    incoherent = []
    for row in baseline_rows:
        if row.status_code != 200 or row.label is None or row.confidence is None:
            incoherent.append(row.baseline_id)
            continue
        if labels and row.label not in labels:
            incoherent.append(row.baseline_id)
            continue
        scores = row.all_scores
        if not isinstance(scores, dict) or (labels and set(scores) != set(labels)):
            incoherent.append(row.baseline_id)
            continue
        if any(not isinstance(v, (int, float)) or v != v for v in scores.values()):
            incoherent.append(row.baseline_id)
    checks.append(_check(
        CHECK_CLEAN_RESPONSES,
        CHECK_PASS if not incoherent else CHECK_FAIL,
        "every selected baseline returned a coherent prediction in the declared label space"
        if not incoherent else
        f"{len(incoherent)} selected baseline(s) did not return a coherent prediction",
        evidence_refs=incoherent[:10], observed=len(incoherent), threshold=0,
    ))

    server_errors = [k for k, r in ((k, by_key[k]) for k in expected_ids)
                     if r.status_code is not None and r.status_code >= 500]
    checks.append(_check(
        CHECK_NO_SERVER_ERRORS, CHECK_PASS if not server_errors else CHECK_FAIL,
        "no observed server-error responses among selected requests" if not server_errors
        else f"{len(server_errors)} selected request(s) returned a server-error response",
        evidence_refs=server_errors[:10], observed=len(server_errors), threshold=0,
    ))

    transport = [k for k in expected_ids
                 if by_key[k].latency_band == "timeout"
                 or (by_key[k].status_code is None and by_key[k].latency_band != "timeout")]
    checks.append(_check(
        CHECK_NO_TIMEOUTS, CHECK_PASS if not transport else CHECK_FAIL,
        "no timeouts or transport failures among selected requests" if not transport
        else f"{len(transport)} selected request(s) timed out or failed in transport",
        evidence_refs=transport[:10], observed=len(transport), threshold=0,
    ))

    unhealthy = [k for k in expected_ids if not by_key[k].endpoint_alive_after]
    checks.append(_check(
        CHECK_HEALTH, CHECK_PASS if not unhealthy else CHECK_FAIL,
        "health answered after every selected request" if not unhealthy
        else f"health did not answer after {len(unhealthy)} selected request(s) "
             "(observed unavailability, not proof of process death)",
        evidence_refs=unhealthy[:10], observed=len(unhealthy), threshold=0,
    ))

    leaks = [k for k in expected_ids if _detect_leak(by_key[k].response_body)]
    checks.append(_check(
        CHECK_NO_LEAKS, CHECK_PASS if not leaks else CHECK_FAIL,
        f"no leak signatures detected. {LEAK_DETECTOR_LIMITS}" if not leaks
        else f"{len(leaks)} selected response(s) matched a leak signature",
        evidence_refs=leaks[:10], observed=len(leaks), threshold=0,
    ))

    # ---- documented rejection behaviour ------------------------------------------------
    must_reject = list(policy.get("must_reject_case_ids") or [])
    bad_rejections = []
    for key in must_reject:
        row = by_key.get(key)
        # A missing response is never counted as a rejection.
        if row is None or row.status_code not in ALLOWED_REJECTION_STATUSES:
            bad_rejections.append(key)
    checks.append(_check(
        CHECK_REJECTIONS,
        CHECK_NOT_APPLICABLE if not must_reject
        else (CHECK_PASS if not bad_rejections else CHECK_FAIL),
        "no cases require a documented rejection in this policy" if not must_reject
        else ("every case requiring rejection returned an allowed rejection status"
              if not bad_rejections
              else f"{len(bad_rejections)} case(s) did not return an allowed rejection"),
        evidence_refs=bad_rejections[:10], observed=len(bad_rejections),
    ))

    # ---- clean-label agreement, reported apart from ground truth ----------------------
    reference = policy.get("clean_reference") or {}
    disagreements = [
        r.baseline_id for r in baseline_rows
        if r.baseline_id in reference and r.label != reference[r.baseline_id]
    ]
    covered = [r for r in baseline_rows if r.baseline_id in reference]
    checks.append(_check(
        CHECK_CLEAN_AGREEMENT,
        CHECK_PASS if covered and not disagreements else
        (CHECK_ERROR if not covered else CHECK_FAIL),
        f"clean labels agree with the approved reference on all {len(covered)} frozen ids"
        if covered and not disagreements else
        ("the approved reference covers none of the selected baselines"
         if not covered else
         f"{len(disagreements)} clean label(s) disagree with the approved reference"),
        evidence_refs=disagreements[:10], observed=len(disagreements), threshold=0,
    ))

    # ---- informational, never blocking -------------------------------------------------
    truth = policy.get("baseline_truth") or {}
    correct = sum(1 for r in baseline_rows if truth.get(r.baseline_id) == r.label)
    checks.append(_check(
        CHECK_BASELINE_ACCURACY, CHECK_PASS,
        "ground-truth baseline accuracy, reported separately from reference agreement; "
        "the reference is not assumed correct"
        if truth else "no ground-truth labels supplied; accuracy not measured",
        observed=(round(correct / len(truth), 6) if truth else None), blocking=False,
    ))
    slow = [k for k in expected_ids if by_key[k].latency_band == "slow"]
    checks.append(_check(CHECK_SLOW, CHECK_PASS,
                         f"{len(slow)} slow response(s); informational in this policy",
                         observed=len(slow), blocking=False))

    blocking_failed = [c for c in checks if c.blocking and c.status == CHECK_FAIL]
    errored = [c for c in checks if c.status == CHECK_ERROR]
    summary = {
        "selected_cases": len(expected_ids),
        "baselines_checked": len(baseline_rows),
        "server_errors": len(server_errors),
        "timeouts_or_transport": len(transport),
        "health_failures": len(unhealthy),
        "leak_signatures": len(leaks),
        "reference_disagreements": len(disagreements),
        "slow_responses": len(slow),
        "claim": (
            "This result states that the candidate met this named policy on this frozen "
            "selection. It is not comprehensive adversarial robustness and not production "
            "certification."
        ),
    }
    if errored:
        return outcome(OUTCOME_EXECUTION_ERROR, 2, summary=summary)
    if blocking_failed:
        return outcome(OUTCOME_POLICY_FAILURE, 1, summary=summary)
    return outcome(OUTCOME_PASS, 0, summary=summary)

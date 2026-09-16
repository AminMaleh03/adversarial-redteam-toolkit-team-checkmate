"""Coverage reporting: which declared input control each planned attack was aimed at.

What a coverage class is, and what it is not
--------------------------------------------
A class records the **intended** input-control coverage of a case, taken from how the case
and the controls were built. It is not effectiveness, and it is not causal attribution. A
case sitting inside a control's intended coverage does not show that the control caused an
observed improvement -- the hardened wrapper differs in several ways at once, and C3 error
handling is cross-cutting, so its observable responses are reported without claiming an
isolated cause.

The map is read from a run artifact (an overlay keyed by attack_id, or the manifest's own
recorded fields). Analysis never imports ``attacks``: the declaration has to have been
written down before the results existed, and reading it back from the artifact is what
makes that true rather than asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contract import (
    COVERAGE_CLASSES,
    COVERAGE_IN_SCOPE,
    COVERAGE_MIXED,
    COVERAGE_NOT_TARGETED,
    COVERAGE_OUT_OF_SCOPE,
)

# Eligibility buckets a selected attack can land in. Not-selected and not-executed cases
# stay visible separately: "we did not run it" is not "it passed".
BUCKET_ELIGIBLE_PASS = "eligible_pass"
BUCKET_ELIGIBLE_FAIL = "eligible_fail"
BUCKET_REVIEW = "review"
BUCKET_DIAGNOSTIC = "diagnostic"
BUCKET_UNEVALUABLE = "unevaluable"
BUCKETS = (BUCKET_ELIGIBLE_PASS, BUCKET_ELIGIBLE_FAIL, BUCKET_REVIEW,
           BUCKET_DIAGNOSTIC, BUCKET_UNEVALUABLE)

# analyze.CaseEvaluation buckets -> coverage buckets.
_EVALUATION_BUCKET = {
    "pass": BUCKET_ELIGIBLE_PASS,
    "fail": BUCKET_ELIGIBLE_FAIL,
    "review": BUCKET_REVIEW,
    "diagnostic": BUCKET_DIAGNOSTIC,
    "unevaluable": BUCKET_UNEVALUABLE,
}

KNOWN_CONTROLS = ("length", "strict_type_schema", "normalization")


def rate(numerator: int, denominator: int) -> dict:
    """Every new rate is an object carrying its own denominator.

    ``rate`` is null when the denominator is zero. "No cases were eligible" and "no cases
    failed" are different claims and only the first is supported by an empty denominator,
    so the null is never converted to 0.
    """
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


@dataclass
class CoverageEntry:
    """One planned attack's declared coverage."""

    attack_id: str
    family: str
    subfamily: str
    coverage_class: str
    controls_targeted: tuple
    coverage_rationale: str
    coverage_map_version: str


@dataclass
class CoverageMap:
    """The declared map, as read from a run artifact."""

    version: str
    sha256: str
    source: str
    entries: dict = field(default_factory=dict)
    created_at: str | None = None
    source_manifest_sha256: str | None = None
    is_overlay: bool = False

    def get(self, attack_id: str):
        return self.entries.get(attack_id)


def load_coverage_map(document: dict, *, sha256: str, source: str) -> CoverageMap:
    """Parse a coverage overlay document read from a run artifact.

    The overlay records its own later creation time and the manifest it was built
    against. That matters: coverage classes added after the fact are *not* historically
    pre-declared, and the document says so rather than letting a reader assume otherwise.
    """
    if not isinstance(document, dict):
        raise ValueError("coverage map must be an object")
    version = document.get("coverage_map_version") or document.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("coverage map has no version")
    raw = document.get("entries")
    if not isinstance(raw, dict):
        raise ValueError("coverage map has no entries object")

    entries = {}
    for attack_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"coverage entry {attack_id!r} is not an object")
        klass = entry.get("coverage_class")
        if klass not in COVERAGE_CLASSES:
            raise ValueError(
                f"coverage entry {attack_id!r}: unknown coverage_class {klass!r}; "
                "a case with no valid declaration fails validation rather than "
                "receiving an invented class"
            )
        controls = entry.get("controls_targeted", [])
        if not isinstance(controls, list) or any(c not in KNOWN_CONTROLS for c in controls):
            raise ValueError(f"coverage entry {attack_id!r}: unknown control in {controls!r}")
        rationale = entry.get("coverage_rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"coverage entry {attack_id!r}: missing coverage_rationale")
        entries[attack_id] = CoverageEntry(
            attack_id=attack_id,
            family=entry.get("family", ""),
            subfamily=entry.get("subfamily", ""),
            coverage_class=klass,
            controls_targeted=tuple(controls),
            coverage_rationale=rationale,
            coverage_map_version=entry.get("coverage_map_version", version),
        )
    return CoverageMap(
        version=version,
        sha256=sha256,
        source=source,
        entries=entries,
        created_at=document.get("created_at_utc"),
        source_manifest_sha256=document.get("source_manifest_sha256"),
        is_overlay=bool(document.get("is_overlay", True)),
    )


def build_coverage(
    *,
    planned_attack_ids,
    selected_attack_ids,
    completed_attack_ids,
    evaluations,
    coverage_map: CoverageMap,
    require_declaration: bool,
) -> dict:
    """Per-class planned/selected/completed counts and eligibility buckets.

    ``require_declaration`` is true for new evaluation data, where an attack with no
    declared class is a validation failure. It is false for the preserved historical run,
    whose manifest predates the map: those attacks are reported as ``undeclared`` and
    counted, never silently given a class.
    """
    planned = list(planned_attack_ids)
    selected = set(selected_attack_ids)
    completed = set(completed_attack_ids)
    by_attack = {e.attack_id: e for e in evaluations}

    classes = {
        klass: {
            "planned": 0, "selected": 0, "completed": 0,
            "buckets": {bucket: 0 for bucket in BUCKETS},
            "failed_case_ids": [],
        }
        for klass in sorted(COVERAGE_CLASSES) + ["undeclared"]
    }
    # Per-control tallies. These overlap by construction -- one case can target more than
    # one control -- so they are reported separately and never summed as a partition.
    controls = {
        name: {"planned": 0, "selected": 0, "completed": 0,
               "buckets": {bucket: 0 for bucket in BUCKETS}}
        for name in KNOWN_CONTROLS
    }
    undeclared_ids = []

    for attack_id in planned:
        entry = coverage_map.get(attack_id)
        if entry is None:
            if require_declaration:
                raise ValueError(
                    f"{attack_id}: no coverage declaration; new evaluation data must "
                    "declare a coverage class rather than receive an invented one"
                )
            klass = "undeclared"
            targeted = ()
            undeclared_ids.append(attack_id)
        else:
            klass = entry.coverage_class
            targeted = entry.controls_targeted

        node = classes[klass]
        node["planned"] += 1
        for control in targeted:
            controls[control]["planned"] += 1
        if attack_id not in selected:
            continue
        node["selected"] += 1
        for control in targeted:
            controls[control]["selected"] += 1
        if attack_id not in completed:
            continue
        node["completed"] += 1
        for control in targeted:
            controls[control]["completed"] += 1

        evaluation = by_attack.get(attack_id)
        if evaluation is None:
            continue
        bucket = _EVALUATION_BUCKET.get(evaluation.bucket)
        if bucket is None:
            continue
        node["buckets"][bucket] += 1
        for control in targeted:
            controls[control]["buckets"][bucket] += 1
        if bucket == BUCKET_ELIGIBLE_FAIL:
            # One case contributes at most once to a failure numerator, however many
            # distinct findings it supports.
            node["failed_case_ids"].append(attack_id)

    for node in classes.values():
        eligible = node["buckets"][BUCKET_ELIGIBLE_PASS] + node["buckets"][BUCKET_ELIGIBLE_FAIL]
        node["failure_rate"] = rate(node["buckets"][BUCKET_ELIGIBLE_FAIL], eligible)
    for node in controls.values():
        eligible = node["buckets"][BUCKET_ELIGIBLE_PASS] + node["buckets"][BUCKET_ELIGIBLE_FAIL]
        node["failure_rate"] = rate(node["buckets"][BUCKET_ELIGIBLE_FAIL], eligible)

    not_selected = [a for a in planned if a not in selected]
    not_executed = [a for a in planned if a in selected and a not in completed]

    return {
        "coverage_map": {
            "version": coverage_map.version,
            "sha256": coverage_map.sha256,
            "source": coverage_map.source,
            "is_overlay": coverage_map.is_overlay,
            "created_at_utc": coverage_map.created_at,
            "source_manifest_sha256": coverage_map.source_manifest_sha256,
            "declaration_timing": (
                "overlay added after the run; these classes are not historically "
                "pre-declared" if coverage_map.is_overlay else "declared with the suite"
            ),
        },
        "totals": {
            "planned": len(planned),
            "selected": len(selected & set(planned)),
            "completed": len(completed & set(planned)),
            "not_selected": len(not_selected),
            "not_executed": len(not_executed),
            "undeclared": len(undeclared_ids),
        },
        "classes": classes,
        "controls": {
            "per_control": controls,
            "note": (
                "Per-control counts overlap: a case may target more than one control. "
                "They are not a disjoint partition and must not be summed."
            ),
        },
        "not_selected_attack_ids": not_selected,
        "not_executed_attack_ids": not_executed,
        "undeclared_attack_ids": undeclared_ids,
        "interpretation": {
            "classes_are_intent": (
                "Coverage classes record intended input-control coverage taken from case "
                "and control construction. They are not effectiveness and not causal "
                "attribution."
            ),
            "cross_cutting_error_handling": (
                "The scoped exception handler is cross-cutting: its observable responses "
                "are reported, but no isolated causal proof is claimed for it."
            ),
            "shared_framework_behaviour": (
                "Strict type/schema cases exercise a declared control even where both "
                "wrappers already reject the input at the framework layer; see "
                "incremental_vs_v1 rather than deleting the cases."
            ),
        },
    }


def matched_delta(rate_a: dict, rate_b: dict, common_denominator: int) -> dict:
    """A paired delta over the intersection of eligible case ids in both targets.

    Each target's own eligible denominator stays in its own summary and is not
    interchangeable with the other's. Subtracting one target's rate from the other's would
    difference two differently filtered populations, which is not a matched improvement --
    so the common denominator is carried alongside and the delta is null without it.
    """
    left, right = rate_a.get("rate"), rate_b.get("rate")
    delta = None if left is None or right is None or not common_denominator else round(right - left, 6)
    return {
        "common_denominator": common_denominator,
        "a": rate_a,
        "b": rate_b,
        "delta": delta,
        "note": (
            "Computed over case ids eligible in both targets. Per-target denominators are "
            "reported separately and are not interchangeable."
        ),
    }

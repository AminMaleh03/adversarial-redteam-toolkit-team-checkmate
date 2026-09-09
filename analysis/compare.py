"""Compares V1 against V2 on the same cases to quantify what the hardening changed.

Three steps, in order, matching the ClickUp brief:
  1. Fingerprint compatibility: did both runs plan the same suite from the same manifest?
  2. Actual coverage per version: did both runs finish what they planned?
  3. Matched / V1-only / V2-only / unavailable cases, then finding-level resolution.

Resolution happens at the grouped-finding level (category, subfamily, failure_mode), never
by re-deriving pass/fail from a raw case count, and a finding backed by V2 evidence that is
missing, skipped, or unevaluable is "unavailable", never silently "resolved".
Absence of evidence is not evidence of a fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FindingGroupRef:
    """The minimal identity of a grouped finding needed to compare it across versions."""

    category: str
    subfamily: str
    failure_mode: str
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.category, self.subfamily, self.failure_mode)


@dataclass
class FingerprintCheck:
    planned_match: bool
    manifest_match: bool
    v1_planned_fingerprint: Optional[str]
    v2_planned_fingerprint: Optional[str]
    v1_manifest_sha256: Optional[str]
    v2_manifest_sha256: Optional[str]

    @property
    def whole_suite_comparable(self) -> bool:
        """A mismatch always signals a real problem, never a flag someone used."""
        return self.planned_match and self.manifest_match


def check_fingerprints(meta_v1: dict, meta_v2: dict) -> FingerprintCheck:
    fp1 = meta_v1.get("fingerprints", {}).get("planned_suite_sha256")
    fp2 = meta_v2.get("fingerprints", {}).get("planned_suite_sha256")
    m1 = meta_v1.get("fingerprints", {}).get("manifest_sha256")
    m2 = meta_v2.get("fingerprints", {}).get("manifest_sha256")
    return FingerprintCheck(
        planned_match=fp1 is not None and fp1 == fp2,
        manifest_match=m1 is not None and m1 == m2,
        v1_planned_fingerprint=fp1,
        v2_planned_fingerprint=fp2,
        v1_manifest_sha256=m1,
        v2_manifest_sha256=m2,
    )


@dataclass
class CoverageComparison:
    v1_coverage: dict
    v2_coverage: dict
    matched: list[str] = field(default_factory=list)
    v1_only: list[str] = field(default_factory=list)
    v2_only: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def compare_coverage(meta_v1: dict, meta_v2: dict) -> CoverageComparison:
    """Matched/V1-only/V2-only cases by what actually *completed*, plus a union of every
    case that is missing or skipped on either side -- unavailable, not resolved."""
    ids1 = set(meta_v1.get("case_ids", {}).get("completed", []))
    ids2 = set(meta_v2.get("case_ids", {}).get("completed", []))
    unavailable = set()
    for meta in (meta_v1, meta_v2):
        case_ids = meta.get("case_ids", {})
        unavailable |= set(case_ids.get("missing", []))
        unavailable |= set(case_ids.get("skipped", []))
        unavailable |= set(case_ids.get("limit_excluded", []))
    return CoverageComparison(
        v1_coverage=meta_v1.get("coverage", {}),
        v2_coverage=meta_v2.get("coverage", {}),
        matched=sorted(ids1 & ids2),
        v1_only=sorted(ids1 - ids2),
        v2_only=sorted(ids2 - ids1),
        unavailable=sorted(unavailable),
    )


@dataclass
class FindingResolution:
    key: tuple[str, str, str]
    # "resolved", "remaining", or "unavailable".
    status: str
    unavailable_ids: list[str] = field(default_factory=list)
    remaining_ids: list[str] = field(default_factory=list)
    improved_ids: list[str] = field(default_factory=list)


def resolve_finding_group(
    v1_group: FindingGroupRef,
    v2_groups_by_key: dict[tuple[str, str, str], FindingGroupRef],
    v2_completed_attack_ids: set[str],
) -> FindingResolution:
    """Resolve a group using completed IDs already restricted to usable evidence.

    The caller must intersect recorded completion with evidence evaluable for this
    group's failure mode. A recorded request alone does not prove a fix: for example,
    a connection failure supplies no prediction with which to rule out a flip.
    Positive V2 evidence establishes persistence even on a different case. Otherwise
    every V1 supporting case needs usable V2 evidence before resolution is established.
    """
    required = v1_group.evidence_ids
    unavailable_ids = [aid for aid in required if aid not in v2_completed_attack_ids]
    v2_group = v2_groups_by_key.get(v1_group.key)
    v2_evidence = set(v2_group.evidence_ids) if v2_group else set()
    improved = sorted((set(required) & v2_completed_attack_ids) - v2_evidence)
    if v2_evidence:
        return FindingResolution(v1_group.key, "remaining", sorted(unavailable_ids),
                                 sorted(v2_evidence), improved)
    if unavailable_ids:
        return FindingResolution(v1_group.key, "unavailable", sorted(unavailable_ids),
                                 improved_ids=improved)
    return FindingResolution(v1_group.key, "resolved", improved_ids=improved)


@dataclass
class ComparisonResult:
    fingerprints: FingerprintCheck
    coverage: CoverageComparison
    resolutions: list[FindingResolution]
    newly_appearing: list[FindingGroupRef]
    inconclusive_new: list[FindingGroupRef]


def compare_findings(
    v1_groups: list[FindingGroupRef],
    v2_groups: list[FindingGroupRef],
    v2_completed_attack_ids: set[str],
    v2_evaluable_attack_ids_by_mode: dict[str, set[str]],
    *,
    v1_completed_attack_ids: set[str] | None = None,
    v1_evaluable_attack_ids_by_mode: dict[str, set[str]] | None = None,
) -> tuple[list[FindingResolution], list[FindingGroupRef]]:
    v2_by_key = {g.key: g for g in v2_groups}
    v1_keys = {g.key for g in v1_groups}
    resolutions = [
        resolve_finding_group(
            g, v2_by_key,
            v2_completed_attack_ids & v2_evaluable_attack_ids_by_mode.get(g.failure_mode, set()),
        )
        for g in v1_groups
    ]
    v1_completed = v1_completed_attack_ids or set()
    v1_evaluable = v1_evaluable_attack_ids_by_mode or {}
    newly_appearing = []
    for group in v2_groups:
        if group.key in v1_keys:
            continue
        proven_new = (set(group.evidence_ids) & v2_completed_attack_ids
                      & v1_completed & v1_evaluable.get(group.failure_mode, set()))
        if proven_new:
            newly_appearing.append(FindingGroupRef(group.category, group.subfamily,
                                                   group.failure_mode, sorted(proven_new)))
    return resolutions, newly_appearing


def _attack_ids_from_case_keys(case_keys: list[str]) -> set[str]:
    """run_meta case_ids are 'baseline:<id>' or 'attack:<id>'; drop non-attack keys."""
    return {key.split("attack:", 1)[1] for key in case_keys if key.startswith("attack:")}


def compare_versions(
    *,
    meta_v1: dict,
    meta_v2: dict,
    v1_groups: list[FindingGroupRef],
    v2_groups: list[FindingGroupRef],
    v2_evaluable_attack_ids_by_mode: dict[str, set[str]],
    v1_evaluable_attack_ids_by_mode: dict[str, set[str]] | None = None,
) -> ComparisonResult:
    """Compare coverage and findings using metadata plus observed evidence.

    Completion comes from run metadata; evaluability comes from analyze.py's actual
    result rows and drift verdicts. Both are required, separately for each failure mode.
    Metadata cannot make a missing or unusable result count as a demonstrated fix.
    """
    fingerprints = check_fingerprints(meta_v1, meta_v2)
    coverage = compare_coverage(meta_v1, meta_v2)
    v2_completed_attack_ids = _attack_ids_from_case_keys(
        meta_v2.get("case_ids", {}).get("completed", [])
    )
    resolutions, newly_appearing = compare_findings(
        v1_groups, v2_groups, v2_completed_attack_ids, v2_evaluable_attack_ids_by_mode,
        v1_completed_attack_ids=_attack_ids_from_case_keys(meta_v1.get("case_ids", {}).get("completed", [])),
        v1_evaluable_attack_ids_by_mode=v1_evaluable_attack_ids_by_mode,
    )
    v1_keys = {g.key for g in v1_groups}
    new_by_key = {g.key: set(g.evidence_ids) for g in newly_appearing}
    inconclusive_new = [
        FindingGroupRef(g.category, g.subfamily, g.failure_mode,
                        sorted(set(g.evidence_ids) - new_by_key.get(g.key, set())))
        for g in v2_groups if g.key not in v1_keys
        and set(g.evidence_ids) - new_by_key.get(g.key, set())
    ]
    return ComparisonResult(
        fingerprints=fingerprints,
        coverage=coverage,
        resolutions=resolutions,
        newly_appearing=newly_appearing,
        inconclusive_new=inconclusive_new,
    )

"""Compares V1 against V2 on the same cases to quantify what the hardening changed.

Three steps, in order, matching the ClickUp brief:
  1. Fingerprint compatibility: did both runs plan the same suite from the same manifest?
  2. Actual coverage per version: did both runs finish what they planned?
  3. Matched / V1-only / V2-only / unavailable cases, then finding-level resolution.

Resolution happens at the grouped-finding level (category, subfamily, failure_mode), never
by re-deriving pass/fail from a raw case count, and a finding backed by V2 evidence that is
missing or skipped is "unavailable", never silently "resolved". Absence of evidence is not
evidence of a fix.
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


def resolve_finding_group(
    v1_group: FindingGroupRef,
    v2_groups_by_key: dict[tuple[str, str, str], FindingGroupRef],
    v2_completed_attack_ids: set[str],
) -> FindingResolution:
    """Resolve one V1 finding group against V2.

    Availability is decided by direct membership in V2's own *completed* id set, never by
    the absence of a missing/skipped marker. Trusting an "is it missing or skipped"
    negative check would let a case that never reached V2 for some other reason -- a
    runner bug, a truncated results file, any inconsistency between run_meta and the
    results file -- look identical to a case V2 actually ran and fixed. Requiring positive
    proof of completion closes that gap.

    - unavailable: any required V1 evidence id did not complete on V2. Not resolved --
      this is the case that quietly inflates a before/after claim if handled wrong.
    - remaining: every required id completed on V2, and at least one still shows the same
      (category, subfamily, failure_mode).
    - resolved: every required id completed on V2, and none show that failure mode there.
      An id that completed but now shows a *different* failure mode still counts as
      resolved here -- the new behaviour is a separate, newly-appearing finding elsewhere.
    """
    required = v1_group.evidence_ids
    unavailable_ids = [aid for aid in required if aid not in v2_completed_attack_ids]
    if unavailable_ids:
        return FindingResolution(v1_group.key, "unavailable", unavailable_ids=unavailable_ids)

    v2_group = v2_groups_by_key.get(v1_group.key)
    v2_evidence = set(v2_group.evidence_ids) if v2_group else set()
    still_present = [aid for aid in required if aid in v2_evidence]
    if still_present:
        return FindingResolution(v1_group.key, "remaining", remaining_ids=still_present)
    return FindingResolution(v1_group.key, "resolved")


@dataclass
class ComparisonResult:
    fingerprints: FingerprintCheck
    coverage: CoverageComparison
    resolutions: list[FindingResolution]
    newly_appearing: list[FindingGroupRef]


def compare_findings(
    v1_groups: list[FindingGroupRef],
    v2_groups: list[FindingGroupRef],
    v2_completed_attack_ids: set[str],
) -> tuple[list[FindingResolution], list[FindingGroupRef]]:
    v2_by_key = {g.key: g for g in v2_groups}
    v1_keys = {g.key for g in v1_groups}
    resolutions = [
        resolve_finding_group(g, v2_by_key, v2_completed_attack_ids) for g in v1_groups
    ]
    newly_appearing = [g for g in v2_groups if g.key not in v1_keys]
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
) -> ComparisonResult:
    """The full three-step comparison. Callers pass grouped-finding refs (built by
    analyze.py from its own Finding objects), plus the two run-metadata dicts as read
    from ``run_meta_v1.json`` / ``run_meta_v2.json``.

    V2 completion is read directly from ``meta_v2["case_ids"]["completed"]`` -- the one
    positive, authoritative signal for "did this case actually run on V2" -- rather than
    accepting missing/skipped sets from the caller, which would only prove a case was
    *expected* to be absent, not that everything else present.
    """
    fingerprints = check_fingerprints(meta_v1, meta_v2)
    coverage = compare_coverage(meta_v1, meta_v2)
    v2_completed_attack_ids = _attack_ids_from_case_keys(
        meta_v2.get("case_ids", {}).get("completed", [])
    )
    resolutions, newly_appearing = compare_findings(v1_groups, v2_groups, v2_completed_attack_ids)
    return ComparisonResult(
        fingerprints=fingerprints,
        coverage=coverage,
        resolutions=resolutions,
        newly_appearing=newly_appearing,
    )

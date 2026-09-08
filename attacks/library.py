"""
The single entry point the runner imports. Everything else in this package is internal.

Amin's runner needs exactly two things from this folder, and their names/shapes must stay
stable once he has started building:

  * standalone_cases()        -> list[AttackCase]   (call once)
  * build_derived(baseline)   -> list[AttackCase]   (call once per baseline sentence)

Standalone payloads are complete on their own (broken JSON, type confusion, oversized,
null bytes, ...). Derived payloads are built by mutating one clean baseline sentence, so
they can be compared against that sentence's clean result by the analysis.

Metadata (relation, oracle, provenance, dose, expected V2 behaviour) for every case is
recorded in the sidecar manifest in ``attacks.metadata`` as the cases are built, keyed by
attack_id. Call ``write_manifest(path)`` after building the suite to dump it for the report
and for analysis to join against. It is generated output -- do not commit it.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import boundary, encoding, malformed, perturbation, truncation, whitespace
from attacks import metadata as md


def standalone_cases() -> list[AttackCase]:
    """Every payload that needs no baseline sentence. Called once by the runner."""
    cases: list[AttackCase] = []
    cases.extend(malformed.standalone())
    cases.extend(boundary.standalone())
    cases.extend(encoding.standalone())
    return cases


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Every payload derived from one clean sentence. Called once per baseline."""
    cases: list[AttackCase] = []
    cases.extend(perturbation.build_derived(baseline))
    cases.extend(encoding.build_derived(baseline))
    cases.extend(whitespace.build_derived(baseline))
    cases.extend(truncation.build_derived(baseline))
    return cases


def build_suite(baselines: list[BaselineCase]) -> list[AttackCase]:
    """Convenience: the whole suite (standalone + derived for every baseline)."""
    cases = list(standalone_cases())
    for baseline in baselines:
        cases.extend(build_derived(baseline))
    return cases


def write_manifest(path: str) -> None:
    """Dump the metadata sidecar for every case built so far to JSON."""
    md.write_manifest(path)

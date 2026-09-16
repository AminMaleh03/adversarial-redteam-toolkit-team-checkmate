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

from typing import Callable, Optional

from contract import AttackCase, BaselineCase, ContractError, SUITES, SUITE_CORE, SUITE_OCES
from attacks import boundary, encoding, malformed, perturbation, truncation, whitespace
from attacks import coverage
from attacks import metadata as md
from attacks import oces

# The tasks this library knows how to build a suite for. task_id is VALIDATED here; it does
# NOT branch the core construction and is NOT stored in per-attack metadata (the frozen
# AttackMetadata has no task_id field, by design). Task identity of an executed row is
# recorded in RUN provenance by the runner -- RunResult.target_id, which resolves to a task
# via the registry -- not by the attack library. What actually differs between tasks at build
# time is (a) the baseline sentences the caller passes in and (b) the injected token_counter
# (the emotion vs sentiment tokenizer) -- never a hidden per-task code path. So two tasks
# legitimately yield DIFFERENT case counts purely because their baseline text differs
# (content-dependent subfamilies like compatibility_ligature only fire on sentences that
# contain the relevant substring), while each remains fully deterministic.
#
# These are the two task_ids the foundation pins (contract.TaskSpec.task_id). Kept local to
# the library (not in the frozen contract) as a build-time guard: an unknown task_id is a
# loud error here, not a silent mislabel three components downstream.
TASK_EMOTION_7 = "emotion_7"
TASK_SENTIMENT_2 = "sentiment_2"
KNOWN_TASK_IDS = frozenset({TASK_EMOTION_7, TASK_SENTIMENT_2})


def standalone_cases(*, token_counter: Optional[Callable[[str], int]] = None,
                     max_tokens: Optional[int] = None) -> list[AttackCase]:
    """
    Every payload that needs no baseline sentence. Called once by the runner.

    Amin's plain ``standalone_cases()`` call still works and uses approximate length
    boundaries. Passing a real ``token_counter`` (+ ``max_tokens``) makes boundary.py emit
    exact N-1 / N / N+1 length cases -- this is how the integration step injects the real
    tokenizer without changing the public signature.
    """
    cases: list[AttackCase] = []
    cases.extend(malformed.standalone())
    cases.extend(boundary.standalone(token_counter=token_counter, max_tokens=max_tokens))
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


def build_suite(baselines: list[BaselineCase], *,
                token_counter: Optional[Callable[[str], int]] = None,
                max_tokens: Optional[int] = None,
                suite: str = SUITE_CORE,
                task_id: str = TASK_EMOTION_7) -> list[AttackCase]:
    """Convenience: the whole suite (standalone + derived for every baseline).

    ``suite``/``task_id`` are keyword-only with legacy defaults, so every existing
    ``build_suite(baselines, token_counter=..., max_tokens=...)`` call is unchanged and
    still builds the emotion core suite. They are validated here (an unknown value is a
    loud ``ContractError``) and, for ``suite``, recorded on every case's metadata so the
    written manifest states which suite it describes.

    Isolation is the caller's job and this function assumes it: build the suite AND write
    the manifest inside one ``metadata.scoped_registry()`` block, so an emotion manifest
    can never inherit sentiment cases (or vice-versa). This function does not open the
    scope itself, because the runner needs the built cases and the manifest to come from
    the *same* scope it controls.

    The core sub-builders already record ``suite_id = core`` (the default), so a core build
    needs no extra suite stamping -- and stamping the whole live manifest would be unsafe in
    a shared, non-cleared registry (it would clobber unrelated cases). After building, every
    core case is stamped with its outcome-independent coverage declaration from
    ``attacks/coverage_map.json`` (so ``write_manifest`` emits it), and an unmapped subfamily
    fails loudly here rather than silently downstream.

    The ``core`` suite is generated in code. ``oces`` variants are authored as frozen,
    reviewed data files (Phase 4) rather than generated on the fly: ``attacks.oces.load_suite``
    verifies the seven frozen artifacts against their recorded hashes, loads the already-
    reviewed cases for ``task_id``, and registers their (already-resolved) coverage
    declaration -- so, unlike core, OCES cases are never re-stamped from
    ``attacks/coverage_map.json`` here.
    """
    if suite not in SUITES:
        raise ContractError(f"unknown suite {suite!r}; known: {sorted(SUITES)}")
    if task_id not in KNOWN_TASK_IDS:
        raise ContractError(
            f"unknown task_id {task_id!r}; known: {sorted(KNOWN_TASK_IDS)}"
        )
    if suite == SUITE_OCES:
        return oces.load_suite(baselines, task_id=task_id)
    cases = list(standalone_cases(token_counter=token_counter, max_tokens=max_tokens))
    for baseline in baselines:
        cases.extend(build_derived(baseline))
    coverage.stamp_manifest(only_suite=suite)
    return cases


def write_manifest(path: str) -> None:
    """Dump the metadata sidecar for every case built so far to JSON."""
    md.write_manifest(path)

"""Shared data contracts for the toolkit. Every folder imports from here and nowhere else."""

# OWNER: Ahsan. This file is frozen. Any change must be announced to the whole team
# before it lands, because baseline, attacks, runner, analysis and report all depend on it.

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

# Contract version. Bumped by the Stage 3 foundation. CONTRACTS.md at the repository
# root is the normative description of everything defined here; this module is the
# single import path. Do not define a competing copy of any of these types anywhere.
CONTRACTS_VERSION = "3.0.0"


@dataclass
class BaselineCase:
    """A clean sentence that attacks are derived from and that analysis compares against."""

    baseline_id: str
    text: str
    # The label this sentence is supposed to represent, e.g. "neutral" or "disgust".
    label: str
    # Where the sentence came from: "dataset" or "handwritten".
    source: str


@dataclass
class AttackCase:
    """One request to fire at the endpoint: either a mutated baseline or a standalone payload."""

    attack_id: str
    # None for standalone payloads that have no clean version to compare against.
    # A None baseline_id means drift analysis must skip this case, since there is
    # nothing to diff the prediction against.
    baseline_id: Optional[str]
    category: str
    original_text: Optional[str]
    attacked_text: Optional[str]
    # True means this is not valid JSON. The runner must send raw_body and raw_headers
    # exactly as given instead of letting the HTTP client serialise a dict and build
    # its own headers. Ignoring this flag silently turns a malformed-input attack into
    # a well-formed request and the test proves nothing.
    is_raw: bool = False
    raw_body: Optional[Union[bytes, str]] = None
    raw_headers: Optional[dict] = None


@dataclass
class RunResult:
    """The full outcome of a single request against one endpoint version."""

    # "baseline" or "attack".
    case_type: str
    # None for baseline requests.
    attack_id: Optional[str]
    baseline_id: Optional[str]
    category: Optional[str]
    # "v1" or "v2".
    version: str
    # None if the connection failed entirely and no HTTP response came back.
    status_code: Optional[int]
    # Always store the full body, not just the status.
    response_body: str
    error: Optional[str]
    label: Optional[str]
    confidence: Optional[float]
    all_scores: Optional[dict]
    latency_ms: float
    # One of "normal", "slow", "timeout".
    latency_band: str
    endpoint_alive_after: bool

    # --- Stage 3 additions. Appended, with defaults, so every historical row still
    # loads and every existing positional construction still works. Never reorder.
    #
    # Which target produced this row: "emotion_v1", "emotion_v2" or "sentiment_v1".
    # Blank is supported for HISTORICAL rows only -- the V6 benchmark predates the
    # registry. A new run must set it explicitly. Nothing may infer a model from
    # `version` alone or silently fall back to an emotion target.
    target_id: str = ""
    # "core" or "oces". Blank is historical-only, and means the original core suite.
    # CI is a frozen *selection* of core, not a third suite: there is no "ci_core".
    suite_id: str = ""
    # Length in bytes of the exact serialised HTTP request body that was sent, as
    # recorded by the sender. None means the evidence is genuinely unavailable
    # (a historical row, or a failure before the body was serialised) -- it never
    # means zero, and it is never a character count or a manifest text length.
    request_body_bytes: Optional[int] = None
    # SHA-256 hex digest of those same bytes. None under the same conditions.
    # Present even when the transport subsequently failed: a request that got no
    # response still has a known attempted body.
    request_body_sha256: Optional[str] = None


@dataclass
class Finding:
    """One reported robustness issue, rendered into the report."""

    finding_id: str
    title: str
    category: str
    severity_score: float
    # One of "Critical", "High", "Medium", "Low".
    severity_tier: str
    description: str
    # Required: every finding must carry a fix. A finding with no remediation should fail
    # at construction, not render as a blank section in the report. This sits before
    # evidence because a required field cannot follow a defaulted one in a dataclass, so
    # note the positional order is (..., description, remediation, evidence).
    remediation: str
    # Attack ids that support this finding. Defaults to empty, since a finding can
    # legitimately have no specific attack ids attached.
    evidence: list[str] = field(default_factory=list)


# ======================================================================================
# Stage 3 shared structural types.
#
# These are MODEL-FREE. Nothing below imports transformers, torch, or any endpoint
# module, and nothing here loads weights. `endpoint/targets.py` parses JSON into these
# types; the runner, orchestrator, analysis, policy and report all read them from here.
# One definition, one import path: `from contract import ...`.
# ======================================================================================

# --- suites and outcomes (module constants so a typo is an ImportError, not a silent
# --- string mismatch three components downstream) -------------------------------------

SUITE_CORE = "core"
SUITE_OCES = "oces"
SUITES = frozenset({SUITE_CORE, SUITE_OCES})

EVAL_KIND_PAIRED = "paired"
EVAL_KIND_SINGLE = "single"
EVAL_KINDS = frozenset({EVAL_KIND_PAIRED, EVAL_KIND_SINGLE})

# Execution mode an evaluation is intended for. "ci" is the internal gate mode; it is
# still suite "core" with a frozen case_set_id.
EVAL_MODE_STANDARD = "standard"
EVAL_MODE_CI = "ci"
EVAL_MODES = frozenset({EVAL_MODE_STANDARD, EVAL_MODE_CI})

# The two additional-evaluation families. Paraphrase and distractor ONLY. There is no
# negation family, no directional oracle and no score-drop threshold in this design.
OCES_FAMILY_PARAPHRASE = "oces.paraphrase"
OCES_FAMILY_DISTRACTOR = "oces.distractor"
OCES_FAMILIES = (OCES_FAMILY_PARAPHRASE, OCES_FAMILY_DISTRACTOR)

# The original core families, unchanged.
CORE_FAMILIES = (
    "malformed", "boundary", "perturbation", "encoding", "whitespace", "truncation",
)

# Coverage classes. Labels describe INTENDED input-control coverage, not demonstrated
# effectiveness and not a causal claim about which control produced an observed result.
COVERAGE_IN_SCOPE = "in_scope"
COVERAGE_OUT_OF_SCOPE = "out_of_scope"
COVERAGE_NOT_TARGETED = "not_targeted"
COVERAGE_MIXED = "mixed"
COVERAGE_CLASSES = frozenset(
    {COVERAGE_IN_SCOPE, COVERAGE_OUT_OF_SCOPE, COVERAGE_NOT_TARGETED, COVERAGE_MIXED}
)


class ContractError(ValueError):
    """Raised when a structural contract object is constructed with invalid content.

    Deliberately a ValueError subclass so existing `except ValueError` call sites keep
    working. Construction fails loudly rather than producing a half-valid object that
    only breaks three components later.
    """


# --- registry specs -------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    """A pinned model. Every field is a real, resolved value -- never "main"."""

    # canonical repo id, e.g. "j-hartmann/emotion-english-distilroberta-base"
    model_id: str
    revision: str                 # exact 40-hex commit; "main" and short SHAs are rejected
    tokenizer_id: str             # usually the same repo
    tokenizer_revision: str       # exact 40-hex commit
    # Declared label space, in model id order, with EXACT casing. Sentiment is
    # ("NEGATIVE", "POSITIVE"); nothing may lowercase it or map it onto emotion labels.
    labels: tuple[str, ...]
    # Usable input limit in tokens, including special tokens. Read from the tokenizer,
    # not copied from a model card's training sequence length.
    max_sequence_length: int
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("revision", "tokenizer_revision"):
            value = getattr(self, name)
            if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
                raise ContractError(
                    f"{self.model_id}: {name} must be an exact 40-hex revision, got "
                    f"{value!r}. A branch name, short SHA or placeholder is not a pin."
                )
        if not self.labels:
            raise ContractError(f"{self.model_id}: label space must not be empty")
        if len(set(self.labels)) != len(self.labels):
            raise ContractError(f"{self.model_id}: duplicate labels in {self.labels}")
        if self.max_sequence_length <= 0:
            raise ContractError(
                f"{self.model_id}: max_sequence_length must be positive, got "
                f"{self.max_sequence_length}"
            )


@dataclass(frozen=True)
class TaskSpec:
    """A classification task: one label space, one default baseline file."""

    task_id: str                  # "emotion_7" | "sentiment_2"
    model_ref: str                # key into Registry.models
    baseline_file: str            # repo-relative default baseline for suite "core"
    description: str = ""


@dataclass(frozen=True)
class TargetSpec:
    """One servable endpoint. `module` is a dotted path and is NOT imported at load."""

    target_id: str                # "emotion_v1" | "emotion_v2" | "sentiment_v1"
    task_id: str                  # key into Registry.tasks
    # Legacy compatibility. sentiment_v1 is version "v1"; target_id, not version, is
    # what distinguishes it from emotion_v1.
    version: str
    module: str                   # e.g. "endpoint.v2"
    app_attr: str = "app"
    port: int = 0
    hardened: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.version not in ("v1", "v2"):
            raise ContractError(
                f"{self.target_id}: version must be v1 or v2, got {self.version!r}"
            )
        if not self.port:
            raise ContractError(f"{self.target_id}: a loopback port must be configured")

    @property
    def app_path(self) -> str:
        """The `module:attr` string uvicorn wants. Still no import happens here."""
        return f"{self.module}:{self.app_attr}"


@dataclass(frozen=True)
class EvaluationSpec:
    """One unit of work: a suite, run against one target (single) or two (paired)."""

    evaluation_id: str            # "emotion.core" | "sentiment.core" | "ci.emotion" | ...
    kind: str                     # EVAL_KIND_PAIRED | EVAL_KIND_SINGLE
    task_id: str
    suite_id: str                 # SUITE_CORE | SUITE_OCES
    target_ids: tuple[str, ...]
    declared_families: tuple[str, ...]
    # Frozen selection within the suite. Only CI uses one today.
    case_set_id: Optional[str] = None
    # Evaluation-level override of TaskSpec.baseline_file. OCES supplies its own frozen
    # seed file here. Resolve it BEFORE suite generation and record the hash of the file
    # actually used -- never the unrelated core baseline hash.
    baseline_file: Optional[str] = None
    mode: str = EVAL_MODE_STANDARD
    description: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EVAL_KINDS:
            raise ContractError(f"{self.evaluation_id}: unknown kind {self.kind!r}")
        if self.suite_id not in SUITES:
            raise ContractError(
                f"{self.evaluation_id}: unknown suite {self.suite_id!r}. CI is a frozen "
                "selection of 'core'; there is no separate 'ci_core' suite."
            )
        if self.mode not in EVAL_MODES:
            raise ContractError(f"{self.evaluation_id}: unknown mode {self.mode!r}")
        expected = 2 if self.kind == EVAL_KIND_PAIRED else 1
        if len(self.target_ids) != expected:
            raise ContractError(
                f"{self.evaluation_id}: kind {self.kind!r} requires exactly {expected} "
                f"target(s), got {len(self.target_ids)}"
            )
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ContractError(
                f"{self.evaluation_id}: duplicate target ids {self.target_ids}"
            )
        if not self.declared_families:
            raise ContractError(
                f"{self.evaluation_id}: declared_families must not be empty"
            )


@dataclass(frozen=True)
class Registry:
    """The parsed target registry. Immutable, model-free, no global singleton state.

    Built by `endpoint.targets.load_registry`. Every accessor raises `ContractError` on
    an unknown id rather than returning None, so a typo fails at the lookup instead of
    producing a null that is mistaken for "not configured" further downstream.
    """

    registry_version: str
    models: Mapping[str, ModelSpec]
    tasks: Mapping[str, TaskSpec]
    targets: Mapping[str, TargetSpec]
    evaluations: Mapping[str, EvaluationSpec]
    source_path: str = ""
    source_sha256: str = ""

    def target(self, target_id: str) -> TargetSpec:
        try:
            return self.targets[target_id]
        except KeyError:
            raise ContractError(
                f"unknown target_id {target_id!r}; configured: {sorted(self.targets)}"
            ) from None

    def task_for(self, target_id: str) -> TaskSpec:
        spec = self.target(target_id)
        try:
            return self.tasks[spec.task_id]
        except KeyError:
            raise ContractError(
                f"target {target_id!r} references unknown task {spec.task_id!r}"
            ) from None

    def model_for(self, target_id: str) -> ModelSpec:
        task = self.task_for(target_id)
        try:
            return self.models[task.model_ref]
        except KeyError:
            raise ContractError(
                f"task {task.task_id!r} references unknown model {task.model_ref!r}"
            ) from None

    def evaluation(self, evaluation_id: str) -> EvaluationSpec:
        try:
            return self.evaluations[evaluation_id]
        except KeyError:
            raise ContractError(
                f"unknown evaluation_id {evaluation_id!r}; configured: "
                f"{sorted(self.evaluations)}"
            ) from None

    def baseline_file_for(self, evaluation_id: str) -> str:
        """The baseline file this evaluation actually uses.

        The evaluation-level override wins; otherwise the task default. Resolve this
        before generating a suite, and hash the file this returns.
        """
        spec = self.evaluation(evaluation_id)
        if spec.baseline_file:
            return spec.baseline_file
        try:
            return self.tasks[spec.task_id].baseline_file
        except KeyError:
            raise ContractError(
                f"evaluation {evaluation_id!r} references unknown task {spec.task_id!r}"
            ) from None


# --- gate outcome ---------------------------------------------------------------------

CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_ERROR = "error"
CHECK_NOT_APPLICABLE = "not_applicable"
CHECK_STATUSES = frozenset({CHECK_PASS, CHECK_FAIL, CHECK_ERROR, CHECK_NOT_APPLICABLE})

OUTCOME_PASS = "pass"
OUTCOME_POLICY_FAILURE = "policy_failure"
OUTCOME_EXECUTION_ERROR = "execution_error"
OUTCOMES = frozenset({OUTCOME_PASS, OUTCOME_POLICY_FAILURE, OUTCOME_EXECUTION_ERROR})

# The only permitted mapping. A gate that returns 0 for a failure is worse than no gate.
EXIT_CODE_BY_OUTCOME = {
    OUTCOME_PASS: 0,
    OUTCOME_POLICY_FAILURE: 1,
    OUTCOME_EXECUTION_ERROR: 2,
}


@dataclass
class CheckResult:
    """One blocking or informational check inside a gate policy."""

    check_id: str
    status: str                   # one of CHECK_STATUSES
    reason: str                   # human-readable, always populated
    # Named references into the evidence: case keys, artifact paths, run ids.
    evidence_refs: list[str] = field(default_factory=list)
    # What was measured, and what it was compared against. None means genuinely not
    # measured -- do not substitute zero.
    observed: Any = None
    threshold: Any = None
    # Informational checks are reported but never change the outcome. Slow counts,
    # attack flip rates and finding-group counts are informational in this first policy.
    blocking: bool = True

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ContractError(f"{self.check_id}: unknown status {self.status!r}")
        if not self.reason:
            raise ContractError(
                f"{self.check_id}: reason is required, even when passing"
            )


@dataclass
class GateOutcome:
    """The complete result of one gate evaluation. Produced by a PURE function.

    `analysis.policy.evaluate_policy` builds this with no file, process or network I/O.
    The runner CLI serialises it and turns `exit_code` into the process exit status.
    """

    outcome: str                  # one of OUTCOMES
    exit_code: int                # must equal EXIT_CODE_BY_OUTCOME[outcome]
    # Policy identity: what was evaluated, and exactly which rules were used.
    policy_id: str
    policy_version: str
    policy_sha256: str
    # Candidate under test: target_id, commit, model_id, model_revision.
    candidate: dict
    # Approved reference snapshot: reference_id and its sha256. Empty dict when the
    # policy legitimately has no reference component.
    reference: dict
    # What was actually scored.
    suite_id: str
    case_set_id: str
    selection_sha256: str
    checks: list[CheckResult]
    summary: dict = field(default_factory=dict)
    # Paths to produced evidence: analysis.json, report.html, raw results, logs.
    artifacts: dict = field(default_factory=dict)
    # Cases deliberately excluded from scoring, each with a reason.
    exclusions: list[dict] = field(default_factory=list)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ContractError(f"unknown gate outcome {self.outcome!r}")
        expected = EXIT_CODE_BY_OUTCOME[self.outcome]
        if self.exit_code != expected:
            raise ContractError(
                f"outcome {self.outcome!r} must carry exit_code {expected}, got "
                f"{self.exit_code}"
            )
        if not self.checks:
            raise ContractError(
                "a GateOutcome with zero checks cannot be a result. Zero executed "
                "checks is an execution_error, never a pass."
            )
        blocking = [c for c in self.checks if c.blocking]
        if self.outcome == OUTCOME_PASS:
            bad = [
                c.check_id for c in blocking
                if c.status not in (CHECK_PASS, CHECK_NOT_APPLICABLE)
            ]
            if bad:
                raise ContractError(
                    f"outcome 'pass' contradicts failing blocking checks: {bad}"
                )
            if not any(c.status == CHECK_PASS for c in blocking):
                raise ContractError(
                    "outcome 'pass' requires at least one blocking check that actually "
                    "passed; all-not_applicable is not a pass"
                )
        if self.outcome == OUTCOME_POLICY_FAILURE and not any(
            c.status == CHECK_FAIL for c in blocking
        ):
            raise ContractError(
                "outcome 'policy_failure' requires a failing blocking check"
            )
        if self.outcome == OUTCOME_EXECUTION_ERROR and not any(
            c.status == CHECK_ERROR for c in self.checks
        ):
            raise ContractError(
                "outcome 'execution_error' requires a check in status 'error'"
            )

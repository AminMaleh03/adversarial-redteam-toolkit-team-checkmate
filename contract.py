"""Shared data contracts for the toolkit. Every folder imports from here and nowhere else."""

# OWNER: Ahsan. This file is frozen. Any change must be announced to the whole team
# before it lands, because baseline, attacks, runner, analysis and report all depend on it.

from dataclasses import dataclass, field
from typing import Optional, Union


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

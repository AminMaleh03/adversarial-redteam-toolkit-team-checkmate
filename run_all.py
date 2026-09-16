"""Root orchestration entry point for Team Checkmate.

    python run_all.py --mode full   [--run-name NAME]
    python run_all.py --mode demo   [--run-name NAME]

Wires together the already-implemented components -- baseline/attack generation,
the V1/V2 endpoints, the runner, analysis and report -- into one command. It owns
process lifecycle (starting/stopping uvicorn) and step sequencing only. It does
not reimplement attack generation, request sending, scoring, or rendering; those
stay in their owning modules (see AGENTS.md).

``run_experiment()`` is the reusable entry point: callable from Python, no
interactive prompts, project-relative paths only, returns a structured result.
A future deployment UI can call it directly instead of shelling out to this CLI.
"""

from __future__ import annotations

import argparse
import difflib
import html
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from analysis import analyze as analysis_mod  # noqa: E402
from analysis import coverage as analysis_coverage  # noqa: E402
from analysis import oces as analysis_oces  # noqa: E402
from analysis import remediation as analysis_remediation  # noqa: E402
from attacks import library as attack_library  # noqa: E402
from baseline.load import load_baseline  # noqa: E402
from contract import AttackCase, CORE_FAMILIES, RunResult  # noqa: E402
from endpoint import targets as target_registry  # noqa: E402
from report import generate as report_mod  # noqa: E402
from runner import run as runner_mod  # noqa: E402

RESULTS_ROOT = ROOT / "results"
# Stable, project-relative location for the canonical verified full-benchmark report bundle
# (provenance recorded in HANDOFF.md). Demo reports link to a copy of this, never to a
# transient results/<run>/ path or an absolute filesystem path.
VERIFIED_FULL_REPORT_DIR = ROOT / "artifacts" / "verified_full_report"

ENDPOINT_SPECS = {
    "v1": {"app": "endpoint.v1:app", "port": 8000},
    "v2": {"app": "endpoint.v2:app", "port": 8001},
}

def _emit_progress(callback, stage: str, message: str) -> None:
    """Report a real orchestration transition to an optional caller-supplied callback.

    Never used to manufacture progress that hasn't actually happened yet -- see the call
    sites in run_experiment()/run_analysis_and_report() for what stage means what.
    """
    if callback:
        callback(stage, message)


READY_TIMEOUT_S = 180.0
READY_POLL_S = 1.0
HEALTH_CHECK_TIMEOUT_S = 2.0

# Demo mode sends every standalone attack plus every derived attack for this many
# baselines. Computed from the real suite at run time (see compute_demo_attack_limit),
# never a hardcoded case count, so it tracks whatever attacks/ actually builds.
DEMO_BASELINE_COVERAGE = 2

# Excluded from DEMO MODE ONLY (--skip, not a suite change): this case sits right at the
# 10-second request deadline and has been observed to land as either a slow-but-completed
# response or a genuine timeout depending on machine load, which can make a live demo look
# like it found a new V2 regression purely from timing noise. The attack itself, its
# definition, its scoring, and its presence in the full suite are all untouched -- it is
# still built, still registered in the manifest, and still sent in --mode full.
DEMO_EXCLUDED_ATTACK_IDS = ("malformed.oversized_10mb",)

FAILURE_MODE_PRIORITY = (
    "service_unavailable", "unhandled_5xx", "timeout", "connection_failure",
)
PREVIEW_CHARS = 160


# --------------------------------------------------------------------------------------
# endpoint lifecycle
# --------------------------------------------------------------------------------------


@dataclass
class EndpointHandle:
    version: str
    port: int
    process: subprocess.Popen
    log_path: Path
    _log_handle: object
    target_id: str = ""
    peak_memory_bytes: Optional[int] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.peak_memory_bytes = _peak_process_tree_memory(self.process.pid)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=20)
        try:
            self._log_handle.close()
        except OSError:
            pass


def _wait_ready(handle: EndpointHandle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        if handle.process.poll() is not None:
            tail = ""
            try:
                tail = handle.log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            except OSError:
                pass
            raise RuntimeError(
                f"{handle.version} endpoint process exited before becoming ready "
                f"(exit code {handle.process.returncode}). Log tail:\n{tail}"
            )
        try:
            resp = httpx.get(handle.url + "/health", timeout=HEALTH_CHECK_TIMEOUT_S)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(READY_POLL_S)
    raise RuntimeError(
        f"{handle.version} endpoint did not answer /health within {timeout}s ({last_error})"
    )


def _peak_process_memory(pid: int) -> Optional[int]:
    """Best-effort peak RSS/working-set reading without adding a runtime dependency."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD,
            ]
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return None
            try:
                if psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb
                ):
                    return int(counters.PeakWorkingSetSize)
            finally:
                kernel.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    else:
        try:
            for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    return None


def _descendant_process_ids(parent_pid: int) -> list[int]:
    """Best-effort Windows process-tree discovery for venv launcher children."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return []
        parents = {}
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        found = []
        frontier = {parent_pid}
        while frontier:
            children = {pid for pid, parent in parents.items() if parent in frontier}
            children -= set(found)
            if not children:
                break
            found.extend(sorted(children))
            frontier = children
        return found
    except (AttributeError, OSError, ValueError):
        return []


def _peak_process_tree_memory(pid: int) -> Optional[int]:
    measurements = [
        value for value in (_peak_process_memory(item) for item in [pid, *_descendant_process_ids(pid)])
        if value is not None
    ]
    return sum(measurements) if measurements else None


def start_target(target_id: str, out_dir: Path, registry=None) -> EndpointHandle:
    """Start one trusted registry target and wait for its health endpoint."""
    registry = registry or target_registry.load_registry()
    target = registry.target(target_id)
    log_path = out_dir / f"{target_id}_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8", newline="\n")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", target.app_path,
         "--host", "127.0.0.1", "--port", str(target.port)],
        cwd=str(ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
    )
    handle = EndpointHandle(version=target.version, port=target.port, process=process,
                            log_path=log_path, _log_handle=log_handle, target_id=target_id)
    try:
        _wait_ready(handle, READY_TIMEOUT_S)
    except Exception:
        handle.stop()
        raise
    return handle


def start_endpoint(version: str, out_dir: Path) -> EndpointHandle:
    """Backward-compatible emotion endpoint lifecycle helper."""
    if version not in ENDPOINT_SPECS:
        raise ValueError(f"unknown emotion endpoint version {version!r}")
    return start_target(f"emotion_{version}", out_dir)


# --------------------------------------------------------------------------------------
# suite construction (shared with the runner's own logic -- read-only reuse for demo
# sizing and for recovering attack text that RunResult does not persist)
# --------------------------------------------------------------------------------------


def build_full_suite(baselines) -> list[AttackCase]:
    from endpoint.model import MAX_SEQUENCE_LENGTH, tokenizer

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    return attack_library.build_suite(
        list(baselines), token_counter=count_tokens, max_tokens=int(MAX_SEQUENCE_LENGTH)
    )


def compute_demo_attack_limit(baselines, attacks: list[AttackCase]) -> int:
    """Every standalone attack plus every derived attack for the first N baselines.

    Computed from the actual built suite (send order: standalone first, then derived
    per baseline in baseline order -- see attacks/library.py), so the curated demo set
    always covers the categories most likely to show a real failure and a real flip
    without hardcoding a case count that could drift out of sync with attacks/.
    """
    covered_ids = {b.baseline_id for b in baselines[:DEMO_BASELINE_COVERAGE]}
    limit = 0
    for case in attacks:
        if case.baseline_id is None or case.baseline_id in covered_ids:
            limit += 1
    return limit


# --------------------------------------------------------------------------------------
# running the suite against one endpoint (delegates to runner.run; no logic duplicated)
# --------------------------------------------------------------------------------------


def run_suite(version: str, target: str, out_dir: Path, *,
             attack_limit: Optional[int], skip: Sequence[str] = ()) -> int:
    argv = ["--target", target, "--version", version, "--out", str(out_dir)]
    if attack_limit is not None:
        argv += ["--limit", str(attack_limit)]
    for attack_id in skip:
        argv += ["--skip", attack_id]
    exit_code = runner_mod.main(argv)
    if exit_code == 2:
        # Preflight failure: no cases were sent and no new artifacts were written.
        raise RuntimeError(
            f"{version} endpoint failed its preflight health check; no requests were sent. "
            f"See {out_dir} for any preserved prior artifacts."
        )
    if exit_code not in (0, 1):
        raise RuntimeError(f"runner for {version} exited unexpectedly with code {exit_code}")
    return exit_code  # 0 completed; 1 = endpoint died mid-suite, preserved as recorded


# --------------------------------------------------------------------------------------
# demo evidence: featured failure + featured prediction flip, built only from real data
# --------------------------------------------------------------------------------------


def _run_outcome(result: Optional[RunResult]) -> Optional[dict]:
    if result is None:
        return None
    status = result.status_code
    if status is not None and 500 <= status < 600:
        outcome = "Unhandled server error"
    elif status is not None and 400 <= status < 500:
        outcome = "Rejected safely"
    elif status is not None and 200 <= status < 300:
        outcome = "Accepted"
    elif result.latency_band == "timeout":
        outcome = "No response (request timeout)"
    elif status is None:
        outcome = "No response (connection/transport failure)"
    else:
        outcome = f"HTTP {status}"
    return {
        "status_code": status,
        "outcome": outcome,
        "error": result.error,
        "latency_ms": result.latency_ms,
        "latency_band": result.latency_band,
        "endpoint_alive_after": result.endpoint_alive_after,
    }


def _payload_preview(case: Optional[AttackCase]) -> tuple[str, Optional[int]]:
    if case is None:
        return "", None
    if case.is_raw:
        body = case.raw_body if case.raw_body is not None else b""
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        size = len(raw)
        text = raw.decode("utf-8", errors="replace")
    else:
        text = case.attacked_text if case.attacked_text is not None else (case.original_text or "")
        size = len(text.encode("utf-8"))
    preview = text[:PREVIEW_CHARS]
    if len(text) > PREVIEW_CHARS:
        preview += f"... [truncated, {size:,} bytes total]"
    return preview, size


def describe_modification(original: Optional[str], attacked: Optional[str]) -> str:
    """Human-readable description of what changed, with Unicode names for single-char swaps."""
    if original is None or attacked is None:
        return "text modified (original not available for comparison)"
    if original == attacked:
        return "no visible character difference detected"
    matcher = difflib.SequenceMatcher(a=original, b=attacked, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        orig_seg, new_seg = original[i1:i2], attacked[j1:j2]
        if tag == "replace" and len(orig_seg) == 1 and len(new_seg) == 1:
            oc, nc = orig_seg, new_seg
            parts.append(
                f"position {i1}: '{oc}' (U+{ord(oc):04X} {unicodedata.name(oc, 'UNKNOWN')}) "
                f"-> '{nc}' (U+{ord(nc):04X} {unicodedata.name(nc, 'UNKNOWN')})"
            )
        elif tag == "replace":
            parts.append(f"position {i1}: {orig_seg!r} -> {new_seg!r}")
        elif tag == "insert":
            parts.append(f"position {i1}: inserted {new_seg!r}")
        elif tag == "delete":
            parts.append(f"position {i1}: deleted {orig_seg!r}")
    if not parts:
        return "no visible character difference detected"
    shown = parts[:3]
    suffix = f" (+{len(parts) - 3} more)" if len(parts) > 3 else ""
    return "; ".join(shown) + suffix


def highlight_diff_html(original: Optional[str], attacked: Optional[str]) -> tuple[str, str]:
    """Pre-escaped HTML for both strings, with the differing spans wrapped in <mark>.

    Escaping happens once, here, in Python -- callers embed the two returned strings as
    trusted HTML (the report template via Jinja's `safe` filter; web/lab.py's Live Red-Team
    Lab embeds them directly into its JSON response under clearly-named fields), so this
    function is what makes that safe. `html.escape` is unconditionally safe for arbitrary
    input, so this is fine both for our own generated attack text (deterministic
    transformations of committed baseline sentences) and for text derived from live,
    judge-supplied Lab input (System V5.4) -- the function makes no assumption about
    provenance either way.
    """
    if original is None or attacked is None:
        return html.escape(original or ""), html.escape(attacked or "")
    if original == attacked:
        escaped = html.escape(original)
        return escaped, escaped
    matcher = difflib.SequenceMatcher(a=original, b=attacked, autojunk=False)
    orig_parts: list[str] = []
    attacked_parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_seg, new_seg = original[i1:i2], attacked[j1:j2]
        if tag == "equal":
            orig_parts.append(html.escape(orig_seg))
            attacked_parts.append(html.escape(new_seg))
            continue
        if orig_seg:
            orig_parts.append(f'<mark class="demo-mark">{html.escape(orig_seg)}</mark>')
        if new_seg:
            attacked_parts.append(f'<mark class="demo-mark">{html.escape(new_seg)}</mark>')
    return "".join(orig_parts), "".join(attacked_parts)


def _select_featured_failure(analysis: dict):
    """Strongest legitimate V1 failure, ranked unavailability > 5xx > timeout > connection.

    Returns (failure_mode, finding_entry, attack_id) or (None, None, None). Never picks
    service_unavailable unless a finding group with that failure_mode actually exists --
    that only happens when a post-request health check actually failed.
    """
    findings = analysis["summary_v1"]["findings"]
    for mode in FAILURE_MODE_PRIORITY:
        candidates = [e for e in findings if e["failure_mode"] == mode]
        if not candidates:
            continue

        def sort_key(entry):
            oversized = any("oversized" in aid for aid in entry["finding"]["evidence"])
            return (oversized, entry["finding"]["severity_score"])

        candidates.sort(key=sort_key, reverse=True)
        chosen = candidates[0]
        evidence = chosen["finding"]["evidence"]
        oversized_ids = sorted(aid for aid in evidence if "oversized" in aid)
        attack_id = oversized_ids[0] if oversized_ids else sorted(evidence)[0]
        return mode, chosen, attack_id
    return None, None, None


def build_featured_failure(mode, chosen, attack_id, attack_index, v1_attacks, v2_attacks):
    if attack_id is None:
        return None
    case = attack_index.get(attack_id)
    v1_result = v1_attacks.get(attack_id)
    v2_result = v2_attacks.get(attack_id)
    preview, size_bytes = _payload_preview(case)
    category = chosen["finding"]["category"]
    subfamily = chosen["subfamily"]

    if mode == "unhandled_5xx" and any("oversized" in e for e in chosen["finding"]["evidence"]):
        remediation = (
            "Reject requests above a defined body/input size limit before expensive model "
            "inference or downstream processing begins."
        )
    else:
        remediation = analysis_mod.REMEDIATIONS.get(mode, chosen["finding"]["remediation"])

    if mode == "service_unavailable":
        interpretation = (
            "The post-request health check failed: this is observed service unavailability, "
            "the strongest evidence of unavailability recorded in this run. It is not, by "
            "itself, confirmation that the underlying process terminated."
        )
    elif mode == "unhandled_5xx":
        alive = bool(v1_result and v1_result.endpoint_alive_after)
        alive_note = "the service remained available afterward" if alive else \
            "availability afterward was not confirmed by this evidence"
        interpretation = (
            f"The endpoint returned an unhandled 5xx response, and {alive_note}. This is an "
            "unhandled server error, not a process crash."
        )
    elif mode == "timeout":
        interpretation = (
            "No response was returned within the 10 second request deadline. The recorded "
            "error is client-side and does not identify which server-side stage was reached."
        )
    else:
        interpretation = analysis_mod.FAILURE_MODE_DETAIL.get(mode, "")

    return {
        "attack_id": attack_id,
        "category": category,
        "subfamily": subfamily,
        "failure_mode": mode,
        "failure_label": analysis_mod.FAILURE_MODE_TITLES.get(mode, mode),
        "input_description": f"{category}/{subfamily}",
        "payload_bytes": size_bytes,
        "preview": preview,
        "v1": _run_outcome(v1_result),
        "v2": _run_outcome(v2_result),
        "technical_interpretation": interpretation,
        "remediation": remediation,
    }


def _select_featured_flip(analysis: dict):
    """Prefer a visually subtle homoglyph flip; else the largest confidence swing."""
    entries = [e for e in analysis["summary_v1"]["findings"] if e["failure_mode"] == "prediction_flip"]
    if not entries:
        return None
    per_flip = {e["attack_id"]: e for e in analysis["summary_v1"]["drift"]["confidence_change"]["per_flip"]}

    def entry_priority(entry):
        is_homoglyph = entry["subfamily"].startswith("homoglyph")
        deltas = [abs(per_flip[aid]["delta"]) for aid in entry["finding"]["evidence"] if aid in per_flip]
        return (is_homoglyph, max(deltas) if deltas else 0.0)

    entries.sort(key=entry_priority, reverse=True)
    chosen_group = entries[0]
    candidate_ids = [aid for aid in chosen_group["finding"]["evidence"] if aid in per_flip]
    if not candidate_ids:
        return None
    attack_id = max(candidate_ids, key=lambda aid: abs(per_flip[aid]["delta"]))
    return attack_id, chosen_group, per_flip[attack_id]


def build_featured_flip(selection, attack_index, v1_attacks, v2_attacks, v1_baselines):
    if selection is None:
        return None
    attack_id, chosen_group, flip_entry = selection
    case = attack_index.get(attack_id)
    if case is None:
        return None
    v1_result = v1_attacks.get(attack_id)
    v2_result = v2_attacks.get(attack_id)
    baseline_result = v1_baselines.get(case.baseline_id) if case.baseline_id else None
    original_html, attacked_html = highlight_diff_html(case.original_text, case.attacked_text)
    return {
        "attack_id": attack_id,
        "baseline_id": case.baseline_id,
        "category": chosen_group["finding"]["category"],
        "subfamily": chosen_group["subfamily"],
        "validity_tiers": chosen_group["validity_tiers"],
        "original_text": case.original_text,
        "attacked_text": case.attacked_text,
        "original_html": original_html,
        "attacked_html": attacked_html,
        "modification": describe_modification(case.original_text, case.attacked_text),
        "original_label": baseline_result.label if baseline_result else None,
        "original_confidence": flip_entry["clean_confidence"],
        "attacked_label": v1_result.label if v1_result else None,
        "attacked_confidence": flip_entry["attacked_confidence"],
        "confidence_change": flip_entry["delta"],
        "v1": _run_outcome(v1_result),
        "v2": _run_outcome(v2_result),
        "v2_still_flipped": bool(
            v2_result and baseline_result and v2_result.label != baseline_result.label
        ),
        "remediation": (
            "This is a model-level robustness gap, not an endpoint defect. V2's application-layer "
            "defenses (length limit, strict types, exception handling, Unicode normalization) do not "
            "reach it -- NFKC normalization does not fold cross-script homoglyphs or fix typo "
            "sensitivity. Closing it needs adversarial/perturbation-aware evaluation, training-data "
            "augmentation with this perturbation family, or robustness fine-tuning, not endpoint-level "
            "exception handling."
        ),
    }


def build_demo_evidence(run_dir: Path, analysis: dict, attack_index: dict) -> dict:
    v1_results = analysis_mod.load_results(run_dir / "v1" / "results_v1.jsonl")
    v2_results = analysis_mod.load_results(run_dir / "v2" / "results_v2.jsonl")
    v1_attacks = {r.attack_id: r for r in v1_results if r.case_type == "attack"}
    v2_attacks = {r.attack_id: r for r in v2_results if r.case_type == "attack"}
    v1_baselines = {r.baseline_id: r for r in v1_results if r.case_type == "baseline"}

    mode, chosen, attack_id = _select_featured_failure(analysis)
    literal_crash_available = mode == "service_unavailable"
    failure = build_featured_failure(mode, chosen, attack_id, attack_index, v1_attacks, v2_attacks)

    flip_selection = _select_featured_flip(analysis)
    flip = build_featured_flip(flip_selection, attack_index, v1_attacks, v2_attacks, v1_baselines)

    # Kept separate from `notes`: this is an expected, calm statement of fact every run
    # (not a problem to warn about), so the template renders it as a small caption near the
    # featured failure card rather than a prominent warning box. `notes` stays reserved for
    # genuine anomalies (no example found) that should stay visually prominent.
    crash_status_note = None
    if not literal_crash_available:
        crash_status_note = (
            "No request in this run caused observed service unavailability (a failed post-request "
            "health check). The featured failure below is the strongest legitimate example found in "
            "this run's data and is reported accurately as an unhandled server error, not a process "
            "crash."
        )

    notes = []
    if failure is None:
        notes.append(
            "No unhandled server error, timeout, connection failure, or service-unavailability "
            "finding was found in this run."
        )
    if flip is None:
        notes.append(
            "No qualifying prediction flip (clean confidence >= 0.6, top label changed) was found "
            "in this run."
        )

    return {
        "literal_crash_case_available": literal_crash_available,
        "featured_failure": failure,
        "featured_prediction_flip": flip,
        "crash_status_note": crash_status_note,
        "notes": notes,
    }


# --------------------------------------------------------------------------------------
# analysis + report
# --------------------------------------------------------------------------------------


def run_analysis_and_report(run_dir: Path, attack_index: dict, *, html_only: bool, mode: str,
                            progress_callback=None) -> dict:
    _emit_progress(progress_callback, "analyzing", "Comparing V1 and V2 results")
    # run_analysis_from_dir returns the v3 envelope (schema_version 3, evaluations[]).
    # This orchestrator, its demo-evidence selection and the report/web layer downstream
    # all still consume the paired emotion v2 shape; project onto it with the official
    # compatibility adapter rather than reading v2-only keys off the v3 document.
    analysis = analysis_mod.legacy_v2_view(analysis_mod.run_analysis_from_dir(str(run_dir)))
    demo_evidence = build_demo_evidence(run_dir, analysis, attack_index)

    report_payload = {
        "schema_version": analysis["schema_version"],
        "summary_v1": analysis["summary_v1"],
        "summary_v2": analysis["summary_v2"],
        "comparison": analysis["comparison"],
        "demo_evidence": demo_evidence,
    }
    # Demo mode links "View Detailed Report" to a copy of the stable verified full-benchmark
    # artifact (see VERIFIED_FULL_REPORT_DIR), never to a transient/absolute path. Only the
    # href needs to be known before rendering; the actual copy happens after generate_report
    # creates report_dir (which must not already exist -- see report.generate.generate_report).
    detailed_available = False
    if mode == "demo":
        detailed_available = (VERIFIED_FULL_REPORT_DIR / "report.html").exists()
        report_payload["detailed_report"] = {
            "available": detailed_available,
            "relative_href": "detailed/report.html" if detailed_available else "",
        }

    (run_dir / "demo_evidence.json").write_text(
        json.dumps(demo_evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    raw = json.dumps(report_payload, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")

    # Full mode gets the complete technical/audit report; demo mode gets a short,
    # single-page judge-facing report (see report/demo_template.html). Both read the
    # same analysis JSON -- only presentation differs, per report.generate.render_html.
    _emit_progress(progress_callback, "generating_results", "Generating the report")
    report_dir = run_dir / "report"
    # Live Demo reports never expose a PDF (v6.1) -- demo_template.html has no download link
    # for it, so generating one had no consumer. Only "full" mode ever attempts PDF rendering.
    effective_html_only = html_only or mode == "demo"
    pdf_ok = not effective_html_only
    try:
        report_mod.generate_report(raw, report_dir, html_only=effective_html_only, mode=mode)
    except RuntimeError as exc:
        if effective_html_only:
            raise
        # PDF renderer unavailable on this machine (missing GTK, etc. -- see AGENTS.md).
        # Fall back to HTML-only rather than failing the whole run over presentation.
        pdf_ok = False
        report_mod.generate_report(raw, report_dir, html_only=True, mode=mode)
        print(f"(PDF rendering unavailable, wrote HTML-only report: {exc})", file=sys.stderr)
    # (mode here is always "demo" or "full" -- run_analysis_and_report is only ever reached
    # from the legacy paired-emotion path, which never carries "ci".)

    if detailed_available:
        shutil.copytree(VERIFIED_FULL_REPORT_DIR, report_dir / "detailed")

    return {"analysis": analysis, "demo_evidence": demo_evidence, "report_dir": report_dir, "pdf_ok": pdf_ok}


# --------------------------------------------------------------------------------------
# summaries
# --------------------------------------------------------------------------------------


def _finding_group_counts(comparison: dict) -> dict:
    if "comparison_withheld_reason" in comparison:
        return {"resolved": None, "remaining": None, "new": None,
                "withheld_reason": comparison["comparison_withheld_reason"]}
    return {
        "resolved": len(comparison["findings_resolved"]),
        "remaining": len(comparison["findings_remaining"]),
        "new": len(comparison["findings_newly_appearing"]),
        "withheld_reason": None,
    }


def print_full_summary(run_name: str, analysis: dict, report_dir: Path, status: str) -> None:
    cov1 = analysis["summary_v1"]["coverage"]
    cov2 = analysis["summary_v2"]["coverage"]
    counts = _finding_group_counts(analysis["comparison"])
    print()
    print("TEAM CHECKMATE -- RUN COMPLETE")
    print()
    print(f"Run: {run_name}")
    print()
    print(f"V1 coverage: {cov1['completed']} / {cov1['planned']}")
    print(f"V2 coverage: {cov2['completed']} / {cov2['planned']}")
    print()
    if counts["withheld_reason"]:
        print(f"Comparison withheld: {counts['withheld_reason']}")
    else:
        print(f"Resolved finding groups: {counts['resolved']}")
        print(f"Remaining finding groups: {counts['remaining']}")
        print(f"Newly demonstrated groups: {counts['new']}")
    print()
    print("Report:")
    print(f"  {report_dir / 'report.html'}")
    if (report_dir / "report.pdf").exists():
        print(f"  {report_dir / 'report.pdf'}")
    print()
    print(f"Status: {status}")


def print_demo_summary(run_name: str, demo_evidence: dict, report_dir: Path) -> None:
    print()
    print("TEAM CHECKMATE -- DEMO COMPLETE")
    print()
    failure = demo_evidence.get("featured_failure")
    print("Featured failure:")
    if failure:
        print(f"  {failure['category']} / {failure['subfamily']}")
        v1 = failure.get("v1") or {}
        v2 = failure.get("v2") or {}
        print(f"  V1: {'HTTP ' + str(v1.get('status_code')) if v1.get('status_code') else 'no response'} "
              f"{v1.get('outcome', '')}")
        if v2:
            print(f"  V2: {'HTTP ' + str(v2.get('status_code')) if v2.get('status_code') else 'no response'} "
                  f"{v2.get('outcome', '')}")
    else:
        print("  none found in this run")
    print()
    flip = demo_evidence.get("featured_prediction_flip")
    print("Featured prediction flip:")
    if flip:
        print(f"  {flip['original_label']} ({flip['original_confidence']:.3f}) -> "
              f"{flip['attacked_label']} ({flip['attacked_confidence']:.3f})")
        print(f"  Attack: {flip['subfamily']}")
    else:
        print("  none found in this run")
    print()
    print(f"Literal crash/unavailability demonstrated: "
          f"{'YES' if demo_evidence.get('literal_crash_case_available') else 'NO'}")
    print()
    print("Report:")
    print(f"  {report_dir / 'report.html'}")
    if (report_dir / "report.pdf").exists():
        print(f"  {report_dir / 'report.pdf'}")


# --------------------------------------------------------------------------------------
# reusable orchestration entry point
# --------------------------------------------------------------------------------------


def _run_legacy_experiment(mode: str, run_name: Optional[str] = None,
                           results_root: Optional[Path] = None,
                           progress_callback=None, *, html_only: bool = False) -> dict:
    """Run one full experiment. Callable from Python; no interactive prompts.

    Returns a structured dict describing what happened -- never raises for a
    endpoint-under-test failure (those are preserved data, per AGENTS.md), only for
    orchestration-level problems (endpoint never came up, preflight failed, etc).

    ``progress_callback``, if given, is called as ``callback(stage, message)`` at real
    orchestration transitions (see _emit_progress call sites here and in
    run_analysis_and_report()) -- initializing, starting_v1, attacking_v1, starting_v2,
    attacking_v2, analyzing, generating_results, complete. Optional and additive: every
    existing caller that omits it keeps the exact V3 behavior.
    """
    if mode not in ("full", "demo"):
        raise ValueError(f"unknown mode {mode!r}; expected 'full' or 'demo'")

    results_root = Path(results_root) if results_root is not None else RESULTS_ROOT
    if run_name is None:
        prefix = "demo" if mode == "demo" else "full"
        run_name = f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = results_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress_callback, "initializing", "Loading baselines and building the attack suite")
    baselines = sorted(load_baseline(), key=lambda b: b.baseline_id)
    attacks = build_full_suite(baselines)
    attack_index = {case.attack_id: case for case in attacks}

    attack_limit = compute_demo_attack_limit(baselines, attacks) if mode == "demo" else None
    # Demo-only, selection-level exclusion -- see DEMO_EXCLUDED_ATTACK_IDS. Full mode always
    # gets an empty skip list, so this never touches the full suite or its scoring.
    skip_ids = DEMO_EXCLUDED_ATTACK_IDS if mode == "demo" else ()

    terminations = {}
    for version in ("v1", "v2"):
        out_dir = run_dir / version
        _emit_progress(progress_callback, f"starting_{version}", f"Starting {version.upper()} endpoint")
        handle = start_endpoint(version, run_dir)
        try:
            label = "unhardened" if version == "v1" else "hardened"
            _emit_progress(progress_callback, f"attacking_{version}", f"Attacking the {label} endpoint")
            exit_code = run_suite(version, handle.url, out_dir, attack_limit=attack_limit, skip=skip_ids)
            terminations[version] = exit_code
        finally:
            handle.stop()

    report_result = run_analysis_and_report(run_dir, attack_index, html_only=html_only, mode=mode,
                                            progress_callback=progress_callback)
    analysis = report_result["analysis"]

    status = "COMPLETE" if all(code == 0 for code in terminations.values()) else "PARTIAL"

    result = {
        "mode": mode,
        "run_name": run_name,
        "run_dir": run_dir,
        "terminations": terminations,
        "status": status,
        "analysis": analysis,
        "demo_evidence": report_result["demo_evidence"],
        "report_dir": report_result["report_dir"],
        "report_html": report_result["report_dir"] / "report.html",
        "report_pdf": (report_result["report_dir"] / "report.pdf"
                       if report_result["pdf_ok"] else None),
        "pdf_generated": report_result["pdf_ok"],
    }

    if mode == "demo":
        print_demo_summary(run_name, report_result["demo_evidence"], report_result["report_dir"])
    else:
        print_full_summary(run_name, analysis, report_result["report_dir"], status)

    _emit_progress(progress_callback, "complete", "Experiment complete")
    return result


# --------------------------------------------------------------------------------------
# Stage 3 registry-driven orchestration
# --------------------------------------------------------------------------------------


def _write_json(path: Path, value: dict) -> None:
    """Write canonical UTF-8/LF JSON so artifact hashes are platform-independent."""
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_verification_case_set(path: Path, evaluation, plan) -> None:
    """Persist the exact selected order as a directly replayable case set."""
    baseline_ids = [key.split(":", 1)[1] for key in plan.selected_keys
                    if key.startswith("baseline:")]
    attack_ids = [key.split(":", 1)[1] for key in plan.selected_keys
                  if key.startswith("attack:")]
    _write_json(path, {
        "case_set_id": f"run_{evaluation.evaluation_id.replace('.', '_')}",
        "selection_version": 1,
        "suite_id": evaluation.suite_id,
        "baseline_ids": baseline_ids,
        "attack_ids": attack_ids,
        "order": list(plan.selected_keys),
        "exclusions": [
            {"case_key": key, "reason": "not selected by this run mode"}
            for key in [*plan.skipped_keys, *plan.limit_excluded, *plan.deselected]
        ],
    })


def _safe_run_name(value: Optional[str], mode: str) -> str:
    if value is None:
        return f"{mode}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    if not value or value in {".", ".."} or any(c in value for c in "/\\"):
        raise ValueError("run_name must be a nonempty name, not a path")
    return value


def _case_set_path(case_set_id: Optional[str]) -> Optional[Path]:
    if case_set_id is None:
        return None
    path = ROOT / "analysis" / "case_sets" / f"{case_set_id}.json"
    if not path.is_file():
        raise RuntimeError(f"case set {case_set_id!r} is not available at {path.relative_to(ROOT)}")
    return path


def _runner_argv(*, target_id: str, target_url: str, evaluation, out_dir: Path,
                 run_id: str, mode: str, case_set_path: Optional[Path],
                 attack_limit: Optional[int]) -> list[str]:
    argv = [
        "--target", target_url, "--target-id", target_id,
        "--suite", evaluation.suite_id, "--evaluation-id", evaluation.evaluation_id,
        "--parent-run-id", run_id, "--out", str(out_dir),
    ]
    if case_set_path is not None:
        argv += ["--case-set", str(case_set_path)]
    elif attack_limit is not None:
        argv += ["--limit", str(attack_limit)]
        for attack_id in DEMO_EXCLUDED_ATTACK_IDS:
            argv += ["--skip", attack_id]
    return argv


def _plan_evaluation(registry, evaluation, evaluation_dir: Path, run_id: str,
                     mode: str, case_set_path: Optional[Path],
                     attack_limit: Optional[int] = None):
    target_id = evaluation.target_ids[0]
    target = registry.target(target_id)
    argv = _runner_argv(
        target_id=target_id,
        target_url=f"http://127.0.0.1:{target.port}",
        evaluation=evaluation,
        out_dir=evaluation_dir / target_id,
        run_id=run_id,
        mode=mode,
        case_set_path=case_set_path,
        attack_limit=attack_limit,
    )
    args = runner_mod.build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix=".plan-", dir=evaluation_dir) as staging_name:
        return runner_mod.plan_run(args, evaluation_dir, Path(staging_name))


def _strip_runtime_objects(document: dict) -> dict:
    return {key: value for key, value in document.items() if key != "findings_by_target"}


def _load_declared_results(path: Path, labels: Sequence[str]) -> tuple[list[RunResult], object]:
    """Load Stage 3 rows with their registry label space.

    ``analysis.load_results`` deliberately supports historical artifacts and therefore
    validates before it knows a declared target's labels. The registry orchestrator has
    that identity already, so it parses the same strict JSONL shape and supplies the
    label space at the validation boundary instead of falling back to emotion labels.
    """
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text, object_pairs_hook=analysis_mod._unique_object)
                rows.append(RunResult(**raw))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path} line {line_number} is not a valid RunResult: {exc}") from exc
    identity = analysis_mod.validation.resolve_identity(rows, labels=labels)
    analysis_mod.validation.validate_rows(rows, labels=labels, identity=identity)
    return rows, identity


def _target_analysis_inputs(registry, evaluation, target_dir: Path):
    manifest_bytes = (target_dir / "manifest.json").read_bytes()
    manifest = json.loads(
        manifest_bytes.decode("utf-8"), object_pairs_hook=analysis_mod._unique_object
    )
    analysis_mod.validation.validate_manifest(manifest)
    meta = analysis_mod.load_run_meta(target_dir / "run_meta.json")
    labels = registry.model_for(meta["target_id"]).labels
    rows, identity = _load_declared_results(target_dir / "results.jsonl", labels)
    analysis_mod.validation.validate_run(
        rows, meta, manifest, identity.version, hashlib.sha256(manifest_bytes).hexdigest(),
        labels=labels, identity=identity,
    )
    drift_summary = analysis_mod.drift.compute_drift(rows, manifest, labels=labels, identity=identity)
    drift_by_attack = {record.attack_id: record for record in drift_summary.records}
    evaluations = [
        analysis_mod.evaluate_case(row, manifest[row.attack_id], drift_by_attack.get(row.attack_id))
        for row in rows if row.case_type == "attack"
    ]
    return manifest_bytes, manifest, rows, meta, evaluations


def _verification_case_set_path(evaluation, evaluation_dir: Path) -> str:
    if evaluation.case_set_id:
        return f"analysis/case_sets/{evaluation.case_set_id}.json"
    path = evaluation_dir / "verification_case_set.json"
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _analyze_target(registry, evaluation, target_dir: Path, evaluation_dir: Path):
    manifest_bytes, manifest, rows, meta, _evaluations = _target_analysis_inputs(
        registry, evaluation, target_dir
    )
    labels = registry.model_for(meta["target_id"]).labels
    identity = analysis_mod.validation.resolve_identity(rows, labels=labels)
    target_analysis = analysis_mod.analyze_version(
        rows, manifest, labels=labels, identity=identity
    )
    target_analysis.version = identity.version
    summary = analysis_mod.build_version_summary(target_analysis, meta, identity)
    case_set_file = _verification_case_set_path(evaluation, evaluation_dir)
    by_id = {item["finding"]["finding_id"]: item for item in summary["findings"]}
    rules = analysis_remediation.load_rules()
    for finding in target_analysis.findings:
        finding_meta = target_analysis.finding_meta[finding.finding_id]
        detail = analysis_remediation.build_remediation_detail(
            finding=finding,
            failure_mode=finding_meta["failure_mode"],
            subfamily=finding_meta["subfamily"],
            rows=rows,
            target_id=meta["target_id"],
            case_set_file=case_set_file,
            rules=rules,
        )
        concise_remediation = analysis_remediation.build_finding_remediation_string(
            detail, finding
        )
        observed = detail["observed"]
        if isinstance(observed, dict):
            statuses = ", ".join(
                f"HTTP {status}: {count}" if status != "no response" else f"no response: {count}"
                for status, count in observed.get("status_distribution", {}).items()
            ) or "no cited response rows"
            detail["observed"] = (
                f"{observed.get('rows_available', 0)} of "
                f"{observed.get('affected_case_count', 0)} cited case row(s) were available; "
                f"recorded outcomes: {statuses}; post-request health-check failures: "
                f"{len(observed.get('health_check_failures_after_request', []))}."
            )
        item = by_id[finding.finding_id]
        item["remediation_detail"] = detail
        item["finding"]["remediation"] = concise_remediation
    return {
        "manifest_bytes": manifest_bytes,
        "manifest": manifest,
        "rows": rows,
        "meta": meta,
        "identity": identity,
        "analysis": target_analysis,
        "summary": summary,
    }


def _core_coverage(registry, evaluation, target_dir: Path) -> dict:
    manifest_bytes, manifest, _rows, meta, evaluations = _target_analysis_inputs(
        registry, evaluation, target_dir
    )
    entries = {}
    versions = set()
    for attack_id, value in manifest.items():
        version = value.get("coverage_map_version")
        if version:
            versions.add(version)
        entries[attack_id] = {
            "family": value.get("family", ""),
            "subfamily": value.get("subfamily", ""),
            "coverage_class": value.get("coverage_class"),
            "controls_targeted": value.get("controls_targeted", []),
            "coverage_rationale": value.get("coverage_rationale"),
            "coverage_map_version": version,
        }
    if len(versions) != 1:
        raise ValueError(f"{evaluation.evaluation_id}: manifest must declare one coverage-map version")
    source_sha = hashlib.sha256(manifest_bytes).hexdigest()
    coverage_map = analysis_coverage.load_coverage_map(
        {"coverage_map_version": next(iter(versions)), "entries": entries,
         "is_overlay": False},
        sha256=source_sha,
        source=str(target_dir / "manifest.json"),
    )
    case_ids = meta["case_ids"]
    attacks_only = lambda values: [value.split(":", 1)[1] for value in values if value.startswith("attack:")]
    return analysis_coverage.build_coverage(
        planned_attack_ids=attacks_only(case_ids["planned"]),
        selected_attack_ids=attacks_only(case_ids["selected"]),
        completed_attack_ids=attacks_only(case_ids["completed"]),
        evaluations=evaluations,
        coverage_map=coverage_map,
        require_declaration=True,
    )


def _oces_block(registry, evaluation, evaluation_dir: Path) -> dict:
    outcomes_by_target = {}
    for target_id in evaluation.target_ids:
        target_dir = evaluation_dir / target_id
        _manifest_bytes, manifest, rows, _meta, _evaluations = _target_analysis_inputs(
            registry, evaluation, target_dir
        )
        baselines = {row.baseline_id: row for row in rows if row.case_type == "baseline"}
        attacks = {row.attack_id: row for row in rows if row.case_type == "attack"}
        outcomes_by_target[target_id] = [
            analysis_oces.classify_case(
                case_id=attack_id,
                family=value.get("declared_family") or value.get("family"),
                target_id=target_id,
                meta=value,
                clean=baselines.get(value.get("baseline_id")),
                attacked=attacks.get(attack_id),
            )
            for attack_id, value in manifest.items()
        ]
    provenance = ROOT / "attacks" / "data" / "oces" / "freeze_content_hashes.json"
    provenance_bytes = provenance.read_bytes()
    snapshot = evaluation_dir / "oces_freeze_content_hashes.json"
    snapshot.write_bytes(provenance_bytes)
    return analysis_oces.build_oces_block(
        outcomes_by_target=outcomes_by_target,
        seed_hashes={
            "path": snapshot.name,
            "sha256": hashlib.sha256(provenance_bytes).hexdigest(),
            "document": json.loads(provenance_bytes.decode("utf-8")),
        },
    )


def _analyze_evaluation(registry, evaluation, evaluation_dir: Path) -> dict:
    targets = list(evaluation.target_ids)
    analyzed = {
        target_id: _analyze_target(
            registry, evaluation, evaluation_dir / target_id, evaluation_dir
        )
        for target_id in targets
    }
    if evaluation.kind == "paired":
        left, right = targets
        if analyzed[left]["manifest_bytes"] != analyzed[right]["manifest_bytes"]:
            raise ValueError("paired target manifest files differ; one oracle set cannot score both")
        left_attacks = {
            row.attack_id: row for row in analyzed[left]["rows"] if row.case_type == "attack"
        }
        for row in analyzed[right]["rows"]:
            if (row.case_type == "attack" and row.attack_id in left_attacks
                    and row.baseline_id != left_attacks[row.attack_id].baseline_id):
                raise ValueError(f"{row.attack_id}: baseline association differs across targets")
        comparison = analysis_mod.build_comparison_summary(
            analyzed[left]["analysis"], analyzed[right]["analysis"],
            analyzed[left]["meta"], analyzed[right]["meta"],
        )
    else:
        comparison = None
    block = analysis_mod.build_evaluation_block(
        evaluation_id=evaluation.evaluation_id,
        kind=evaluation.kind,
        task_id=evaluation.task_id,
        suite_id=evaluation.suite_id,
        targets=targets,
        summaries={target_id: analyzed[target_id]["summary"] for target_id in targets},
        comparison=comparison,
        coverage=None,
        oces=None,
    )
    baseline_path = ROOT / registry.baseline_file_for(evaluation.evaluation_id)
    block["baseline_file"] = registry.baseline_file_for(evaluation.evaluation_id)
    block["baseline_file_sha256"] = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    if evaluation.suite_id == "core":
        per_target = {
            target_id: _core_coverage(registry, evaluation, evaluation_dir / target_id)
            for target_id in evaluation.target_ids
        }
        if evaluation.kind == "single":
            block["coverage"] = per_target[evaluation.target_ids[0]]
        else:
            first = per_target[evaluation.target_ids[0]]
            block["coverage"] = {
                "coverage_map": first["coverage_map"],
                "by_target": per_target,
                "interpretation": first["interpretation"],
            }
    else:
        block["oces"] = _oces_block(registry, evaluation, evaluation_dir)
    return block


# analysis.analyze.LIMITATION_NOTES is emitted unconditionally onto every target's summary
# (per-target, regardless of whether that target has a paired counterpart) -- this one note
# is written in V1/V2 hardening terms and is not applicable to a run that never touches a
# paired evaluation (v6.2: a sentiment-only report must never say "V2" or "hardening").
# Matched by content, not by tuple index, so a reordering of the frozen tuple upstream can't
# silently break the filter.
_PAIRED_ONLY_LIMITATION_MARKER = "V2's defenses are application-layer only"


def _applicable_limitations(analysis_blocks: list) -> list:
    """The run-wide, deduplicated limitations list, minus any paired-only (V1/V2 hardening)
    note when this run contains no paired evaluation at all. Never rewrites or reorders the
    notes that do apply -- only omits ones that describe a comparison this run cannot have."""
    has_paired = any(block["kind"] == "paired" for block in analysis_blocks)
    notes = (
        note for block in analysis_blocks
        for target_id in block["targets"]
        for note in block["summaries"][target_id].get("limitations", [])
        if has_paired or _PAIRED_ONLY_LIMITATION_MARKER not in note
    )
    return list(dict.fromkeys(notes))


def _app_commit_unavailable_reason(provenance: dict) -> Optional[str]:
    """An explicit reason for a missing application commit (v6.2) -- never a silent
    "unknown", a branch name, or the remote head standing in for the real commit."""
    if provenance.get("app_commit"):
        return None
    return (
        "Git metadata was unavailable in this environment when the run started "
        "(no .git directory, git not on PATH, or the git command failed); no application "
        "commit could be recorded for this run."
    )


def _registry_snapshot(registry) -> dict:
    return {
        "registry_version": registry.registry_version,
        "source_path": str(Path(registry.source_path).relative_to(ROOT).as_posix()),
        "source_sha256": registry.source_sha256,
    }


def _public_evaluation_entry(registry, evaluation, evaluation_dir: Path) -> dict:
    return {
        "evaluation_id": evaluation.evaluation_id,
        "kind": evaluation.kind,
        "task_id": evaluation.task_id,
        "suite_id": evaluation.suite_id,
        "declared_families": list(evaluation.declared_families),
        "case_set_id": evaluation.case_set_id,
        "baseline_file": registry.baseline_file_for(evaluation.evaluation_id),
        "target_dirs": {
            target_id: str((evaluation_dir / target_id).resolve())
            for target_id in evaluation.target_ids
        },
    }


def _run_registry_experiment(mode: str, run_name: Optional[str], results_root: Optional[Path],
                             progress_callback, evaluation_ids: Sequence[str],
                             html_only: bool) -> dict:
    if mode not in ("full", "demo", "ci"):
        raise ValueError(f"unknown mode {mode!r}; expected 'full', 'demo', or 'ci'")
    if not evaluation_ids or len(set(evaluation_ids)) != len(evaluation_ids):
        raise ValueError("evaluation_ids must be a nonempty list without duplicates")

    registry = target_registry.load_registry()
    evaluations = [registry.evaluation(evaluation_id) for evaluation_id in evaluation_ids]
    for evaluation in evaluations:
        if mode == "ci" and evaluation.mode != "ci":
            raise ValueError(f"{evaluation.evaluation_id!r} is not an internal CI evaluation")
        if mode != "ci" and evaluation.mode == "ci":
            raise ValueError(f"{evaluation.evaluation_id!r} may run only in ci mode")
        if mode == "demo" and evaluation.suite_id != "core":
            raise ValueError("public demos support the core suites; additional evaluations are report-only")
        target_registry.require_runnable(registry, evaluation.evaluation_id)

    run_id = uuid.uuid4().hex[:16]
    display_name = _safe_run_name(run_name, mode)
    root = (Path(results_root) if results_root is not None else RESULTS_ROOT).resolve()
    run_dir = root / f"{display_name}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "runs").mkdir()
    registry_bytes = Path(registry.source_path).read_bytes()
    require_hash = hashlib.sha256(registry_bytes).hexdigest()
    if require_hash != registry.source_sha256:
        raise RuntimeError("target registry changed while the run was being created")
    (run_dir / "registry.json").write_bytes(registry_bytes)

    # Obtained once, here, and reused for every evaluation in this orchestration call (never
    # re-derived per evaluation or asked of the report renderer) so multiple evaluations in one
    # run always agree on the same application commit (v6.2 requirement).
    provenance = runner_mod.code_provenance(ROOT)
    app_commit_unavailable_reason = _app_commit_unavailable_reason(provenance)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index_entries = []
    for evaluation in evaluations:
        evaluation_dir = run_dir / "runs" / evaluation.evaluation_id.replace(".", "_")
        evaluation_dir.mkdir()
        index_entries.append(_public_evaluation_entry(registry, evaluation, evaluation_dir))
    persisted_entries = json.loads(json.dumps(index_entries))
    for entry in persisted_entries:
        entry["target_dirs"] = {
            target_id: Path(directory).relative_to(run_dir).as_posix()
            for target_id, directory in entry["target_dirs"].items()
        }
    run_index = {
        "run_id": run_id,
        "run_name": display_name,
        "created_at_utc": created,
        "app_commit": provenance["app_commit"],
        "dirty": provenance["dirty"],
        "mode": mode,
        "status": "running",
        "registry": _registry_snapshot(registry),
        "evaluations": persisted_entries,
    }
    _write_json(run_dir / "run.json", run_index)

    _emit_progress(progress_callback, "initializing", "Preparing the selected evaluation")
    analysis_blocks = []
    terminations = {}
    memory = {}
    try:
        for evaluation, public_entry in zip(evaluations, index_entries):
            evaluation_dir = Path(next(iter(public_entry["target_dirs"].values()))).parent
            case_path = _case_set_path(evaluation.case_set_id)
            if case_path is not None:
                selection_bytes = case_path.read_bytes()
                (evaluation_dir / "case_selection.json").write_bytes(selection_bytes)
                public_entry["case_selection_sha256"] = hashlib.sha256(selection_bytes).hexdigest()
                next(item for item in persisted_entries
                     if item["evaluation_id"] == evaluation.evaluation_id)["case_selection_sha256"] = public_entry["case_selection_sha256"]
            plan = _plan_evaluation(registry, evaluation, evaluation_dir, run_id, mode, case_path)
            attack_limit = (
                compute_demo_attack_limit(plan.baselines, plan.attacks)
                if mode == "demo" else None
            )
            if attack_limit is not None:
                # The reusable plan must already contain the exact demo selection. The
                # first build above discovers the content-derived limit; the second is
                # the one and only plan reused by every target in the evaluation.
                plan = _plan_evaluation(
                    registry, evaluation, evaluation_dir, run_id, mode, case_path,
                    attack_limit=attack_limit,
                )
            if case_path is None:
                _write_verification_case_set(
                    evaluation_dir / "verification_case_set.json", evaluation, plan
                )
            for target_id in evaluation.target_ids:
                target = registry.target(target_id)
                target_dir = Path(public_entry["target_dirs"][target_id])
                stage = f"starting_{target_id}"
                _emit_progress(progress_callback, stage, f"Starting {target_id.replace('_', ' ')}")
                handle = start_target(target_id, evaluation_dir, registry)
                started = time.monotonic()
                try:
                    _emit_progress(progress_callback, f"attacking_{target_id}",
                                   f"Sending the {evaluation.suite_id} suite to {target_id.replace('_', ' ')}")
                    argv = _runner_argv(
                        target_id=target_id, target_url=handle.url, evaluation=evaluation,
                        out_dir=target_dir, run_id=run_id, mode=mode,
                        case_set_path=case_path, attack_limit=attack_limit,
                    )
                    exit_code = runner_mod.main(argv, reuse_plan=plan)
                    if exit_code not in (0, 1):
                        raise RuntimeError(
                            f"runner for {target_id} exited with configuration/execution code {exit_code}"
                        )
                    terminations[target_id] = exit_code
                finally:
                    handle.stop()
                    memory[target_id] = {
                        "peak_process_memory_bytes": handle.peak_memory_bytes,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "measurement_scope": "uvicorn endpoint process; sequential startup does not prove only one model was resident",
                    }
            _emit_progress(progress_callback, "analyzing", f"Analyzing {evaluation.evaluation_id}")
            analysis_blocks.append(_analyze_evaluation(registry, evaluation, evaluation_dir))

        analysis_document = {
            "schema_version": 3,
            "contracts_version": "3.0.0",
            "run_identity": {
                "run_id": run_id, "run_name": display_name,
                "created_at_utc": created, "app_commit": provenance["app_commit"],
                "app_commit_unavailable_reason": app_commit_unavailable_reason,
                "dirty": provenance["dirty"], "registry_sha256": registry.source_sha256,
            },
            "evaluations": analysis_blocks,
            "limitations": _applicable_limitations(analysis_blocks),
        }
        raw = (json.dumps(analysis_document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        _emit_progress(progress_callback, "generating_results", "Generating the report")
        report_dir = run_dir / "report"
        # Live Demo reports never expose a PDF -- v6.1: a Download PDF button only belongs on
        # the full/verified technical report, and generating a file with no linked consumer for
        # every demo run was pure waste. Only "full" mode ever attempts PDF rendering. "ci" is
        # not a report presentation mode (report.generate only knows "full"/"demo"); CI runs
        # get the "full" report style, same as before this fix.
        report_mode = "demo" if mode == "demo" else "full"
        effective_html_only = html_only or mode == "demo"
        pdf_ok = not effective_html_only
        try:
            report_mod.generate_report(raw, report_dir, html_only=effective_html_only, mode=report_mode)
        except RuntimeError as exc:
            if effective_html_only:
                raise
            pdf_ok = False
            report_mod.generate_report(raw, report_dir, html_only=True, mode=report_mode)
            print(f"(PDF rendering unavailable, wrote HTML-only report: {exc})", file=sys.stderr)

        status = "COMPLETE" if all(value == 0 for value in terminations.values()) else "PARTIAL"
        run_index.update(status=status.lower(), completed_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         resources=memory,
                         artifacts={"analysis_json": "report/analysis.json", "report_html": "report/report.html",
                                    "report_pdf": "report/report.pdf" if pdf_ok else None})
        _write_json(run_dir / "run.json", run_index)
        result = {
            "mode": mode, "run_id": run_id, "run_name": display_name,
            "run_dir": run_dir, "evaluations": index_entries,
            "terminations": terminations, "status": status,
            "analysis": analysis_document, "analysis_json": report_dir / "analysis.json",
            "report_dir": report_dir, "report_html": report_dir / "report.html",
            "report_pdf": report_dir / "report.pdf" if pdf_ok else None,
            "pdf_generated": pdf_ok, "resources": memory,
        }
        _emit_progress(progress_callback, "complete", "Experiment complete")
        return result
    except Exception as exc:
        run_index.update(status="execution_error", completed_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         error={"type": type(exc).__name__, "message": str(exc)}, resources=memory)
        _write_json(run_dir / "run.json", run_index)
        raise


def run_experiment(mode: str, run_name: Optional[str] = None,
                   results_root: Optional[Path] = None, progress_callback=None,
                   *, evaluation_ids: Optional[Sequence[str]] = None,
                   html_only: bool = False) -> dict:
    """Run an experiment without opening a browser.

    ``evaluation_ids=None`` retains the original paired-emotion call path. Explicit
    identities use the Stage 3 registry, including the single-target sentiment and
    internal CI journeys. Browser opening remains exclusively in :func:`main`.
    """
    if evaluation_ids is None:
        legacy = _run_legacy_experiment(
            mode, run_name=run_name, results_root=results_root,
            progress_callback=progress_callback, html_only=html_only,
        )
        legacy["run_id"] = legacy.get("run_id") or uuid.uuid4().hex[:16]
        legacy["evaluations"] = [{
            "evaluation_id": "emotion.core", "kind": "paired", "task_id": "emotion_7",
            "suite_id": "core", "declared_families": list(CORE_FAMILIES),
            "case_set_id": None, "baseline_file": "baseline/baseline.json",
            "target_dirs": {
                "emotion_v1": str((legacy["run_dir"] / "v1").resolve()),
                "emotion_v2": str((legacy["run_dir"] / "v2").resolve()),
            },
        }]
        return legacy
    return _run_registry_experiment(
        mode, run_name, results_root, progress_callback, list(evaluation_ids), html_only,
    )


# --------------------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_all", description="Run the full Team Checkmate experiment end to end."
    )
    parser.add_argument("--mode", required=True, choices=("full", "demo", "ci"))
    parser.add_argument("--run-name", default=None,
                        help="output subdirectory under results/; default is a timestamped name")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the generated report in the default browser "
                             "(CI/Docker/servers/automated tests)")
    parser.add_argument("--evaluation", action="append", dest="evaluation_ids",
                        help="trusted registry evaluation id; repeat to run sequentially")
    parser.add_argument("--html-only", action="store_true",
                        help="generate HTML/JSON without loading the PDF renderer")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_experiment(mode=args.mode, run_name=args.run_name,
                                evaluation_ids=args.evaluation_ids,
                                html_only=args.html_only)
    except (RuntimeError, ValueError) as exc:
        print(f"\nrun_all failed: {exc}", file=sys.stderr)
        return 1

    # Browser opening is CLI presentation only -- run_experiment() never does this, so
    # a future Hugging Face app calling run_experiment() directly cannot trigger it.
    if not args.no_open:
        report_html = result["report_html"]
        try:
            opened = webbrowser.open(report_html.resolve().as_uri())
            if not opened:
                print(f"(could not open a browser automatically; report is at {report_html})")
        except webbrowser.Error as exc:
            print(f"(could not open a browser automatically ({exc}); report is at {report_html})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Public FastAPI web layer for Team Checkmate's Red Lab product (System V4, V5.1 UI polish).

Thin deployment layer only -- no attack/runner/analysis/report logic lives here. The
"Run Live Demo" button ultimately calls ``run_all.run_experiment(mode="demo", ...)``
directly, in-process, never by shelling out to ``python run_all.py``. See AGENTS.md and
HANDOFF.md for the project's architecture and ownership rules; this file and the rest of
``web/`` are the deployment layer, not owned by any existing component folder.

Runtime shape: one uvicorn worker serving :7860 publicly. A single background thread runs
at most one ``run_experiment()`` at a time, guarded by a process-local lock -- there is no
database or task queue, because a single Hugging Face Space container only ever needs to
protect its own internal V1/V2 ports (:8000/:8001) from two visitors racing each other.
"""

from __future__ import annotations

import base64
import logging
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import run_all  # noqa: E402
from report.generate import (  # noqa: E402
    CREATOR_NAME, PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION_LABEL,
)
from web import lab as lab_module  # noqa: E402
from web import progress as progress_module  # noqa: E402

logger = logging.getLogger("team_checkmate.web")

LOGO_PATH = ROOT / "Team Checkmate Logo.png"
# The real, approved Red Lab logo (System V5.1). Not recreated or modified here -- read
# verbatim from the repository root, same embedding pattern as the Team Checkmate logo.
RED_LAB_LOGO_PATH = ROOT / "Red Lab Adversarial Testing Redefined.png"

RESULTS_MOUNT = "/results"
VERIFIED_MOUNT = "/verified-full"
TECHNICAL_REPORT_MOUNT = "/technical-report"

# Real orchestration transitions only -- see run_all.py's _emit_progress call sites for
# what each stage actually means. Order here must match the order run_experiment() emits.
# v6.1 Phase 2: paired (emotion) vs single-target (sentiment) get distinct descriptors --
# the single-target flow has no V2 phase at all, so it must never share the paired stage list.
_PAIRED_DEMO_STAGE_ORDER = (
    "initializing", "starting_v1", "attacking_v1", "starting_v2", "attacking_v2",
    "analyzing", "generating_results", "complete",
)
_PAIRED_DEMO_STAGE_PERCENT = dict(zip(_PAIRED_DEMO_STAGE_ORDER, (5, 15, 30, 50, 65, 82, 92, 100)))
_PAIRED_DEMO_LABELS = {
    "initializing": "Initializing toolkit",
    "starting_v1": "Starting V1",
    "attacking_v1": "Attacking unhardened endpoint",
    "starting_v2": "Starting V2",
    "attacking_v2": "Testing hardened endpoint",
    "analyzing": "Analyzing evidence",
    "generating_results": "Generating results",
    "complete": "Complete",
}

# The registry orchestration for a single target only ever emits one combined
# starting_{target}/attacking_{target} pair (see run_all.py's _run_registry_experiment) --
# there is no separate backend signal for "clean reference" vs "adversarial variants", so
# those two display rows below both map onto the one real "attacking_target" transition
# rather than inventing a fake intermediate progress step.
_SINGLE_DEMO_STAGE_ORDER = (
    "initializing", "starting_target", "attacking_target",
    "analyzing", "generating_results", "complete",
)
_SINGLE_DEMO_STAGE_PERCENT = dict(zip(_SINGLE_DEMO_STAGE_ORDER, (5, 20, 55, 80, 92, 100)))


def _demo_descriptor(evaluation_id: str, target_ids: list) -> dict:
    if evaluation_id == "sentiment.core":
        target_id = target_ids[0] if target_ids else "sentiment_v1"
        return progress_module.descriptor(
            evaluation_id=evaluation_id, kind="single", target_ids=target_ids,
            same_model_note=None,
            footer_note="Single-target sentiment evaluation; no V1/V2 comparison is implied.",
            cards=[progress_module.card(
                "target", "Sentiment — Configured Target",
                f"{target_id} · single-target evaluation",
                start_stage="starting_target", end_stage="attacking_target",
            )],
            stage_order=list(_SINGLE_DEMO_STAGE_ORDER), stage_percent=_SINGLE_DEMO_STAGE_PERCENT,
            stages=[
                progress_module.stage("initializing", "Initializing toolkit"),
                progress_module.stage("starting_target", "Starting sentiment target"),
                progress_module.stage("clean_reference", "Running clean reference",
                                       maps_to="attacking_target"),
                progress_module.stage("adversarial_variants", "Testing sentiment adversarial variants",
                                       maps_to="attacking_target"),
                progress_module.stage("analyzing", "Analyzing observations"),
                progress_module.stage("generating_results", "Generating results"),
                progress_module.stage("complete", "Complete"),
            ],
        )
    return progress_module.descriptor(
        evaluation_id=evaluation_id, kind="paired", target_ids=target_ids,
        same_model_note="Two endpoint configurations",
        footer_note="Same underlying AI model in both cases — only the endpoint hardening differs.",
        cards=[
            progress_module.card(
                "v1", "V1 — Unhardened Endpoint", "No application-layer hardening.",
                start_stage="starting_v1", end_stage="attacking_v1",
            ),
            progress_module.card(
                "v2", "V2 — Hardened Endpoint",
                "Input validation, length controls, exception handling and normalization.",
                start_stage="starting_v2", end_stage="attacking_v2",
            ),
        ],
        stage_order=list(_PAIRED_DEMO_STAGE_ORDER), stage_percent=_PAIRED_DEMO_STAGE_PERCENT,
        stages=[progress_module.stage(s, _PAIRED_DEMO_LABELS[s]) for s in _PAIRED_DEMO_STAGE_ORDER],
    )


def _real_stage_alias(evaluation_id: str, raw_stage: str) -> str:
    """Map a raw orchestration stage (run_all.py's f"starting_{target_id}" etc.) onto this
    evaluation's descriptor stage id. Kept in one place so the display stage list and the
    percent/index computed from it can never disagree about what a raw stage means."""
    if evaluation_id == "sentiment.core":
        aliases = {
            "starting_sentiment_v1": "starting_target",
            "attacking_sentiment_v1": "attacking_target",
        }
    else:
        aliases = {
            "starting_emotion_v1": "starting_v1", "attacking_emotion_v1": "attacking_v1",
            "starting_emotion_v2": "starting_v2", "attacking_emotion_v2": "attacking_v2",
        }
    return aliases.get(raw_stage, raw_stage)


def _data_uri(path: Path, label: str) -> str:
    if not path.exists():
        raise RuntimeError(f"Required {label} asset not found: {path}")
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _logo_data_uri() -> str:
    return _data_uri(LOGO_PATH, "Team Checkmate logo")


def _red_lab_logo_data_uri() -> str:
    return _data_uri(RED_LAB_LOGO_PATH, "Red Lab logo")


def _idle_state() -> dict:
    return {
        "status": "idle", "state": "idle", "stage": None, "stage_index": -1,
        "percent": 0, "message": "",
        "run_id": None, "evaluation_id": None, "target_ids": [], "results": None,
        "run_name": None, "started_at": None, "completed_at": None,
        "result_url": None, "report_url": None, "error": None,
    }


# Shared with web/lab.py's Live Red-Team Lab job (System V5.4): both flows start V1/V2 on the
# same fixed ports (run_all.ENDPOINT_SPECS), so a demo run and a lab run must never overlap.
# Aliasing lab_module.JOB_LOCK here (instead of constructing a second Lock()) is the only
# change this module makes to its own demo logic -- every existing demo route/test still works
# unchanged, since a threading.Lock behaves identically regardless of which module built it.
_job_lock = lab_module.JOB_LOCK
_job_state = _idle_state()


def _reset_state_for_tests() -> None:
    """Test-only helper -- not exposed via any route. Restores a clean idle job state."""
    global _job_state
    with _job_lock:
        _job_state = _idle_state()


def _snapshot() -> dict:
    with _job_lock:
        return dict(_job_state)


def _generate_run_name() -> str:
    # Server-generated only -- the public API never accepts a caller-supplied run name or
    # path (see AGENTS.md / the V4 brief section on API security).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"hf_demo_{stamp}_{secrets.token_hex(3)}"


def _make_progress_callback(run_id: str, evaluation_id: str):
    descriptor = _demo_descriptor(evaluation_id, [])
    stage_order = descriptor["stage_order"]
    stage_percent = descriptor["stage_percent"]

    def callback(stage: str, message: str) -> None:
        display_stage = _real_stage_alias(evaluation_id, stage)
        with _job_lock:
            if _job_state.get("run_id") != run_id or _job_state["status"] != "running":
                return
            _job_state["stage"] = display_stage
            if display_stage in stage_order:
                _job_state["stage_index"] = stage_order.index(display_stage)
                _job_state["percent"] = stage_percent[display_stage]
            _job_state["message"] = message
    return callback


def _run_job(run_name: str, run_id: str, evaluation_id: str, mode: str) -> None:
    descriptor = _demo_descriptor(evaluation_id, [])
    try:
        result = run_all.run_experiment(
            mode=mode, run_name=run_name,
            progress_callback=_make_progress_callback(run_id, evaluation_id),
            evaluation_ids=[evaluation_id],
        )
        report_html = Path(result["report_html"]).resolve()
        rel = report_html.relative_to(Path(run_all.RESULTS_ROOT).resolve())
        result_url = f"{RESULTS_MOUNT}/{rel.as_posix()}"
        with _job_lock:
            if _job_state.get("run_id") != run_id:
                return
            analysis_path = result.get("analysis_json")
            analysis_url = None
            if analysis_path is not None:
                analysis_json = Path(analysis_path).resolve()
                analysis_rel = analysis_json.relative_to(Path(run_all.RESULTS_ROOT).resolve())
                analysis_url = f"{RESULTS_MOUNT}/{analysis_rel.as_posix()}"
            _job_state["status"] = _job_state["state"] = "complete"
            _job_state["stage"] = "done"
            _job_state["stage_index"] = len(descriptor["stage_order"]) - 1
            _job_state["percent"] = 100
            _job_state["message"] = "Run complete."
            _job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _job_state["result_url"] = _job_state["report_url"] = result_url
            _job_state["results"] = {"analysis_json": analysis_url} if analysis_url else None
    except Exception:  # noqa: BLE001 -- orchestration failure; never let it kill the thread silently
        logger.exception("Live demo run failed for run_name=%s", run_name)
        with _job_lock:
            if _job_state.get("run_id") != run_id:
                return
            _job_state["status"] = _job_state["state"] = "failed"
            _job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _job_state["error"] = "The live attack run failed. Please try again in a moment."


app = FastAPI(title="Team Checkmate", docs_url=None, redoc_url=None)


def _inline_json_response(path: Path) -> Response:
    # Source JSON must always open inline, never download (System V5.1 fix). The generic
    # StaticFiles mounts below are fine for report.html/report.pdf, but analysis.json gets
    # its own tiny, path-restricted route so its Content-Type (with charset) and the
    # absence of Content-Disposition are guaranteed, independent of the host OS's
    # mimetypes registry. This only ever serves the one filename at controlled, pre-existing
    # Red Lab result/report locations -- it accepts no caller-supplied filesystem path.
    if not path.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return Response(content=path.read_bytes(), media_type="application/json; charset=utf-8")


@app.get("/results/{run_name}/report/analysis.json")
def results_analysis_json(run_name: str) -> Response:
    root = Path(run_all.RESULTS_ROOT).resolve()
    candidate = (root / run_name / "report" / "analysis.json").resolve()
    if not candidate.is_relative_to(root):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return _inline_json_response(candidate)


@app.get("/verified-full/analysis.json")
def verified_full_analysis_json() -> Response:
    return _inline_json_response(run_all.VERIFIED_FULL_REPORT_DIR / "analysis.json")


Path(run_all.RESULTS_ROOT).mkdir(parents=True, exist_ok=True)
app.mount(RESULTS_MOUNT, StaticFiles(directory=str(run_all.RESULTS_ROOT)), name="results")

if run_all.VERIFIED_FULL_REPORT_DIR.exists():
    app.mount(VERIFIED_MOUNT, StaticFiles(directory=str(run_all.VERIFIED_FULL_REPORT_DIR)), name="verified_full")

if run_all.TECHNICAL_REPORT_DIR.exists():
    app.mount(TECHNICAL_REPORT_MOUNT, StaticFiles(directory=str(run_all.TECHNICAL_REPORT_DIR), html=True),
              name="technical_report")

app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

templates = Jinja2Templates(directory=str(HERE / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    # Always the welcome page -- never redirects a fresh visitor into a previous result
    # (see the V4 brief section 4). A run already in progress is surfaced by the client's
    # own /api/status poll on load, not by this route.
    context = {
        "logo_data_uri": _logo_data_uri(),
        "red_lab_logo_data_uri": _red_lab_logo_data_uri(),
        "creator_name": CREATOR_NAME,
        "product_name": PRODUCT_NAME,
        "product_tagline": PRODUCT_TAGLINE,
        "product_version_label": PRODUCT_VERSION_LABEL,
        "verified_full_available": run_all.VERIFIED_FULL_REPORT_DIR.exists(),
        "verified_full_href": f"{VERIFIED_MOUNT}/report.html",
        "technical_report_available": run_all.TECHNICAL_REPORT_DIR.exists(),
        "technical_report_href": f"{TECHNICAL_REPORT_MOUNT}/",
        "demo_descriptors": _all_demo_descriptors(),
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/lab", response_class=HTMLResponse)
def lab_page(request: Request) -> HTMLResponse:
    context = {
        "logo_data_uri": _logo_data_uri(),
        "red_lab_logo_data_uri": _red_lab_logo_data_uri(),
        "creator_name": CREATOR_NAME,
        "product_name": PRODUCT_NAME,
        "product_tagline": PRODUCT_TAGLINE,
        "product_version_label": PRODUCT_VERSION_LABEL,
        "verified_full_available": run_all.VERIFIED_FULL_REPORT_DIR.exists(),
        "verified_full_href": f"{VERIFIED_MOUNT}/report.html",
        "technical_report_available": run_all.TECHNICAL_REPORT_DIR.exists(),
        "technical_report_href": f"{TECHNICAL_REPORT_MOUNT}/",
        "lab_descriptors": lab_module.all_lab_descriptors(),
        "lab_max_chars": lab_module.MAX_INPUT_CHARS,
    }
    return templates.TemplateResponse(request, "lab.html", context)


@app.get("/healthz")
def healthz() -> dict:
    # Confirms only that the public web app itself is alive -- never starts V1/V2.
    return {"status": "ok", "service": "team-checkmate-web"}


def _all_demo_descriptors() -> dict:
    registry = run_all.target_registry.load_registry()
    return {
        evaluation_id: _demo_descriptor(evaluation_id, list(registry.evaluation(evaluation_id).target_ids))
        for evaluation_id in ("emotion.core", "sentiment.core")
    }


def _target_choices() -> dict:
    registry = run_all.target_registry.load_registry()
    labels = {
        "emotion_v1": "Emotion (unhardened)",
        "emotion_v2": "Emotion (hardened)",
        "sentiment_v1": "Sentiment",
    }
    return {
        "targets": [
            {
                "target_id": target_id,
                "task_id": target.task_id,
                "label": labels[target_id],
                "hardened": target.hardened,
            }
            for target_id, target in registry.targets.items()
        ],
        "evaluations": [
            {
                "evaluation_id": evaluation_id,
                "kind": registry.evaluation(evaluation_id).kind,
                "suite_id": registry.evaluation(evaluation_id).suite_id,
            }
            for evaluation_id in ("emotion.core", "sentiment.core")
        ],
        "note": "Only trusted configured choices are offered. There is no free-form URL entry.",
    }


@app.get("/api/targets")
def targets() -> dict:
    return _target_choices()


def _validation_error(field: str, message: str, error_type: str) -> JSONResponse:
    return JSONResponse({"detail": [{
        "loc": ["body", field], "msg": message, "type": error_type,
    }]}, status_code=422)


def _resolve_public_evaluation(body) -> tuple[str, str] | JSONResponse:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return _validation_error("body", "request body must be an object", "type_error.object")
    mode = body.get("mode", "demo")
    if mode not in ("demo", "full"):
        return _validation_error(
            "mode", f"unknown mode {mode!r}; configured: ['demo', 'full']",
            "value_error.unknown_mode",
        )
    registry = run_all.target_registry.load_registry()
    target_id = body.get("target_id")
    evaluation_id = body.get("evaluation_id")
    if target_id is not None:
        if target_id not in registry.targets:
            return _validation_error(
                "target_id",
                f"unknown target_id {target_id!r}; configured: {sorted(registry.targets)}",
                "value_error.unknown_target",
            )
        target_evaluation = "sentiment.core" if target_id == "sentiment_v1" else "emotion.core"
        if evaluation_id is not None and evaluation_id != target_evaluation:
            return _validation_error(
                "evaluation_id", "target_id and evaluation_id identify different tasks",
                "value_error.incompatible_selection",
            )
        evaluation_id = target_evaluation
    evaluation_id = evaluation_id or "emotion.core"
    if evaluation_id not in ("emotion.core", "sentiment.core"):
        configured = ["emotion.core", "sentiment.core"]
        return _validation_error(
            "evaluation_id",
            f"unknown evaluation_id {evaluation_id!r}; configured: {configured}",
            "value_error.unknown_evaluation",
        )
    return evaluation_id, mode


@app.post("/api/run")
async def start_run(request: Request) -> JSONResponse:
    raw = await request.body()
    if raw:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - normalized to the public 422 contract
            return _validation_error("body", "request body is not valid JSON", "value_error.json")
    else:
        body = {}
    resolved = _resolve_public_evaluation(body)
    if isinstance(resolved, JSONResponse):
        return resolved
    evaluation_id, mode = resolved
    registry = run_all.target_registry.load_registry()
    evaluation = registry.evaluation(evaluation_id)
    with _job_lock:
        if _job_state["status"] == "running" or lab_module.is_running_unlocked():
            active_id = _job_state.get("run_id") or lab_module.active_job_id_unlocked()
            return JSONResponse(
                {"detail": "A run is already in progress.", "run_id": active_id},
                status_code=409,
            )
        run_name = _generate_run_name()
        run_id = secrets.token_hex(8)
        descriptor = _demo_descriptor(evaluation_id, list(evaluation.target_ids))
        _job_state.update(
            status="running", state="running", run_id=run_id,
            evaluation_id=evaluation_id, target_ids=list(evaluation.target_ids),
            stage="initializing", stage_index=0,
            percent=descriptor["stage_percent"]["initializing"],
            message=descriptor["stages"][0]["label"],
            run_name=run_name, started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None, results=None, result_url=None, report_url=None, error=None,
        )
        snapshot = dict(_job_state)
        thread = threading.Thread(
            target=_run_job, args=(run_name, run_id, evaluation_id, mode), daemon=True
        )
        thread.start()
    return JSONResponse(snapshot, status_code=202)


@app.get("/api/status")
def status() -> dict:
    return _snapshot()


@app.post("/api/lab/run")
async def start_lab(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 -- malformed JSON body, not our concern beyond a 422
        body = None
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        return JSONResponse({"status": "invalid", "error": "Text is required."}, status_code=422)
    resolved = _resolve_public_evaluation(body)
    if isinstance(resolved, JSONResponse):
        return resolved
    evaluation_id, _mode = resolved
    try:
        result = lab_module.start_lab_job(
            text, lambda: _job_state["status"] == "running",
            evaluation_id=evaluation_id,
        )
    except lab_module.LabValidationError as exc:
        return JSONResponse({"status": "invalid", "error": str(exc)}, status_code=422)
    if result.get("status") == "busy":
        with _job_lock:
            active_id = _job_state.get("run_id") or lab_module.active_job_id_unlocked()
        return JSONResponse(
            {"detail": "A run is already in progress.", "run_id": active_id},
            status_code=409,
        )
    return JSONResponse(result, status_code=202)


@app.get("/api/lab/status/{job_id}")
def lab_status(job_id: str) -> JSONResponse:
    state = lab_module.lab_status(job_id)
    if state is None:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse(state)

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

logger = logging.getLogger("team_checkmate.web")

LOGO_PATH = ROOT / "Team Checkmate Logo.png"
# The real, approved Red Lab logo (System V5.1). Not recreated or modified here -- read
# verbatim from the repository root, same embedding pattern as the Team Checkmate logo.
RED_LAB_LOGO_PATH = ROOT / "Red Lab Adversarial Testing Redefined.png"

RESULTS_MOUNT = "/results"
VERIFIED_MOUNT = "/verified-full"

# Real orchestration transitions only -- see run_all.py's _emit_progress call sites for
# what each stage actually means. Order here must match the order run_experiment() emits.
STAGE_ORDER = (
    "initializing", "starting_v1", "attacking_v1", "starting_v2", "attacking_v2",
    "analyzing", "generating_results", "complete",
)
STAGE_LABELS = {
    "initializing": "Initializing toolkit",
    "starting_v1": "Starting V1",
    "attacking_v1": "Attacking unhardened endpoint",
    "starting_v2": "Starting V2",
    "attacking_v2": "Testing hardened endpoint",
    "analyzing": "Analyzing evidence",
    "generating_results": "Generating results",
    "complete": "Complete",
}
# Stage-boundary percentages, per the V4 brief -- movement happens only on real stage
# transitions (see _progress_callback), never a fake continuous animation.
STAGE_PERCENT = dict(zip(STAGE_ORDER, (5, 15, 30, 50, 65, 82, 92, 100)))


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
        "status": "idle", "stage": None, "stage_index": -1, "percent": 0, "message": "",
        "run_name": None, "started_at": None, "completed_at": None,
        "result_url": None, "error": None,
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


def _progress_callback(stage: str, message: str) -> None:
    with _job_lock:
        if _job_state["status"] != "running":
            return
        _job_state["stage"] = stage
        _job_state["stage_index"] = STAGE_ORDER.index(stage)
        _job_state["percent"] = STAGE_PERCENT[stage]
        _job_state["message"] = message


def _run_job(run_name: str) -> None:
    try:
        result = run_all.run_experiment(
            mode="demo", run_name=run_name, progress_callback=_progress_callback,
        )
        report_html = Path(result["report_html"]).resolve()
        rel = report_html.relative_to(Path(run_all.RESULTS_ROOT).resolve())
        result_url = f"{RESULTS_MOUNT}/{rel.as_posix()}"
        with _job_lock:
            _job_state["status"] = "complete"
            _job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _job_state["result_url"] = result_url
    except Exception:  # noqa: BLE001 -- orchestration failure; never let it kill the thread silently
        logger.exception("Live demo run failed for run_name=%s", run_name)
        with _job_lock:
            _job_state["status"] = "failed"
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
        "stage_labels": STAGE_LABELS,
        "stage_order": list(STAGE_ORDER),
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
        "lab_stage_order": list(lab_module.LAB_STAGE_ORDER),
        "lab_stage_labels": lab_module.LAB_STAGE_LABELS,
        "lab_max_chars": lab_module.MAX_INPUT_CHARS,
    }
    return templates.TemplateResponse(request, "lab.html", context)


@app.get("/healthz")
def healthz() -> dict:
    # Confirms only that the public web app itself is alive -- never starts V1/V2.
    return {"status": "ok", "service": "team-checkmate-web"}


@app.post("/api/run")
def start_run() -> JSONResponse:
    with _job_lock:
        if _job_state["status"] == "running":
            return JSONResponse(dict(_job_state), status_code=202)
        if lab_module.is_running_unlocked():
            # A Live Red-Team Lab job holds the shared slot -- distinct from the branch above
            # (which reattaches to demo's own already-running job): this is a real "try again"
            # busy signal, in the same shape as Lab's own busy response (brief section 9).
            return JSONResponse({"status": "busy"}, status_code=409)
        run_name = _generate_run_name()
        _job_state.update(
            status="running", stage="initializing", stage_index=0,
            percent=STAGE_PERCENT["initializing"], message=STAGE_LABELS["initializing"],
            run_name=run_name, started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None, result_url=None, error=None,
        )
        snapshot = dict(_job_state)
        thread = threading.Thread(target=_run_job, args=(run_name,), daemon=True)
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
    try:
        result = lab_module.start_lab_job(text, lambda: _job_state["status"] == "running")
    except lab_module.LabValidationError as exc:
        return JSONResponse({"status": "invalid", "error": str(exc)}, status_code=422)
    status_code = 409 if result.get("status") == "busy" else 202
    return JSONResponse(result, status_code=status_code)


@app.get("/api/lab/status/{job_id}")
def lab_status(job_id: str) -> JSONResponse:
    state = lab_module.lab_status(job_id)
    if state is None:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse(state)

"""Public FastAPI web layer for Team Checkmate (System V4).

Thin deployment layer only -- no attack/runner/analysis/report logic lives here. The
"Run Live Attack Test" button ultimately calls ``run_all.run_experiment(mode="demo", ...)``
directly, in-process, never by shelling out to ``python run_all.py``. See AGENTS.md and
HANDOFF.md for the project's architecture and ownership rules; this file and the rest of
``web/`` are the V4-specific deployment layer, not owned by any existing component folder.

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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import run_all  # noqa: E402

logger = logging.getLogger("team_checkmate.web")

LOGO_PATH = ROOT / "Team Checkmate Logo.png"

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


def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        raise RuntimeError(f"Required logo asset not found: {LOGO_PATH}")
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")


def _idle_state() -> dict:
    return {
        "status": "idle", "stage": None, "stage_index": -1, "percent": 0, "message": "",
        "run_name": None, "started_at": None, "completed_at": None,
        "result_url": None, "error": None,
    }


_job_lock = threading.Lock()
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
        "verified_full_available": run_all.VERIFIED_FULL_REPORT_DIR.exists(),
        "verified_full_href": f"{VERIFIED_MOUNT}/report.html",
        "stage_labels": STAGE_LABELS,
        "stage_order": list(STAGE_ORDER),
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/healthz")
def healthz() -> dict:
    # Confirms only that the public web app itself is alive -- never starts V1/V2.
    return {"status": "ok", "service": "team-checkmate-web"}


@app.post("/api/run")
def start_run() -> JSONResponse:
    with _job_lock:
        if _job_state["status"] == "running":
            return JSONResponse(dict(_job_state), status_code=202)
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

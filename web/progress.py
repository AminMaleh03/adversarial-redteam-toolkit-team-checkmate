"""Shared progress-descriptor builders for Live Demo and Try Your Own Input (v6.1 Phase 2/3).

A "descriptor" is the single place that decides what the progress view looks like for a given
registry evaluation: paired (two endpoint cards, a V1/V2 comparison, "Same model / Two endpoint
configurations") or single-target (one card, no hardening claim). Both web/app.py (Live Demo)
and web/lab.py (Try Your Own Input) render their progress view from a descriptor's ``cards`` and
``stages`` -- the client rebuilds the DOM from this data rather than hiding pre-rendered V1/V2
markup with CSS, so a single-target evaluation like sentiment.core can never carry paired-only
content (no "Two endpoint configurations", no "Starting V1", no hardening-improvement wording).

``stage_order``/``stage_percent`` describe the REAL, distinguishable backend progress events for
this evaluation (used to compute a percent and an index from the raw stage name a progress
callback reports). ``stages`` is the DISPLAY list rendered as the stage checklist; each entry's
``maps_to`` names the real stage id that marks it active/done, so two display rows may share one
real transition when the orchestration genuinely cannot distinguish them (never fabricated as
separate real progress).
"""

from __future__ import annotations

from typing import Optional


def card(lane: str, title: str, note: str, *, start_stage: str, end_stage: str) -> dict:
    """One endpoint-status card. ``start_stage``/``end_stage`` are real stage ids (see
    ``stage_order``) marking when this lane moves from "Starting" to "Active" to "Complete"."""
    return {"lane": lane, "title": title, "note": note,
            "start_stage": start_stage, "end_stage": end_stage}


def stage(stage_id: str, label: str, *, maps_to: Optional[str] = None) -> dict:
    return {"id": stage_id, "label": label, "maps_to": maps_to or stage_id}


def descriptor(*, evaluation_id: str, kind: str, target_ids: list[str],
               same_model_note: Optional[str], footer_note: str,
               cards: list[dict], stage_order: list[str], stage_percent: dict,
               stages: list[dict]) -> dict:
    if kind not in ("paired", "single"):
        raise ValueError(f"unknown descriptor kind {kind!r}")
    return {
        "evaluation_id": evaluation_id,
        "kind": kind,
        "target_ids": list(target_ids),
        "same_model_note": same_model_note,
        "footer_note": footer_note,
        "cards": cards,
        "stage_order": list(stage_order),
        "stage_percent": dict(stage_percent),
        "stages": stages,
    }

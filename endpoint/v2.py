"""
V2 — hardened endpoint. Runs on port 8001.

Same model loading code, same two routes, same response shape as V1.
Exactly four defenses added on top, no more:

  1. Length limit, tied to the model's own tokenizer max length.
     Checked BEFORE inference, so oversized input never reaches
     model.py (which never truncates — see model.py docstring).
  2. Strict Pydantic types + extra="forbid" (reject unexpected fields).
  3. A generic exception handler for genuinely unexpected server
     errors only. It does NOT touch FastAPI/Pydantic's own 422
     validation responses or HTTPExceptions we raise ourselves —
     those are a legitimate, analysed result and must stay as-is.
  4. Unicode normalization + invisible/control character stripping +
     whitespace collapsing, all in one pass.

Run with (from the repo root, venv active):
    uvicorn endpoint.v2:app --port 8001

No --reload when testing attacks, same reasoning as V1.
"""

import re
import unicodedata

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr

from endpoint.model import MAX_SEQUENCE_LENGTH, format_response, predict, tokenizer

app = FastAPI()


class PredictRequest(BaseModel):
    # Defense 2: strict types + reject unexpected extra fields.
    model_config = ConfigDict(extra="forbid")
    text: StrictStr


def clean_text(text: str) -> str:
    """Defense 4: unicode normalize, strip invisible/control chars, collapse whitespace."""
    normalized = unicodedata.normalize("NFKC", text)
    # Keep normal whitespace (space, tab, newline); drop every other
    # Unicode "control/format/other" category character — this is
    # where zero-width chars, RTL overrides, and null bytes go.
    visible = "".join(
        ch for ch in normalized
        if ch in (" ", "\t", "\n") or unicodedata.category(ch)[0] != "C"
    )
    collapsed = re.sub(r"\s+", " ", visible).strip()
    return collapsed


# Defense 3: catch genuinely unexpected errors only. This handler is
# registered for the exact `Exception` type. FastAPI/Starlette resolve
# exception handlers by exact type match before falling back up the
# MRO, and RequestValidationError (422) and HTTPException already have
# their own built-in/explicit handlers — so this never intercepts
# those. It only fires for things neither of us anticipated.
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.post("/predict")
def predict_endpoint(request: PredictRequest):
    cleaned = clean_text(request.text)

    # Defense 1: length limit, checked before inference. Uses the same
    # tokenizer model.py uses, so "too long" means exactly what the
    # model can't handle — no arbitrary number.
    # truncation=False passed explicitly, same as model.py: this call must
    # measure the FULL length, never silently trim it before we can count it.
    token_count = len(tokenizer.encode(cleaned, add_special_tokens=True, truncation=False))
    if token_count > MAX_SEQUENCE_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Input exceeds maximum sequence length of {MAX_SEQUENCE_LENGTH} tokens.",
        )

    scores = predict(cleaned)
    return format_response(scores)


@app.get("/health")
def health():
    return {"status": "ok"}
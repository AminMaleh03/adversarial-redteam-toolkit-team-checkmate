"""V1-equivalent sentiment endpoint. Runs on port 8002 (see endpoint/targets.json).

Same shape as endpoint/v1.py: no length limit, no character cleanup, no custom error
handling beyond what FastAPI/Pydantic give automatically. Those absences are
intentional here too -- this is the unhardened wrapper for the sentiment target, not a
new, better-defended endpoint. There is deliberately no sentiment V2 (see
docs/stage3/tasks/task_2_rayyan.md: "Do not add a sentiment V2 or tune defenses based
on new evaluation results").

Model/tokenizer are loaded ONCE at import time via endpoint.loader.load_target_model,
never via endpoint.model -- importing that module would load the *emotion* model's
weights into this process as a side effect. This file only ever knows about
"sentiment_v1" and the registry; it never imports endpoint.v1, endpoint.v2 or
endpoint.model.

Labels served are exactly NEGATIVE / POSITIVE, uppercase, as declared in
endpoint/targets.json and verified against the loaded model by loader.py. Nothing
here lowercases them, retitles them, or maps them onto the emotion label set.

Run with (from the repo root, venv active):
    uvicorn endpoint.sentiment_v1:app --port 8002

No --reload when testing attacks, same reasoning as v1.py/v2.py: reload silently
restarts the app on changes/crashes, which would hide exactly the failures the
toolkit is trying to detect.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from endpoint.loader import format_response, load_target_model

app = FastAPI()

# Loaded once at import time -- same rule as endpoint/model.py, applied to this
# target instead of the emotion one. Raises loudly (ModelIdentityError) at import if
# the loaded model doesn't match what endpoint/targets.json declares for
# "sentiment_v1"; this process must not start serving a target it can't verify.
_loaded = load_target_model("sentiment_v1")

# Exposed for parity with endpoint/model.py's MAX_SEQUENCE_LENGTH -- read from the
# live tokenizer via loader.py, not hardcoded. V1 does not enforce this (that's the
# point, same as the emotion V1); it exists for callers (the runner) that need to
# parameterize token limits by target.
MAX_SEQUENCE_LENGTH = _loaded.max_sequence_length


class PredictRequest(BaseModel):
    text: str


@app.post("/predict")
def predict_endpoint(request: PredictRequest):
    scores = _loaded.predict(request.text)
    return format_response(scores)


@app.get("/health")
def health():
    # Deliberately cheap -- proves the process is alive, does not touch the model.
    # Same contract as the emotion endpoints' /health.
    return {"status": "ok"}

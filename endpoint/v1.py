"""Unhardened FastAPI app: accepts input as-is and passes it straight to the model."""

# TODO(Rayyan): implement the V1 app.

"""
V1 — deliberately unhardened endpoint. Runs on port 8000.
 
This is the target for the initial attack run. It has no length limit,
no character cleanup, and no custom error handling on top of what
FastAPI/Pydantic give us automatically. Those absences are intentional:
they're the vulnerabilities the toolkit is meant to find. See V2 for
the hardened version with the same model, same routes, same response
shape, plus four defenses.
 
Run with (from the repo root, venv active):
    uvicorn endpoint.v1:app --port 8000
 
Do NOT add --reload when testing attacks — reload silently restarts
the app on changes/crashes, which would hide exactly the failures
we're trying to detect.
"""
 
from fastapi import FastAPI
from pydantic import BaseModel
 
from endpoint.model import format_response, predict
 
app = FastAPI()
 
 
class PredictRequest(BaseModel):
    text: str
 
 
@app.post("/predict")
def predict_endpoint(request: PredictRequest):
    scores = predict(request.text)
    return format_response(scores)
 
 
@app.get("/health")
def health():
    # Deliberately cheap — proves the process is alive, does not touch
    # the model. Amin's runner pings this between attacks.
    return {"status": "ok"}
 

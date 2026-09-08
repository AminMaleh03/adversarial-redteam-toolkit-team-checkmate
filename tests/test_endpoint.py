"""
Tests for endpoint/v1.py and endpoint/v2.py.

Run from the repo root (venv active):
    python -m pytest tests/test_endpoint.py -v

Note: importing v1/v2 loads the real model, so this suite is slow the
first time (model download, cached after) and takes a few seconds each
run after that (model load at import, once per process). That's
expected — it mirrors the real server's startup cost.
"""

from fastapi.testclient import TestClient

from endpoint.v1 import app as v1_app
from endpoint.v2 import app as v2_app

client_v1 = TestClient(v1_app)
client_v2 = TestClient(v2_app)

EMOTIONS = {"joy", "neutral", "surprise", "sadness", "anger", "fear", "disgust"}
NORMAL_TEXT = "I just got the job I wanted"


def test_v1_normal_sentence_returns_prediction():
    response = client_v1.post("/predict", json={"text": NORMAL_TEXT})
    assert response.status_code == 200
    body = response.json()
    assert "label" in body
    assert "confidence" in body
    assert "all_scores" in body


def test_v1_health_responds():
    response = client_v1.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_contains_label():
    body = client_v1.post("/predict", json={"text": NORMAL_TEXT}).json()
    assert isinstance(body["label"], str)
    assert body["label"] in EMOTIONS


def test_confidence_between_0_and_1():
    body = client_v1.post("/predict", json={"text": NORMAL_TEXT}).json()
    assert 0.0 <= body["confidence"] <= 1.0


def test_all_scores_contains_all_seven_emotions():
    body = client_v1.post("/predict", json={"text": NORMAL_TEXT}).json()
    assert set(body["all_scores"].keys()) == EMOTIONS
    for score in body["all_scores"].values():
        assert 0.0 <= score <= 1.0


def test_v1_and_v2_return_same_response_shape():
    body_v1 = client_v1.post("/predict", json={"text": NORMAL_TEXT}).json()
    body_v2 = client_v2.post("/predict", json={"text": NORMAL_TEXT}).json()
    assert set(body_v1.keys()) == set(body_v2.keys()) == {"label", "confidence", "all_scores"}
    assert set(body_v1["all_scores"].keys()) == set(body_v2["all_scores"].keys()) == EMOTIONS


def test_v2_rejects_input_v1_accepts():
    # Extra, unexpected field: V1 has no schema restriction beyond
    # `text: str`, so Pydantic silently ignores the extra field and
    # the request succeeds. V2 uses extra="forbid", so the same
    # payload is rejected with a 422.
    payload = {"text": NORMAL_TEXT, "unexpected_field": "should not be here"}

    response_v1 = client_v1.post("/predict", json=payload)
    assert response_v1.status_code == 200

    response_v2 = client_v2.post("/predict", json=payload)
    assert response_v2.status_code == 422
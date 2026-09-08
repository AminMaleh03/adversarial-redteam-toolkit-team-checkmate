"""Tests for the V1 and V2 endpoints: prediction shape, defenses, and error handling."""

# TODO(Rayyan): write the endpoint tests.

from fastapi.testclient import TestClient
 
from endpoint.v1 import app as v1_app
 
client_v1 = TestClient(v1_app)
 
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

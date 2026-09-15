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

# ==========================================================================
# Stage 3: the sentiment target, its loader, and the registry that names it.
#
# Two levels, deliberately separate.
#
# The loader tests below use hand-built stand-ins for the model config and the
# tokenizer. They run offline in milliseconds and prove the declared-vs-actual
# identity checks fire -- which is all a stand-in can prove. The tests that need
# the real pinned weights say so, load them, and SKIP with a stated reason if they
# are unavailable. A skip there is a gap in the evidence, not a pass: nothing below
# treats a skipped sentiment test as validation of the sentiment endpoint.
# ==========================================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from contract import ContractError, ModelSpec
from endpoint.loader import (
    ModelIdentityError,
    _inference_capacity,
    _resolve_usable_max_length,
    _validate_inference_capacity,
    _validate_label_space,
)
from endpoint.targets import TargetConfigError, load_registry

SENTIMENT_LABELS = {"NEGATIVE", "POSITIVE"}
SENTIMENT_TEXT = "it 's a charming and often affecting journey . "


class FakeTokenizer:
    def __init__(self, model_max_length):
        self.model_max_length = model_max_length


class FakeConfig:
    def __init__(self, model_type="distilbert", max_position_embeddings=512, id2label=None):
        self.model_type = model_type
        self.max_position_embeddings = max_position_embeddings
        self.id2label = id2label or {0: "NEGATIVE", 1: "POSITIVE"}


def sentiment_spec(**overrides) -> ModelSpec:
    fields = dict(
        model_id="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        revision="714eb0fa89d2f80546fda750413ed43d93601a13",
        tokenizer_id="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        tokenizer_revision="714eb0fa89d2f80546fda750413ed43d93601a13",
        labels=("NEGATIVE", "POSITIVE"),
        max_sequence_length=512,
    )
    fields.update(overrides)
    return ModelSpec(**fields)


# --------------------------------------------------------------------------
# registry: what is configured, and what it refuses
# --------------------------------------------------------------------------


def test_the_registry_is_the_only_source_of_targets():
    registry = load_registry()
    assert set(registry.targets) == {"emotion_v1", "emotion_v2", "sentiment_v1"}
    sentiment = registry.target("sentiment_v1")
    assert sentiment.module == "endpoint.sentiment_v1"
    assert sentiment.hardened is False          # there is deliberately no sentiment V2
    assert sentiment.version == "v1"
    assert registry.task_for("sentiment_v1").task_id == "sentiment_2"


def test_every_target_has_its_own_loopback_port():
    registry = load_registry()
    ports = [spec.port for spec in registry.targets.values()]
    assert len(set(ports)) == len(ports)
    assert all(1024 < port < 65536 for port in ports)
    # A service is bound to the port its target declares, never to a number
    # written down somewhere else.
    assert registry.target("sentiment_v1").port == 8002


def test_an_unknown_target_raises_instead_of_returning_none():
    registry = load_registry()
    with pytest.raises(ContractError, match="unknown target_id"):
        registry.target("sentiment_v2")
    with pytest.raises(ContractError, match="unknown evaluation_id"):
        registry.evaluation("sentiment.ci")


def test_a_duplicate_port_is_rejected_at_load(tmp_path):
    import json
    document = json.loads((ROOT / "endpoint" / "targets.json").read_text(encoding="utf-8"))
    document["targets"]["sentiment_v1"]["port"] = document["targets"]["emotion_v1"]["port"]
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TargetConfigError, match="collides"):
        load_registry(path)


def test_an_unpinned_revision_is_rejected_at_load(tmp_path):
    import json
    document = json.loads((ROOT / "endpoint" / "targets.json").read_text(encoding="utf-8"))
    document["models"]["sentiment_distilbert_sst2"]["revision"] = "main"
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TargetConfigError, match="40-hex revision"):
        load_registry(path)


def test_an_evaluation_cannot_reference_a_target_from_another_task(tmp_path):
    import json
    document = json.loads((ROOT / "endpoint" / "targets.json").read_text(encoding="utf-8"))
    document["evaluations"]["sentiment.core"]["target_ids"] = ["emotion_v1"]
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TargetConfigError, match="cannot mix tasks"):
        load_registry(path)


def test_the_registry_records_the_uppercase_sentiment_label_space():
    registry = load_registry()
    labels = registry.model_for("sentiment_v1").labels
    assert labels == ("NEGATIVE", "POSITIVE")
    assert set(labels) == SENTIMENT_LABELS
    assert set(labels).isdisjoint(EMOTIONS)


# --------------------------------------------------------------------------
# loader: declared identity vs what actually loaded
# --------------------------------------------------------------------------


def test_a_label_space_that_contradicts_the_registry_fails_the_run():
    spec = sentiment_spec()
    # The exact defect the model-identity document names: sentiment labels
    # lowercased, or mapped onto the emotion set.
    with pytest.raises(ModelIdentityError, match="does not match its declared"):
        _validate_label_space(spec, {0: "negative", 1: "positive"})
    with pytest.raises(ModelIdentityError):
        _validate_label_space(spec, {0: "sadness", 1: "joy"})


def test_a_reordered_label_space_fails_even_with_the_same_labels():
    """id 0 must be NEGATIVE. Same set, wrong ids, is a silently inverted model."""
    with pytest.raises(ModelIdentityError):
        _validate_label_space(sentiment_spec(), {0: "POSITIVE", 1: "NEGATIVE"})


def test_the_matching_label_space_is_accepted_unchanged():
    assert _validate_label_space(sentiment_spec(), {0: "NEGATIVE", 1: "POSITIVE"}) is None


def test_the_unset_tokenizer_length_sentinel_is_not_treated_as_a_limit():
    """transformers reports int(1e30) when no limit is configured."""
    with pytest.raises(ModelIdentityError, match="no real model_max_length"):
        _resolve_usable_max_length(sentiment_spec(), FakeTokenizer(int(1e30)))
    with pytest.raises(ModelIdentityError, match="no real model_max_length"):
        _resolve_usable_max_length(sentiment_spec(), FakeTokenizer(0))


def test_a_tokenizer_limit_that_contradicts_the_registry_is_an_error():
    with pytest.raises(ModelIdentityError, match="does not match registry"):
        _resolve_usable_max_length(sentiment_spec(), FakeTokenizer(128))


def test_the_usable_limit_is_read_from_the_tokenizer():
    assert _resolve_usable_max_length(sentiment_spec(), FakeTokenizer(512)) == 512


def test_inference_capacity_is_derived_from_the_pinned_config_not_a_model_card():
    """A model card's training length is prose; the position table is the ceiling."""
    # DistilBERT reserves no positions: 512 embeddings means 512 usable tokens.
    assert _inference_capacity(FakeConfig("distilbert", 512)) == 512
    # RoBERTa-family start position ids at padding_idx + 1, so 514 means 512. This
    # is why the emotion model's config says 514 and its real limit is 512.
    assert _inference_capacity(FakeConfig("roberta", 514)) == 512
    # Not derivable is None, never a guess.
    assert _inference_capacity(FakeConfig("distilbert", None)) is None


def test_a_capacity_that_contradicts_the_declared_limit_is_a_configuration_error():
    with pytest.raises(ModelIdentityError, match="inference capacity"):
        _validate_inference_capacity(sentiment_spec(), FakeConfig("distilbert", 256))
    # 512 declared against a 512-position DistilBERT is consistent.
    assert _validate_inference_capacity(
        sentiment_spec(), FakeConfig("distilbert", 512)
    ) == 512
    # An undeclarable capacity is reported as unknown, not as agreement.
    assert _validate_inference_capacity(
        sentiment_spec(), FakeConfig("distilbert", None)
    ) is None


def test_the_registry_limits_agree_with_each_architectures_real_capacity():
    """The two pinned models, checked against the family rule above."""
    registry = load_registry()
    assert registry.model_for("sentiment_v1").max_sequence_length == _inference_capacity(
        FakeConfig("distilbert", 512)
    )
    assert registry.model_for("emotion_v2").max_sequence_length == _inference_capacity(
        FakeConfig("roberta", 514)
    )


def test_the_loader_never_reaches_the_emotion_module():
    """A sentiment process must not load a second model as an import side effect."""
    source = (ROOT / "endpoint" / "loader.py").read_text(encoding="utf-8")
    for forbidden in ("endpoint.model", "from endpoint import model",
                      "endpoint.v1", "endpoint.v2"):
        code = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#") and not line.lstrip().startswith("``")
        )
        assert f"import {forbidden}" not in code

    sentiment_source = (ROOT / "endpoint" / "sentiment_v1.py").read_text(encoding="utf-8")
    assert "endpoint.model" not in sentiment_source.split('"""')[-1]


def test_reading_the_pinned_tokenizer_loads_no_weights():
    """The runner needs token counts, not a model. It must not pay for one."""
    import subprocess
    probe = (
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        "from endpoint.loader import load_target_tokenizer\n"
        "context = load_target_tokenizer('sentiment_v1')\n"
        "assert context.max_tokens == 512, context.max_tokens\n"
        "assert context.model_spec.labels == ('NEGATIVE', 'POSITIVE')\n"
        "assert context.count_tokens('hello there') > 0\n"
        "print('endpoint.model' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                          capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip(
            "the pinned sentiment tokenizer is not available offline; this check "
            f"was NOT performed: {done.stderr.strip()[-300:]}"
        )
    assert done.stdout.strip().endswith("False")


# --------------------------------------------------------------------------
# the real pinned sentiment endpoint
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sentiment_client():
    """The real app, with the real pinned weights. Skips loudly if unavailable."""
    try:
        from endpoint.sentiment_v1 import app as sentiment_app
    except Exception as exc:                       # noqa: BLE001
        pytest.skip(
            "the pinned sentiment model could not be loaded, so NOTHING below was "
            f"verified against a real endpoint: {type(exc).__name__}: {exc}"
        )
    return TestClient(sentiment_app)


def test_sentiment_returns_the_full_pinned_label_space(sentiment_client):
    response = sentiment_client.post("/predict", json={"text": SENTIMENT_TEXT})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"label", "confidence", "all_scores"}
    assert set(body["all_scores"]) == SENTIMENT_LABELS
    assert body["label"] in SENTIMENT_LABELS
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["confidence"] == max(body["all_scores"].values())


def test_sentiment_labels_are_uppercase_and_never_emotion_labels(sentiment_client):
    body = sentiment_client.post("/predict", json={"text": SENTIMENT_TEXT}).json()
    assert body["label"] == body["label"].upper()
    assert set(body["all_scores"]).isdisjoint(EMOTIONS)
    assert "negative" not in body["all_scores"]


def test_sentiment_separates_the_two_polarities(sentiment_client):
    """Not an accuracy claim: two clearly opposite sentences must not collapse."""
    positive = sentiment_client.post(
        "/predict", json={"text": "an absolute delight from start to finish"}
    ).json()
    negative = sentiment_client.post(
        "/predict", json={"text": "this was the worst film I have ever sat through"}
    ).json()
    assert positive["label"] == "POSITIVE"
    assert negative["label"] == "NEGATIVE"


def test_sentiment_health_matches_the_emotion_contract(sentiment_client):
    response = sentiment_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sentiment_response_shape_matches_the_emotion_endpoints(sentiment_client):
    sentiment = sentiment_client.post("/predict", json={"text": SENTIMENT_TEXT}).json()
    emotion = client_v1.post("/predict", json={"text": NORMAL_TEXT}).json()
    assert set(sentiment) == set(emotion) == {"label", "confidence", "all_scores"}


def test_sentiment_does_not_silently_truncate_oversized_input(sentiment_client):
    """The one thing this path is not allowed to get wrong.

    V1-equivalent means unguarded, not lenient. Over-length input must reach the
    model and fail there. A 200 with a confident prediction would mean the input
    was quietly cut to 512 tokens, which neutralises the whole boundary and
    truncation attack families -- they would look like they succeeded normally.
    """
    from endpoint.loader import load_target_tokenizer

    limit = load_target_tokenizer("sentiment_v1").max_tokens
    oversized = "word " * (limit * 2)
    client = TestClient(sentiment_client.app, raise_server_exceptions=False)
    response = client.post("/predict", json={"text": oversized})
    assert response.status_code != 200, (
        "oversized input returned a normal prediction, which means it was "
        "truncated somewhere on this path"
    )
    assert response.status_code >= 500


def test_sentiment_v1_has_no_hardening_of_its_own(sentiment_client):
    """The emotion V2 defenses are not silently copied onto the new target."""
    # extra="forbid" is a V2 defense; V1-equivalent must accept the extra field.
    response = sentiment_client.post(
        "/predict", json={"text": SENTIMENT_TEXT, "unexpected_field": "ignored"}
    )
    assert response.status_code == 200


def test_the_served_labels_are_the_registry_labels(sentiment_client):
    registry = load_registry()
    declared = set(registry.model_for("sentiment_v1").labels)
    served = set(sentiment_client.post(
        "/predict", json={"text": SENTIMENT_TEXT}
    ).json()["all_scores"])
    assert served == declared

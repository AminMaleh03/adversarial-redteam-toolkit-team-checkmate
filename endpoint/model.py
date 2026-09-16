"""Loads the emotion classifier once and exposes a single predict helper shared by V1 and V2."""


from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
"""
Shared model loading and inference code for the endpoint.

Loaded ONCE per process at import time — never inside a request handler.
V1 and V2 each run as separate uvicorn processes and each import this
module independently, so each gets its own copy in memory. That's fine;
what matters is that the (expensive) load happens exactly once per
process, not once per request.

Truncation is intentionally disabled everywhere text reaches the
tokenizer or the model. This is deliberate, not an oversight:
Hugging Face's pipeline can silently cut long input down to the model's
max length, which would make oversized-payload attacks look like they
succeeded normally instead of surfacing the real, unguarded failure.
V1 has no protection against this (that's the point — it's a genuine
vulnerability from missing validation). V2 never lets oversized input
reach this file at all; it rejects it before calling predict().
"""



MODEL_NAME = "j-hartmann/emotion-english-distilroberta-base"

# Exact commit pinned so V1, V2, and every teammate's cache resolve to the identical
# weights/config regardless of what "main" points to later. Verified against the actual
# Hugging Face cache (huggingface_hub.scan_cache_dir): refs/main -> this commit.
MODEL_REVISION = "0e1cd914e3d46199ed785853e12b57304e04178b"

# Loaded once at import time.
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)
_model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)

# top_k=None -> return all label scores, not just the winner.
# truncation=False -> never silently trim input. See module docstring.
_classifier = pipeline(
    task="text-classification",
    model=_model,
    tokenizer=tokenizer,
    top_k=None,
    truncation=False,
)

# Read from the tokenizer rather than hardcoding a number, so V2's
# length limit always matches what this specific model can actually
# process.
MAX_SEQUENCE_LENGTH = tokenizer.model_max_length


def predict(text: str) -> list[dict]:
    """
    Run inference and return all seven label scores.

    Returns a list like:
        [{"label": "joy", "score": 0.94}, {"label": "neutral", "score": 0.02}, ...]

    Deliberately does NOT truncate. If `text` is longer than the model
    can handle, this will raise/fail naturally rather than silently
    trimming — callers that need a length guard (V2) must check before
    calling this, using MAX_SEQUENCE_LENGTH above.
    """
    # truncation=False passed explicitly here too — belt and suspenders,
    # since pipeline-level defaults have changed across transformers
    # versions and this is the one thing we're not allowed to get wrong.
    results = _classifier(text, truncation=False)

    # With top_k=None, the pipeline returns a nested list: [[{...}, ...]]
    # for a single input string. Unwrap it.
    if len(results) > 0 and isinstance(results[0], list):
        results = results[0]

    return results


def format_response(scores: list[dict]) -> dict:
    """
    Shape raw predict() output into the response contract shared by
    V1 and V2:

        {
          "label": "joy",
          "confidence": 0.94,
          "all_scores": {"joy": 0.94, "neutral": 0.02, ...}
        }

    Kept here, not duplicated in v1.py/v2.py, so the two endpoints
    can't accidentally drift apart on response shape.
    """
    top = max(scores, key=lambda item: item["score"])
    all_scores = {item["label"]: item["score"] for item in scores}
    return {
        "label": top["label"],
        "confidence": top["score"],
        "all_scores": all_scores,
    }
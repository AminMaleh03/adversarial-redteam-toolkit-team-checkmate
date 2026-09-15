"""Registry-driven model loader for endpoint targets.

``endpoint/model.py`` is emotion-specific: it imports the emotion model directly by
name and loads it at import time. This module is its general-purpose counterpart --
it loads the real model/tokenizer FOR A GIVEN TARGET using the static registry
(``endpoint/targets.py`` + ``contract.py``) instead of a hardcoded model id.

It exists so ``endpoint/sentiment_v1.py`` never has to import ``endpoint.model``.
Importing that module loads the *emotion* classifier's weights as a side effect of
import -- exactly the trap this task calls out: "Token counting must not accidentally
import the old emotion module and load its weights for a sentiment run." This module
imports nothing from ``endpoint.model`` and nothing from ``endpoint.v1``/``v2``.

Design mirrors ``endpoint/model.py``'s rules exactly:
  - truncation is NEVER applied anywhere text reaches the tokenizer or the model.
    ``truncation=False`` is passed explicitly at both the pipeline and the predict
    call, the same belt-and-suspenders reasoning as the emotion loader.
  - the usable max sequence length is READ from the loaded tokenizer, never copied
    from a model card's training-sequence-length claim.
  - loading happens once per call to :func:`load_target_model`, which the caller
    (an endpoint module, at its own import time) is responsible for invoking exactly
    once per process -- not once per request.

Runtime identity check
-----------------------
This does not just trust the registry's declared label space and
``max_sequence_length`` -- it loads the real model/tokenizer and checks that what
actually loaded matches what the registry declared:

  - the model's ``id2label`` mapping must equal ``ModelSpec.labels``, in order and in
    exact case (id 0 -> ``labels[0]``, id 1 -> ``labels[1]``, ...). Sentiment's is
    ``("NEGATIVE", "POSITIVE")`` -- uppercase, never lowercased, never remapped onto
    emotion labels.
  - the tokenizer's ``model_max_length`` must be a real, finite, positive number --
    not the "no limit configured" sentinel some tokenizer configs fall back to
    (``int(1e30)``) -- and must equal the registry's declared ``max_sequence_length``.

A mismatch on either is a loud failure (:class:`ModelIdentityError`), never a silent
fallback. See ``docs/stage3/MODEL_IDENTITY.md``: "a target whose declared identity
does not match what the loaded model reports fails the run rather than continuing."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

from contract import ModelSpec, Registry
from endpoint.targets import load_registry

# transformers' PreTrainedTokenizerBase defaults model_max_length to int(1e30) when a
# tokenizer config sets no explicit value. That is a "no limit configured" sentinel,
# not a real limit, and must never be trusted as one.
_UNSET_MAX_LENGTH_SENTINEL = int(1e30)


class ModelIdentityError(ValueError):
    """Raised when a loaded model/tokenizer does not match its registry declaration."""


@dataclass(frozen=True)
class LoadedTarget:
    """Everything a target endpoint needs to serve /predict and /health."""

    target_id: str
    model_spec: ModelSpec
    # The usable input limit in tokens, confirmed against the live tokenizer -- not
    # copied from the registry unchecked. See _resolve_usable_max_length.
    max_sequence_length: int
    # text -> [{"label": str, "score": float}, ...], one entry per declared label.
    # Never truncates; see module docstring.
    predict: Callable[[str], list[dict]]


def _validate_label_space(model_spec: ModelSpec, id2label: dict) -> None:
    """The loaded model's label space must match the registry, in order and case."""
    reported = tuple(id2label[i] for i in sorted(id2label))
    if reported != model_spec.labels:
        raise ModelIdentityError(
            f"{model_spec.model_id}: loaded model reports labels {reported!r}, "
            f"registry declares {model_spec.labels!r}. Refusing to serve a target "
            "whose actual label space does not match its declared identity."
        )


def _resolve_usable_max_length(model_spec: ModelSpec, tokenizer) -> int:
    """The tokenizer's own reported limit, validated against the registry pin.

    Distinguishes an actual configured limit from the "unset" sentinel, and from a
    model-card training-sequence-length claim -- this function only ever trusts what
    the live tokenizer reports for THIS pinned revision.
    """
    reported = tokenizer.model_max_length
    if reported is None or reported <= 0 or reported >= _UNSET_MAX_LENGTH_SENTINEL:
        raise ModelIdentityError(
            f"{model_spec.model_id}: tokenizer reports no real model_max_length "
            f"({reported!r}); cannot derive a usable input limit from it."
        )
    if reported != model_spec.max_sequence_length:
        raise ModelIdentityError(
            f"{model_spec.model_id}: tokenizer model_max_length={reported} does not "
            f"match registry max_sequence_length={model_spec.max_sequence_length}. "
            "The registry value must be the tokenizer's real reported limit, not a "
            "model-card training length -- fix the registry, don't override it here."
        )
    return reported


def load_target_model(target_id: str, registry: Optional[Registry] = None) -> LoadedTarget:
    """Load the real model/tokenizer for `target_id` and validate its identity.

    Loads weights -- this is not free and not model-free. Call it once per process,
    at the calling endpoint module's import time, never inside a request handler and
    never from anything that must stay model-free (``endpoint/targets.py``, the
    runner's ``--help`` path, offline fixture tests).
    """
    registry = registry if registry is not None else load_registry()
    model_spec = registry.model_for(target_id)

    tokenizer = AutoTokenizer.from_pretrained(
        model_spec.tokenizer_id, revision=model_spec.tokenizer_revision
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_spec.model_id, revision=model_spec.revision
    )

    _validate_label_space(model_spec, model.config.id2label)
    max_sequence_length = _resolve_usable_max_length(model_spec, tokenizer)

    # top_k=None -> return every label's score, not just the winner.
    # truncation=False -> never silently trim input. See module docstring and
    # docs/stage3/MODEL_IDENTITY.md: no truncation anywhere on this path, pipeline,
    # tokenizer call or request handler.
    classifier = pipeline(
        task="text-classification",
        model=model,
        tokenizer=tokenizer,
        top_k=None,
        truncation=False,
    )

    def predict(text: str) -> list[dict]:
        results = classifier(text, truncation=False)
        # With top_k=None, the pipeline returns a nested list for a single input
        # string: [[{...}, ...]]. Unwrap it, same as endpoint/model.py.
        if len(results) > 0 and isinstance(results[0], list):
            results = results[0]
        return results

    return LoadedTarget(
        target_id=target_id,
        model_spec=model_spec,
        max_sequence_length=max_sequence_length,
        predict=predict,
    )


def format_response(scores: list[dict]) -> dict:
    """Shape raw predict() output into the shared response contract.

    Deliberately duplicated from ``endpoint/model.py`` rather than imported from it --
    importing that module loads the emotion model as a side effect, which is exactly
    what a sentiment-only process must not do. Keep this in sync by hand; the shape is
    frozen by CONTRACTS.md, not likely to drift.
    """
    top = max(scores, key=lambda item: item["score"])
    all_scores = {item["label"]: item["score"] for item in scores}
    return {
        "label": top["label"],
        "confidence": top["score"],
        "all_scores": all_scores,
    }

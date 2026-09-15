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

from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)

from contract import ModelSpec, Registry
from endpoint.targets import load_registry

# transformers' PreTrainedTokenizerBase defaults model_max_length to int(1e30) when a
# tokenizer config sets no explicit value. That is a "no limit configured" sentinel,
# not a real limit, and must never be trusted as one.
_UNSET_MAX_LENGTH_SENTINEL = int(1e30)

# Position ids a family reserves before the first real token, so the usable limit is
# max_position_embeddings minus this. RoBERTa-style models start position ids at
# padding_idx + 1 = 2; BERT/DistilBERT start at 0. Anything not listed reserves none.
_RESERVED_POSITIONS_BY_MODEL_TYPE = {
    "roberta": 2,
    "xlm-roberta": 2,
    "camembert": 2,
    "longformer": 2,
}


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


def _inference_capacity(config) -> Optional[int]:
    """Positions this architecture can actually attend over, or None if unknowable.

    This is the "actual inference capacity" the task separates from a model card's
    *training* sequence length. It is read from the pinned ``config.json``, never from
    prose: ``max_position_embeddings`` is the size of the learned position embedding
    table, so a longer input indexes past the end of that table and the forward pass
    fails -- it is a hard architectural ceiling, not a recommendation.

    RoBERTa-family models reserve the first two position ids (``padding_idx`` is 1 and
    position ids start at ``padding_idx + 1``), which is why the emotion model reports
    ``max_position_embeddings=514`` and a real usable limit of 512. BERT/DistilBERT
    reserve none, so 512 means 512. Both numbers include the special tokens, exactly as
    ``ModelSpec.max_sequence_length`` is defined to.

    Returns ``None`` -- not a guess -- when the config declares no position table, so a
    caller records "not derivable from this config" instead of inventing a boundary.
    """
    positions = getattr(config, "max_position_embeddings", None)
    if not isinstance(positions, int) or isinstance(positions, bool) or positions <= 0:
        return None
    offset = _RESERVED_POSITIONS_BY_MODEL_TYPE.get(getattr(config, "model_type", ""), 0)
    capacity = positions - offset
    return capacity if capacity > 0 else None


def _validate_inference_capacity(model_spec: ModelSpec, config) -> Optional[int]:
    """The declared limit must be the architecture's real capacity, when derivable."""
    capacity = _inference_capacity(config)
    if capacity is None:
        return None
    if capacity != model_spec.max_sequence_length:
        raise ModelIdentityError(
            f"{model_spec.model_id}: pinned config gives an inference capacity of "
            f"{capacity} tokens (max_position_embeddings="
            f"{getattr(config, 'max_position_embeddings', None)}, model_type="
            f"{getattr(config, 'model_type', None)!r}), but the registry declares "
            f"max_sequence_length={model_spec.max_sequence_length}. Boundary attacks "
            "built on the registry value would sit on the wrong token, so this is a "
            "configuration error, not something to round off here."
        )
    return capacity


@dataclass(frozen=True)
class TokenizerContext:
    """A target's tokenizer and token limit, loaded WITHOUT any model weights.

    This is what the runner needs and all it needs: boundary attacks have to land on
    the true token limit of the target actually under test, and building them must not
    drag a second model into the process. Loading this for ``sentiment_v1`` imports no
    ``endpoint.model``, downloads no weights and allocates no tensors -- only the
    pinned ``tokenizer.json``/``vocab.txt`` and ``config.json``.
    """

    target_id: str
    task_id: str
    model_spec: ModelSpec
    # Confirmed against the live tokenizer AND, when the config allows it to be
    # derived, against the architecture's real position-table capacity.
    max_tokens: int
    # None when the pinned config declares no position table -- recorded as unknown
    # rather than assumed equal to the tokenizer's limit.
    inference_capacity: Optional[int]
    # text -> token count including special tokens. Never truncates.
    count_tokens: Callable[[str], int]

    def describe(self) -> dict:
        """A JSON-safe record of what was verified, for a run's metadata."""
        return {
            "target_id": self.target_id,
            "task_id": self.task_id,
            "model_id": self.model_spec.model_id,
            "model_revision": self.model_spec.revision,
            "tokenizer_id": self.model_spec.tokenizer_id,
            "tokenizer_revision": self.model_spec.tokenizer_revision,
            "labels": list(self.model_spec.labels),
            "max_tokens": self.max_tokens,
            "inference_capacity": self.inference_capacity,
            "weights_loaded": False,
        }


def load_target_tokenizer(
    target_id: str, registry: Optional[Registry] = None
) -> TokenizerContext:
    """Load only the pinned tokenizer and config for `target_id`. No weights.

    Use this anywhere a token count or a length boundary is needed for a target --
    above all in the runner, where importing ``endpoint.model`` would load the
    *emotion* classifier's weights into a sentiment run and silently give every
    boundary case the wrong tokenizer.

    Validates the same declared-vs-actual identity as :func:`load_target_model`, minus
    the parts that genuinely need weights: label space comes from the pinned config
    here rather than from a loaded ``model.config``.
    """
    registry = registry if registry is not None else load_registry()
    task = registry.task_for(target_id)
    model_spec = registry.model_for(target_id)

    tokenizer = AutoTokenizer.from_pretrained(
        model_spec.tokenizer_id, revision=model_spec.tokenizer_revision
    )
    config = AutoConfig.from_pretrained(model_spec.model_id, revision=model_spec.revision)

    _validate_label_space(model_spec, config.id2label)
    max_tokens = _resolve_usable_max_length(model_spec, tokenizer)
    capacity = _validate_inference_capacity(model_spec, config)

    def count_tokens(text: str) -> int:
        # truncation=False is the whole point: a truncated count would report the
        # limit for any oversized input, and the boundary cases built from it would
        # all collapse onto the same length.
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    return TokenizerContext(
        target_id=target_id,
        task_id=task.task_id,
        model_spec=model_spec,
        max_tokens=max_tokens,
        inference_capacity=capacity,
        count_tokens=count_tokens,
    )


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
    _validate_inference_capacity(model_spec, model.config)

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
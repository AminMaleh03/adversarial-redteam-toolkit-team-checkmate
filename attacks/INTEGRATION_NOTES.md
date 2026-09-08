# Attack library - integration notes (Lamei)

Notes for Amin (runner), Ahsan (contract/report) and Khalid (analysis). Nothing here
changes `contract.py`; these are things to agree on before wiring the runner in.

## 1. `is_raw` means "send verbatim", not literally "invalid JSON"  (Ahsan + Amin)
`contract.py` documents `is_raw=True` as "this is not valid JSON". The library uses raw
mode more broadly: **any body that cannot be produced by serialising `{"text": "<string>"}`**.
That includes bodies that are perfectly valid JSON but the wrong shape/type:
- type confusion: `{"text": 123}`, `{"text": null}`, `{"text": [...]}`
- schema: missing/renamed/**extra** field, deeply nested JSON, wrong top-level type
- encoding-boundary: UTF-8 BOM, trailing garbage

**Operational contract the runner must follow:** if `is_raw` is True, send `raw_body` and
`raw_headers` exactly as given; do not re-serialise, and do not add/override headers.

## 2. `raw_body` can be `bytes`  (Amin)
Two transport cases (`malformed.utf8_bom`, `malformed.malformed_utf8`) set `raw_body` to
`bytes`, including **intentionally invalid UTF-8**. Send those bytes on the wire unchanged
— do not `.decode()`/`.encode()` them. `contract.AttackCase.raw_body` is typed
`Optional[Union[bytes, str]]`, so this is within contract.

## 3. `extra_field` is the ONE clean V1/V2 difference — measure it  (Ahsan + Amin)
`{"text":"...","surprise":"..."}` should be **accepted by V1** (Pydantic default
`extra="ignore"`) and **rejected by V2** (`extra="forbid"`). This is the cleanest
before/after row. But it only holds if V1 uses plain Pydantic defaults. **Please confirm
V1's model config and measure it before it goes in the report.** Note also: the int
type-confusion case (`{"text":123}`) is *not* a V1/V2 difference — plain Pydantic v2
already rejects it, so both should 422.

## 4. Exact token boundaries need the real tokenizer  (Amin)
`library.standalone_cases()` with no args produces **approximate** length boundaries
(`boundary_source="approximate_word_estimate"`). To get exact N-1 / N / N+1 cases, call:
```python
from endpoint.model import tokenizer, MAX_SEQUENCE_LENGTH
count = lambda s: len(tokenizer.encode(s, add_special_tokens=True))
cases = library.standalone_cases(token_counter=count, max_tokens=MAX_SEQUENCE_LENGTH)
```
The measured token count is stored in each case's metadata (`boundary_measured`).

## 5. Metadata manifest for analysis + report  (Khalid + Ahsan)
Every case's relation/oracle/provenance/expected-V2-behaviour lives in the sidecar,
keyed by `attack_id`. After building the suite, dump it with:
```python
library.write_manifest("results/attack_manifest.json")
```
Use the `oracle` field to decide what "failure" means per case; **never auto-score
`REVIEW` or `DIAGNOSTIC` cases** as vulnerabilities. `expected_sanitizer_behavior` /
`expected_http_behavior` are hypotheses for the before/after column — measured, not asserted.

## 6. Runtime  (Amin)
~33 standalone + up to ~44 derived per baseline. At ~40 baselines that is ~1,793 cases,
≈3,586 requests across V1+V2. Fine, but if a run drags, the cheapest trim is the homoglyph
3x3 matrix. The 10 MB oversized case dominates payload size — make sure the client
timeout (10 s) and any body-size limits are set with that in mind.

---

# Phase 2 proposal (NOT enabled): directional tests

Everything above is **invariance** testing: same meaning -> label must not change. A
complementary, high-value test is **directional**: deliberately change the meaning and
check the prediction moves in the expected direction. This catches a model that is *too*
invariant, which our current suite cannot detect. CheckList (Ribeiro et al., ACL 2020)
explicitly separates INV from DIR tests, so this is standard, not feature creep.

Examples (emotion classifier):
- negation:   "I am happy today"        -> "I am not happy today"      (joy -> not joy)
- reversal:   "the service was awful"   -> "the service was wonderful"  (disgust -> joy)
- intensity:  "I am slightly afraid"    -> "I am absolutely terrified"  (fear, higher conf)

Why it is not in this branch:
- It **changes the oracle**: the expected label is no longer "same as baseline", so it
  needs Khalid to define expected labels / relationships (gold data), not the model-blind
  generator inventing them.
- The vocabulary is already staged: `metadata.REL_DIRECTIONAL` exists and is reserved.

What we would need to turn it on:
1. Khalid provides, per directional template, the expected label (or expected direction of
   change) as gold data in `baseline/`.
2. Analysis adds a directional check: prediction moved as expected = pass; did not move =
   finding ("model insensitive to a real meaning change").
3. The generator adds a `directional.py` producing `REL_DIRECTIONAL` cases from those seeds.

**Decision needed from Ahsan/Khalid:** do we want an opt-in Phase 2 directional suite? It
is a strong innovation angle (robustness *and* sensitivity), but only if the gold labels
are defined properly — otherwise it is not defensible.

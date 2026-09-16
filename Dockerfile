# Team Checkmate -- System V4 Hugging Face Docker Space.
#
# Thin deployment image: it installs the exact pinned dependencies already used locally,
# pre-caches the pinned model revision so a judge's first live run doesn't pay a cold
# download, and serves the public web layer in web/app.py on the Hugging Face-required
# port 7860. It does not rebuild or reimplement any of the validated V1/V2/runner/
# analysis/report pipeline -- see AGENTS.md and HANDOFF.md.

FROM python:3.11-slim-bookworm

# WeasyPrint (pinned in requirements.txt) needs these Debian runtime libraries for text
# shaping/rendering. This is the minimal set, not a full GTK/desktop environment -- see
# AGENTS.md's WeasyPrint notes.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface

# Cache every model and tokenizer from the static registry at its exact revision. Copying
# only the registry here keeps ordinary source/UI edits from invalidating this expensive
# layer while ensuring a pin change necessarily rebuilds it.
COPY endpoint/targets.json /tmp/targets.json
RUN python -c "\
import json; \
from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
models=json.load(open('/tmp/targets.json', encoding='utf-8'))['models']; \
[(AutoTokenizer.from_pretrained(m['tokenizer_id'], revision=m['tokenizer_revision']), AutoModelForSequenceClassification.from_pretrained(m['model_id'], revision=m['revision'])) for m in models.values()]; \
print('all registry models and tokenizers cached at pinned revisions')"

# Runtime never depends on network access to load the model -- it must come from the
# image's own baked cache, matching the pinned revision above exactly.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY . .

# Standard Hugging Face Spaces non-root user. Created/chowned after COPY so the copied
# application source (owned by root at COPY time) ends up readable/writable as needed.
RUN useradd -m -u 1000 user \
    && mkdir -p /app/results \
    && chown -R user:user /app

USER user

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]

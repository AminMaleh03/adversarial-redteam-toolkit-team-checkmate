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

# Pre-download the exact pinned model/tokenizer revision at build time (network available
# during build), so the image can run the model from its baked cache with no first-run
# download. Same model ID/revision constants as endpoint/model.py; never fetches
# unpinned `main`. Placed BEFORE `COPY . .` -- it only needs the installed dependencies
# above, not the application source -- so ordinary source/frontend changes invalidate
# neither this layer nor the pip-install layer above it; only `COPY . .` onward rebuilds.
RUN python -c "\
from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
MODEL_NAME = 'j-hartmann/emotion-english-distilroberta-base'; \
MODEL_REVISION = '0e1cd914e3d46199ed785853e12b57304e04178b'; \
AutoTokenizer.from_pretrained(MODEL_NAME, revision=MODEL_REVISION); \
AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, revision=MODEL_REVISION); \
print('model cached at pinned revision')"

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

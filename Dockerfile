FROM ghcr.io/gh0stkey/opf-privacy-filter:latest

LABEL org.opencontainers.image.title="PII Span Extractor"
LABEL org.opencontainers.image.description="Structured PII span extraction API powered by OpenAI Privacy Filter"
LABEL org.opencontainers.image.source="https://github.com/hi-unc1e/pii-span-extractor"

WORKDIR /app

# Reuse the upstream OPF runtime and baked model, but replace the HTTP layer
# with this project's extraction-first API.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=opf:opf server.py /app/server.py
USER opf

ENV OPF_DEVICE=cpu
ENV OPF_OUTPUT_MODE=typed
ENV HOME=/home/opf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--workers", "2"]

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Clone the official OpenAI Privacy Filter repo.
RUN git clone --depth 1 https://github.com/openai/privacy-filter.git .

# Install dependencies (CPU-only torch to keep the image small).
RUN pip install --no-cache-dir --prefix=/install \
    torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --prefix=/install -e . && \
    pip install --no-cache-dir --prefix=/install fastapi uvicorn[standard]

# --- Final stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local
# Copy the project source
COPY --from=builder /build /app

# Copy the PII Span Extractor HTTP server.
COPY server.py .

# Create a non-root runtime user. The model is intentionally not baked into
# the public image; mount it with OPF_CHECKPOINT in production, or let OPF
# download it into HOME on first startup for demos.
RUN useradd -m -s /bin/bash extractor
USER extractor

ENV OPF_DEVICE=cpu
ENV OPF_OUTPUT_MODE=typed
ENV HOME=/home/extractor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]

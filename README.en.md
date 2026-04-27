# PII Span Extractor

Language: [中文](README.zh-CN.md) | **English** | [Default README](README.md)

## Positioning

PII Span Extractor is a production-oriented service for extracting structured
PII spans from unstructured text.

If you need **privacy filtering or redaction**, use the official
[OpenAI Privacy Filter](https://github.com/openai/privacy-filter). If you need
**PII extraction**, this project provides a direct HTTP API, demo scripts,
benchmarking tools, and quality evaluation.

Input:

```text
My name is Alice Smith and my email is alice@example.com.
```

Output:

```json
{
  "label": "private_email",
  "start": 39,
  "end": 56,
  "text": "alice@example.com"
}
```

## Value

- Turn logs, tickets, emails, and contracts into structured PII spans.
- Return label, source text, and character offsets for audit and governance.
- Run on-premises or inside a private network.
- Keep the original redaction API while adding extraction-first workflows.

## Supported Labels

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

## Quick Start

```bash
docker pull ghcr.io/hi-unc1e/pii-span-extractor:latest
```

CPU:

```bash
docker run -d \
  -p 8000:8000 \
  -e OPF_DEVICE=cpu \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

GPU:

```bash
docker run -d \
  -p 8000:8000 \
  --gpus all \
  -e CC=gcc \
  -e OPF_DEVICE=cuda \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

Health check:

```bash
curl http://localhost:8000/health
```

For mainland China deployments, pre-download the model and point the service
to a local checkpoint:

```bash
OPF_CHECKPOINT=/models/privacy_filter
OPF_OUTPUT_MODE=typed
OPF_DEVICE=cpu
```

## Extraction API

Recommended production-style hybrid request:

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Alice Smith and my email is alice@example.com. Call me at 555-123-4567.",
    "include_text": true,
    "merge_adjacent": true,
    "merge_strategy": "label_aware",
    "enable_regex_backstop": true,
    "trim_punctuation": true
  }'
```

Response:

```json
{
  "schema_version": 1,
  "extracted_spans": [
    {
      "label": "private_person",
      "start": 11,
      "end": 22,
      "text": "Alice Smith"
    },
    {
      "label": "private_email",
      "start": 39,
      "end": 56,
      "text": "alice@example.com"
    }
  ]
}
```

Batch extraction:

```bash
curl -X POST http://localhost:8000/extract/batch \
  -H "Content-Type: application/json" \
  -d '{
    "texts": [
      "Call Alice at 555-123-4567",
      "Send mail to bob@example.com"
    ],
    "labels": ["private_phone", "private_email"]
  }'
```

## Request Options

- `labels`: return only selected labels.
- `include_text`: include or omit sensitive source text.
- `merge_adjacent`: merge adjacent same-label spans.
- `merge_strategy=label_aware`: use label-specific gap rules for merging.
- `enable_regex_backstop`: add high-confidence URL, secret, and account spans.
- `trim_punctuation`: trim common trailing punctuation.

## Redaction API

The original redaction workflow is still available:

```bash
curl -X POST http://localhost:8000/redact \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

Text-only redaction:

```bash
curl -X POST http://localhost:8000/redact/text \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

## Demo

```bash
scripts/demo_extract_api.py --base-url http://localhost:8000
```

Remote verification:

```bash
OPF_SSH_HOST=8.215.27.92 \
OPF_SSH_USER=root \
OPF_SSH_PORT=22 \
OPF_BASE_URL=http://localhost:8000 \
scripts/verify_remote_extract_api.sh
```

## Benchmark

Throughput benchmark:

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --profile hybrid \
  --sizes 1K,10K \
  --estimate-over-bytes 10240
```

Quality evaluation:

```bash
scripts/evaluate_extract_quality.py \
  --base-url http://localhost:8000 \
  --profiles baseline,hybrid
```

Validated result:

```text
baseline exact F1: 0.9231
hybrid   exact F1: 1.0000
```

CPU mode is suitable for demos, small evaluations, and low-frequency offline
jobs. For MB/GB-scale files, use GPU inference, async queues, and chunked
processing.

## Build

```bash
docker build -t ghcr.io/hi-unc1e/pii-span-extractor:latest .
docker run -d -p 8000:8000 ghcr.io/hi-unc1e/pii-span-extractor:latest
```

## Research Branch

The `privacy-parser` research notes and detailed comparison remain on the
side branch `codex/extract-demo-benchmark`. The main branch keeps only
production-facing code and documentation.

## License

Apache-2.0.

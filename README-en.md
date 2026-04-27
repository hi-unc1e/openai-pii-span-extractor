# PII Span Extractor

Language: [中文](README.md) | **English**

PII Span Extractor is a production-oriented service for extracting privacy
signals from unstructured text. It is powered by the
[OpenAI Privacy Filter](https://github.com/openai/privacy-filter) model and
returns structured spans:

```text
label + text + start offset + end offset
```

If you need **privacy filtering or redaction**, use the official project. If
you need **privacy extraction from logs, tickets, emails, contracts, or data
lake text**, this project provides a direct HTTP API, demos, benchmarks, and
quality evaluation tools.

## Use Cases

- **AI data governance**: discover PII and secrets before enterprise text is
  used in RAG, training datasets, analytics, or data lakes.
- **Security audit and DLP**: convert hidden sensitive text into searchable
  security signals.
- **Redaction preflight**: locate names, emails, phones, addresses, accounts,
  URLs, dates, and secrets before applying policy-specific masking.
- **Compliance and data transfer review**: produce structured evidence for
  privacy inventory, data classification, and cross-border review.

## Deployment

Pull the image:

```bash
docker pull ghcr.io/hi-unc1e/pii-span-extractor:latest
```

The image is built from `ghcr.io/gh0stkey/opf-privacy-filter:latest`. It
reuses the upstream OPF runtime and cached model layer, then replaces the HTTP
layer with this project's extraction-first API. Demo startup is therefore
simpler and usually does not need to download the model again.

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

For custom checkpoints or mainland China deployments, you can still point the
service to a local model:

```bash
OPF_CHECKPOINT=/models/privacy_filter
OPF_OUTPUT_MODE=typed
OPF_DEVICE=cpu
```

Example with a mounted local model:

```bash
docker run -d \
  -p 8000:8000 \
  -v /models/privacy_filter:/models/privacy_filter:ro \
  -e OPF_CHECKPOINT=/models/privacy_filter \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

## Extraction Demo

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

Example response:

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

Run the long-text demo:

```bash
scripts/demo_extract_api.py --base-url http://localhost:8000
```

## Supported Labels

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

## API Options

- `labels`: return only selected labels.
- `include_text`: include or omit sensitive source text.
- `merge_adjacent`: merge adjacent same-label spans.
- `merge_strategy=label_aware`: use label-specific gap rules for merging.
- `enable_regex_backstop`: add high-confidence URL, secret, and account spans.
- `trim_punctuation`: trim common trailing punctuation.

Recommended production-style hybrid options:

```json
{
  "merge_adjacent": true,
  "merge_strategy": "label_aware",
  "enable_regex_backstop": true,
  "trim_punctuation": true
}
```

## Batch Extraction

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

## Redaction Compatibility

The original redaction API is still available:

```bash
curl -X POST http://localhost:8000/redact \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

## Performance and Quality

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

### L20 GPU Concurrency Benchmark

Environment: NVIDIA L20 (46 GB), CUDA inference, `OPF_OUTPUT_MODE=typed`,
short text (~318 B).

Staircase concurrency via `scripts/concurrency_benchmark_extract_api.py`,
20-30 s per level:

| Concurrency | RPS | Avg Latency (ms) | P50 (ms) | P95 (ms) | Errors | GPU Util | VRAM (MB) |
|-------------|-----:|---------:|--------:|--------:|-------:|--------:|--------:|
| 1           | 62.9 |   15.9  |  16.0   |  16.5   |  0     | 39 %    | 3 537   |
| 2           | 71.9 |   27.8  |  27.4   |  30.6   |  0     | 44 %    | 3 667   |
| 4           | 60.4 |   66.2  |  66.1   |  71.9   |  0     | 40 %    | 3 667   |
| 6           | 43.2 |  138.8  | 139.2   | 145.4   |  0     | 27 %    | 3 667   |
| 8           | 40.0 |  199.6  | 199.5   | 207.7   |  0     | 26 %    | 3 667   |
| 10          | 38.6 |  258.9  | 259.0   | 269.5   |  0     | 25 %    | 3 669   |
| 12          | 38.2 |  313.6  | 313.6   | 326.8   |  0     | 29 %    | 3 669   |

Key findings:

- **Optimal concurrency is 2**, peak throughput ~72 RPS, ~28 ms latency,
  GPU utilization ~44 %.
- Concurrency ≥ 4 shows throughput decline and linear latency growth; GPU
  utilization drops—the bottleneck is single-process scheduling, not GPU
  compute.
- VRAM stays at ~3.7 GB / 46 GB; the model is very lightweight.

Reproduce:

```bash
python scripts/concurrency_benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --levels 1,2,4,6,8,10,12 \
  --duration 30 \
  --sample-gpu
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

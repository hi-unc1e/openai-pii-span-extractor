# PII Span Extractor

语言切换：**中文** | [English](README.en.md) | [默认 README](README.md)

## 项目定位

PII Span Extractor 是一个面向工程落地的敏感信息提取服务。

如果目标是 **隐私过滤/脱敏**，用户可以直接使用官方
[OpenAI Privacy Filter](https://github.com/openai/privacy-filter)。
如果目标是 **从非结构化文本中提取敏感信息**，本项目提供更直接的 HTTP API、
Demo、Benchmark 和质量评估工具。

输入：

```text
My name is Alice Smith and my email is alice@example.com.
```

输出：

```json
{
  "label": "private_email",
  "start": 39,
  "end": 56,
  "text": "alice@example.com"
}
```

## 核心价值

- 把日志、工单、邮件、合同中的 PII 转成结构化 span。
- 返回类别、内容、字符索引，便于审计、治理、脱敏和告警。
- 支持本地或内网部署，敏感文本无需发往第三方 SaaS。
- 保留官方脱敏能力，同时新增提取能力。

## 支持类别

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

## 快速启动

```bash
docker pull ghcr.io/hi-unc1e/pii-span-extractor:latest
```

CPU 模式：

```bash
docker run -d \
  -p 8000:8000 \
  -e OPF_DEVICE=cpu \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

GPU 模式：

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

健康检查：

```bash
curl http://localhost:8000/health
```

国内节点建议提前把模型放到本地路径，然后通过 `OPF_CHECKPOINT` 加载：

```bash
OPF_CHECKPOINT=/models/privacy_filter
OPF_OUTPUT_MODE=typed
OPF_DEVICE=cpu
```

## 提取 API

生产建议使用 hybrid 参数：

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

返回：

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

批量提取：

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

## 参数说明

- `labels`：只返回指定类别。
- `include_text`：是否返回敏感原文。
- `merge_adjacent`：是否合并相邻同类 span。
- `merge_strategy=label_aware`：按类别允许短间隔合并，改善姓名、地址、日期边界。
- `enable_regex_backstop`：对 URL、secret、账号做高置信规则回补。
- `trim_punctuation`：修剪结构化 span 尾部常见标点。

## 脱敏接口

本项目仍保留原有脱敏能力：

```bash
curl -X POST http://localhost:8000/redact \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

只返回脱敏文本：

```bash
curl -X POST http://localhost:8000/redact/text \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

## Demo

```bash
scripts/demo_extract_api.py --base-url http://localhost:8000
```

远程验证：

```bash
OPF_SSH_HOST=8.215.27.92 \
OPF_SSH_USER=root \
OPF_SSH_PORT=22 \
OPF_BASE_URL=http://localhost:8000 \
scripts/verify_remote_extract_api.sh
```

## Benchmark

吞吐测试：

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --profile hybrid \
  --sizes 1K,10K \
  --estimate-over-bytes 10240
```

质量评估：

```bash
scripts/evaluate_extract_quality.py \
  --base-url http://localhost:8000 \
  --profiles baseline,hybrid
```

已验证结果：

```text
baseline exact F1: 0.9231
hybrid   exact F1: 1.0000
```

纯 CPU 模式适合 Demo、小批量验证和低频离线任务。处理 MB/GB 级文件时，
建议使用 GPU、异步队列和分块处理。

## 构建

```bash
docker build -t ghcr.io/hi-unc1e/pii-span-extractor:latest .
docker run -d -p 8000:8000 ghcr.io/hi-unc1e/pii-span-extractor:latest
```

## 研究分支

`privacy-parser` 调研文档和详细对比分析保留在旁路分支
`codex/extract-demo-benchmark`，主干仅保留生产运行所需内容。

## License

Apache-2.0。

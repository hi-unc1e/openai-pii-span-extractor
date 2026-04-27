# PII Span Extractor

语言切换：**中文** | [English](README.en.md)

> 从非结构化文本中提取结构化敏感信息 span：类别、内容、起止索引。

PII Span Extractor 基于 OpenAI Privacy Filter 模型构建。官方项目侧重
隐私过滤和脱敏；本项目定位为 **隐私信息提取**：把文本中的姓名、邮箱、
电话、地址、账号、URL、日期和 secret 转换为可审计、可检索、可治理的
结构化结果。

完整中文文档见：[README.zh-CN.md](README.zh-CN.md)。

## 快速开始

```bash
docker pull ghcr.io/hi-unc1e/pii-span-extractor:latest

docker run -d \
  -p 8000:8000 \
  -e OPF_DEVICE=cpu \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

健康检查：

```bash
curl http://localhost:8000/health
```

提取敏感信息：

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Alice Smith and my email is alice@example.com. Call me at 555-123-4567.",
    "merge_adjacent": true,
    "merge_strategy": "label_aware",
    "enable_regex_backstop": true,
    "trim_punctuation": true
  }'
```

示例输出：

```json
{
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

## 支持类别

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

## 使用场景

- 数据入湖前识别 PII。
- 日志、工单、邮件、合同中的敏感信息盘点。
- DLP、分类分级、合规审计的上游结构化信号。
- 脱敏前置检查：先定位敏感信息，再按策略处理。

## Benchmark 与质量评估

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

当前测试结论：

```text
baseline exact F1: 0.9231
hybrid   exact F1: 1.0000
```

纯 CPU 可用于 Demo 和低频离线任务；生产建议使用 GPU、异步队列和分块处理。

## 与官方项目的关系

- 需要隐私过滤/脱敏：优先使用官方 OpenAI Privacy Filter。
- 需要隐私提取/结构化 span：使用本项目。

底层仍使用 OpenAI Privacy Filter 模型，因此环境变量保留 `OPF_*` 命名。

## 研究文档

`privacy-parser` 调研和对比分析保留在旁路分支
`codex/extract-demo-benchmark`，不合入主干生产文档。

## License

Apache-2.0。

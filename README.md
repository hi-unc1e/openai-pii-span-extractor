# PII Span Extractor

语言：**中文** | [English](README-en.md)

PII Span Extractor 是一个面向工程落地的隐私信息提取服务。它基于
[OpenAI Privacy Filter](https://github.com/openai/privacy-filter) 模型，
将非结构化文本中的敏感信息转换为结构化 span：

```text
label + text + start offset + end offset
```

如果你需要 **隐私过滤/脱敏**，可以直接使用官方项目；如果你需要
**从日志、工单、邮件、合同、数据湖文本中提取隐私信息**，本项目提供
更直接的 HTTP API、Demo、Benchmark 和质量评估工具。

## 使用场景

- **AI 数据治理**：在把企业文档、客服工单、日志送入 RAG、训练集或数据湖前，
  先发现其中的 PII 和 secret。
- **安全审计与 DLP**：把散落在非结构化文本里的敏感信息转成可检索的安全信号。
- **脱敏前置分析**：先定位姓名、邮箱、电话、地址、账号、URL、日期和密钥，
  再按业务策略脱敏或阻断。
- **合规与数据出境检查**：为隐私盘点、分类分级、跨境评估提供结构化证据。

## 部署

拉取镜像：

```bash
docker pull ghcr.io/hi-unc1e/pii-span-extractor:latest
```

本镜像基于 `ghcr.io/gh0stkey/opf-privacy-filter:latest` 构建，复用上游
OPF 运行时和已缓存模型层，只替换为本项目的提取优先 HTTP API。因此
Demo 启动更简单，首次启动通常不需要重新下载模型。

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

如需使用自定义模型或国内节点本地模型，也可以通过 `OPF_CHECKPOINT` 加载：

```bash
OPF_CHECKPOINT=/models/privacy_filter
OPF_OUTPUT_MODE=typed
OPF_DEVICE=cpu
```

挂载本地模型目录示例：

```bash
docker run -d \
  -p 8000:8000 \
  -v /models/privacy_filter:/models/privacy_filter:ro \
  -e OPF_CHECKPOINT=/models/privacy_filter \
  -e OPF_OUTPUT_MODE=typed \
  --name pii-span-extractor \
  ghcr.io/hi-unc1e/pii-span-extractor:latest
```

## 提取 Demo

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

示例输出：

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

也可以直接运行长文本 Demo：

```bash
scripts/demo_extract_api.py --base-url http://localhost:8000
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

## API 参数

- `labels`：只返回指定类别。
- `include_text`：是否返回敏感原文。
- `merge_adjacent`：是否合并相邻同类 span。
- `merge_strategy=label_aware`：按类别允许短间隔合并，改善姓名、地址、日期边界。
- `enable_regex_backstop`：对 URL、secret、账号做高置信规则回补。
- `trim_punctuation`：修剪结构化 span 尾部常见标点。

生产建议使用 hybrid 参数：

```json
{
  "merge_adjacent": true,
  "merge_strategy": "label_aware",
  "enable_regex_backstop": true,
  "trim_punctuation": true
}
```

## 批量提取

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

## 脱敏兼容

本项目仍保留原有脱敏接口：

```bash
curl -X POST http://localhost:8000/redact \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John and my email is john@example.com"}'
```

## 性能与质量评估

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

当前验证结果：

```text
baseline exact F1: 0.9231
hybrid   exact F1: 1.0000
```

### L20 GPU 并发测试

测试环境：NVIDIA L20 (46 GB)，CUDA 推理，`OPF_OUTPUT_MODE=typed`，短文本 (~318 B)。

使用 `scripts/concurrency_benchmark_extract_api.py` 阶梯并发，每档 20-30 s：

| 并发 | RPS | 平均延迟 (ms) | P50 (ms) | P95 (ms) | 错误 | GPU 利用率 | 显存 (MB) |
|------|------:|---------:|--------:|--------:|-----:|---------:|--------:|
| 1    |  62.9 |    15.9  |  16.0   |  16.5   |   0  |  39 %    | 3 537   |
| 2    |  71.9 |    27.8  |  27.4   |  30.6   |   0  |  44 %    | 3 667   |
| 4    |  60.4 |    66.2  |  66.1   |  71.9   |   0  |  40 %    | 3 667   |
| 6    |  43.2 |   138.8  | 139.2   | 145.4   |   0  |  27 %    | 3 667   |
| 8    |  40.0 |   199.6  | 199.5   | 207.7   |   0  |  26 %    | 3 667   |
| 10   |  38.6 |   258.9  | 259.0   | 269.5   |   0  |  25 %    | 3 669   |
| 12   |  38.2 |   313.6  | 313.6   | 326.8   |   0  |  29 %    | 3 669   |

结论：

- **最优并发为 2**，吞吐峰值 ~72 RPS，延迟 ~28 ms，GPU 利用率 ~44 %。
- 并发 ≥ 4 后吞吐下降、延迟线性增长，GPU 利用率反而降低——瓶颈是单进程推理调度，非 GPU 算力。
- 显存占用稳定在 ~3.7 GB / 46 GB，模型本身非常轻量。

复现命令：

```bash
python scripts/concurrency_benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --levels 1,2,4,6,8,10,12 \
  --duration 30 \
  --sample-gpu
```

纯 CPU 适合 Demo、小批量验证和低频离线任务。生产处理 MB/GB 级文件时，
建议使用 GPU、异步队列和分块处理。

## 构建

```bash
docker build -t ghcr.io/hi-unc1e/pii-span-extractor:latest .
docker run -d -p 8000:8000 ghcr.io/hi-unc1e/pii-span-extractor:latest
```

## 研究分支

`privacy-parser` 调研和详细对比分析保留在旁路分支
`codex/extract-demo-benchmark`，主干仅保留生产运行所需内容。

## License

Apache-2.0。

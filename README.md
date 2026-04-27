# OPF Privacy Filter 提取服务

基于 [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) 的
PII 敏感信息识别服务。项目原本用于文本脱敏，本仓库在保留脱敏能力的基础上，
新增了“反向提取”接口：输入非结构化文本，输出敏感信息类别、内容和索引。

## 适用场景

- 从客服工单、日志、邮件、合同草稿中提取 PII。
- 在数据入湖、标注、审计前识别敏感字段。
- 评估文本清洗、脱敏、数据治理链路的工程吞吐。
- 在内网或本地 CPU/GPU 环境中部署可控的 PII 检测服务。

支持的类别：

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

## 原理简述

OpenAI Privacy Filter 是 token-classification 模型。模型对输入文本的每个
token 输出 BIOES 标签，再通过约束解码得到连续 span。

本服务复用 OPF 的 `redact()` 推理结果：

```text
非结构化文本
  -> OPF token classification
  -> detected_spans
  -> /extract 输出结构化敏感信息
```

因此新增提取能力不需要修改模型权重，也不需要重新训练。

## 快速启动

拉取镜像：

```bash
docker pull ghcr.io/gh0stkey/opf-privacy-filter:latest
```

CPU 模式启动：

```bash
docker run -d \
  -p 8000:8000 \
  -e OPF_DEVICE=cpu \
  -e OPF_OUTPUT_MODE=typed \
  --name opf \
  ghcr.io/gh0stkey/opf-privacy-filter:latest
```

GPU 模式启动：

```bash
docker run -d \
  -p 8000:8000 \
  --gpus all \
  -e CC=gcc \
  -e OPF_DEVICE=cuda \
  -e OPF_OUTPUT_MODE=typed \
  --name opf \
  ghcr.io/gh0stkey/opf-privacy-filter:latest
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

## 提取 Demo

运行长文本 Demo：

```bash
scripts/demo_extract_api.py --base-url http://localhost:8000
```

示例请求：

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

按类别过滤：

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Alice Smith and my email is alice@example.com.",
    "labels": ["private_email"]
  }'
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

生产建议使用 `hybrid` 风格参数：

```json
{
  "merge_adjacent": true,
  "merge_strategy": "label_aware",
  "enable_regex_backstop": true,
  "trim_punctuation": true
}
```

含义：

- `label_aware`：按类别合并短间隔同类 span，改善姓名、地址、日期边界。
- `enable_regex_backstop`：对 URL、secret、账号做高置信规则回补。
- `trim_punctuation`：修剪结构化 span 尾部常见标点。

## 脱敏接口

保留原有脱敏能力。

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

## 验证脚本

本地验证：

```bash
scripts/verify_extract_api.sh
```

指定服务地址：

```bash
OPF_BASE_URL=http://localhost:8000 scripts/verify_extract_api.sh
```

通过 SSH 验证远程服务：

```bash
OPF_SSH_HOST=8.215.27.92 \
OPF_SSH_USER=root \
OPF_SSH_PORT=22 \
OPF_BASE_URL=http://localhost:8000 \
scripts/verify_remote_extract_api.sh
```

## CPU Benchmark

Benchmark 脚本会生成模拟敏感数据，并按块调用 `/extract`。这样可以测试
1KB、10KB、1MB、100MB 等输入规模，同时避免单次请求超过模型上下文或 HTTP
负载限制。

默认测试 1K、10K、1M、100M：

```bash
scripts/benchmark_extract_api.py --base-url http://localhost:8000
```

测试 hybrid 后处理：

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --profile hybrid \
  --sizes 1K,10K \
  --estimate-over-bytes 10240
```

快速冒烟测试：

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --sizes 1K,10K \
  --chunk-bytes 32768
```

当前纯 CPU 节点上，大文件全量实测耗时很长。可以先实测小样本，再对更大
文件做容量估算：

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --sizes 1K,10K,1M,100M \
  --chunk-bytes 32768 \
  --estimate-over-bytes 10240
```

输出字段说明：

- `wall_time_s`：客户端观测总耗时。
- `wall_time_h`：小时单位耗时，便于观察大文件估算值。
- `throughput_bytes_s`：按输入字节数估算的吞吐。
- `throughput_mb_s`：按输入字节数估算的吞吐。
- `requests`：分块后的请求次数。
- `spans`：提取到的 span 数量。
- `avg_server_latency_ms`：服务端平均推理耗时。
- `p95_server_latency_ms`：服务端 P95 推理耗时。
- `estimated`：为 `true` 时表示结果是基于最大实测样本的线性估算。

一次远程 CPU 测试结果如下，仅作为当前机器规格下的容量参考：

```text
CPU: 8 vCPU, Intel(R) Xeon(R) Gold 6462C
chunk_bytes: 32768

1K    actual    12.852s
10K   actual    126.462s
1MB   estimate  12949.709s  (~3.60h)
100MB estimate  1294970.88s (~359.71h / ~15 days)
```

结论：纯 CPU 模式适合 Demo、小批量验证和低频离线任务；如果要处理 MB/GB
级文件，应使用 GPU、ONNX/量化运行时，或建立异步分块队列和批处理流水线。

## 质量评估套件

质量评估脚本会用带 ground truth 的合成样本对比不同后处理模式：

```bash
scripts/evaluate_extract_quality.py --base-url http://localhost:8000
```

输出包含：

- exact precision / recall / F1
- overlap precision / recall / F1
- 尾部标点错误数
- 客户端和服务端平均延迟

可只跑某些模式：

```bash
scripts/evaluate_extract_quality.py \
  --base-url http://localhost:8000 \
  --profiles baseline,hybrid \
  --details
```

## 本地构建

```bash
docker build -t opf-privacy-filter .
docker run -d -p 8000:8000 opf-privacy-filter
```

## 注意事项

- `/extract` 会返回敏感原文，生产环境必须放在内网或增加鉴权。
- `OPF_OUTPUT_MODE` 必须保持为 `typed`，否则无法返回原始类别。
- 模型主要面向英语，中文、非拉丁文本和行业私有编号需要单独评估。
- 100MB 文件应采用分块处理，再在业务侧合并结果和全局 offset。

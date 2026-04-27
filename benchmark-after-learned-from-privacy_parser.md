# Benchmark After Lessons from `privacy-parser`

本文档用于下一轮 Benchmark 记录。目标是验证从
`chiefautism/privacy-parser` 学到的后处理策略，是否能在当前 HTTP 服务中
改善准确率、召回率和边界质量，并量化它们带来的性能成本。

## 待验证假设

### H1: label-aware merge 改善边界完整性

预期：

- 多词姓名、地址、日期被合并成更完整 span。
- span 数量下降，实体级输出更稳定。

风险：

- 相邻但独立的同类实体被误合并。

### H2: regex backstop 提升强格式类别召回

预期：

- `private_url`
- `secret`
- `account_number`

在短上下文、日志、配置片段中的召回提升。

风险：

- 样例 token、订单号、公共 URL 被误报。

### H3: 尾部标点修剪提升 exact-match

预期：

- 减少 URL、邮箱、secret、账号等类别的边界多吃标点问题。

风险：

- 某些 secret 的真实末尾可能包含标点。

## 对照组

```text
baseline:
  当前 /extract，纯 OPF detected_spans

merge:
  baseline + label-aware merge

regex:
  baseline + regex backstop

hybrid:
  baseline + label-aware merge + regex backstop + punctuation trim

viterbi-tuned:
  hybrid + Viterbi bias tuning
  仅在 API 可稳定配置时测试
```

## 数据集

### 合成短文本

- 联系方式：姓名、邮箱、电话。
- 支付信息：账号、路由号、日期。
- 密钥片段：`sk-`、`ghp_`、`Bearer`、高熵密码。
- URL：带 query、尾部标点、括号包裹。

### 合成长文档

- settlement agreement 风格合同。
- 客服工单。
- 应用日志。
- 配置文件片段。

### 大文件吞吐

- 1KB
- 10KB
- 1MB
- 100MB

100MB 可先采用估算模式；如果 CPU 耗时过长，不强制全量实跑。

## 指标

### 准确性

- exact precision
- exact recall
- exact F1
- overlap precision
- overlap recall
- overlap F1
- label recall
- boundary offset mean / p95

### 性能

- cold start time
- warm request latency p50 / p95
- docs/s
- bytes/s
- CPU utilization
- RSS memory

### 输出质量

- span count
- average span length
- tail punctuation error count
- overlap conflict count
- regex-added span count
- regex-overrode-model count

## 运行环境记录

```text
host:
cpu:
cpu_count:
memory:
docker_image:
opf_device:
opf_output_mode:
opf_checkpoint:
chunk_bytes:
commit:
```

## 结果记录模板

```text
mode       size   latency_p50   latency_p95   bytes/s   exact_f1   overlap_f1   notes
baseline   1K
merge      1K
regex      1K
hybrid     1K
baseline   10K
merge      10K
regex      10K
hybrid     10K
baseline   1MB
hybrid     1MB
baseline   100MB
hybrid     100MB
```

## 初步成功标准

- hybrid 的 overlap recall 高于 baseline。
- hybrid 的 exact F1 不低于 baseline。
- regex backstop 新增 span 的误报率可解释、可配置。
- 性能开销相对模型推理时间可忽略，目标低于 5%。
- 输出 schema 与现有 `/extract` 兼容。

## 当前验证记录

验证环境：

```text
host: 8.215.27.92
container: opf2
cpu: 8 vCPU, Intel(R) Xeon(R) Gold 6462C
opf_device: cpu
opf_output_mode: typed
commit: local working tree after 6a57070
```

质量评估命令：

```bash
scripts/evaluate_extract_quality.py \
  --base-url http://localhost:8000 \
  --profiles baseline,hybrid
```

结果：

```text
mode      exact_precision  exact_recall  exact_f1  overlap_f1  tail_punctuation_errors  avg_server_latency_ms
baseline  0.9231           0.9231        0.9231    1.0000      1                        1088.27
hybrid    1.0000           1.0000        1.0000    1.0000      0                        1091.99
```

解释：

- hybrid 修复了 baseline 的尾部标点边界问题。
- 在当前小型合成评估集上，hybrid exact F1 从 0.9231 提升到 1.0。
- 平均服务端延迟基本不变，后处理成本相对模型推理可忽略。

hybrid 性能冒烟命令：

```bash
scripts/benchmark_extract_api.py \
  --base-url http://localhost:8000 \
  --profile hybrid \
  --sizes 1K \
  --chunk-bytes 32768 \
  --no-warmup
```

结果：

```text
1K actual
wall_time_s: 9.038
throughput_bytes_s: 113.3
avg_server_latency_ms: 9017.62
```

结论：

- 后处理优化有效提升边界质量。
- 当前瓶颈仍是 CPU 模型推理，不是后处理逻辑。
- 下一步应在 GPU 或更优运行时上跑同一套 quality + throughput benchmark。

## 下一步工程任务

1. 在 L20 或同级 GPU 上运行同一套 benchmark。
2. 补充更大、更贴近业务的数据集。
3. 对 regex backstop 记录新增/覆盖 span 明细。
4. 增加异步分块队列和文件级 offset 汇总。

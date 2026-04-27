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

## 下一步工程任务

1. 给 `/extract` 增加可选后处理参数：
   - `merge_strategy`
   - `enable_regex_backstop`
   - `trim_punctuation`
2. 增加带 ground truth 的评估脚本。
3. 复用当前远程 CPU 环境跑 baseline。
4. 实现后处理后跑 merge/regex/hybrid 对照。
5. 把结果补充到本文档。


# Lessons from `chiefautism/privacy-parser`

调研对象：

- 仓库：https://github.com/chiefautism/privacy-parser
- 调研版本：`79e7511fde4aa694c0bdf6e03955337280c229a4`
- 调研时间：2026-04-27

## 概要结论

`privacy-parser` 的核心思路不是重新训练模型，而是把 OpenAI Privacy Filter
的检测能力包装成“结构化 PII 提取器”，并在模型输出后增加工程化后处理。

它的最有价值经验是：

```text
文本
  -> OPF 模型推理
  -> Viterbi 解码调参
  -> 同类相邻 span 合并
  -> regex backstop 回补高确定性类别
  -> 重叠消解
  -> 结构化 spans
```

这与当前项目的 `/extract` 路线一致，但 `privacy-parser` 在召回率和边界稳定性
上做了更多工程补强，尤其适合后续 Benchmark 对比。

## 原理拆解

### 1. 三种后端

`privacy-parser` 提供三类能力：

- `PIIParser`：纯正则，无模型权重，速度极快。
- `ModelPIIParser`：直接调用 OPF 模型，返回 spans，不做脱敏。
- `HybridPIIParser`：OPF 模型 + span merge + regex backstop。

README 中给出的指标是：

```text
PIIParser       none    微秒级      F1 1.000
ModelPIIParser 1.5B    约 500ms   F1 0.733
HybridPIIParser 1.5B   约 600ms   F1 0.929
```

这些数字来自仓库自带小样本测试，不应直接当作生产指标；但它说明作者认为
“模型 + 少量确定性规则”比纯模型更适合工程落地。

### 2. 模型包装层

`ModelPIIParser` 使用同一个 OPF 模型：

- `OPF(model=..., device=..., output_mode="typed", decode_mode="viterbi")`
- 调用 `opf.redact(text)`
- 从 `RedactionResult.detected_spans` 中取 `label/start/end/text`

这与当前项目新增的 `/extract` 接口本质一致。

### 3. Viterbi 调参

`HybridPIIParser` 默认设置两个 bias：

```python
{
    "transition_bias_end_to_start": -0.5,
    "transition_bias_inside_to_continue": 0.2,
}
```

意图是减少“刚结束一个 span 又立刻开始新 span”的碎片化情况，并略微鼓励
span 延续。这会提高连续实体的召回和边界完整性，但也可能带来更长的误报 span。

### 4. 同类 span 合并

`privacy-parser` 对同 label 且间隔很短的 span 做合并。

它不是简单合并重叠 span，而是按类别设置 gap：

- `private_person`、`private_address`、`private_date`：允许最多 3 字符间隔。
- `private_email`：不允许 gap。
- `private_phone`、`private_url`、`secret`：允许短连接符。
- 允许连接字符包括空白、`.`、`-`、`,`、`/`。

这个设计比当前项目的 `merge_adjacent=true` 更细，因为当前项目只合并
同 label 且 `next.start <= current.end` 的重叠/贴合 span。

### 5. Regex backstop

Hybrid 只对三个类别做规则回补：

- `private_url`
- `secret`
- `account_number`

它没有对 person/email/phone/date 做广泛规则增强，原因很务实：

- URL、secret、长账号有强形态特征，正则精度较高。
- person/address/date 的上下文依赖更强，正则容易制造噪声。
- phone/email 已可规则化，但 phone 与账号/日期冲突较多，需谨慎。

重叠处理策略：

- 如果 regex candidate 与同 label 模型 span 重叠，保留模型结果。
- 如果 URL 或 secret 有强前缀证据，允许 regex 覆盖模型错标。
- 如果 account_number 包含一个被模型错标为 phone 的 span，允许改为账号。
- 不重叠时，直接添加 regex candidate。

## 优点

### 召回率更稳

纯 OPF 模型可能漏掉短上下文中的 URL、secret、长数字账号。
Regex backstop 可以低成本回补这些强格式类别。

### 边界更适合工程消费

模型可能把多词姓名、地址、日期拆成多个相邻 span。
后处理合并后，调用方拿到的是更接近业务实体的完整片段。

### 保持模型能力，同时避免过度规则化

它没有试图用正则替代模型，而是只在高确定性类别上补强。
这个边界比较合理，能减少正则带来的误报。

### API 设计轻量

输出只有 `label/start/end/text`，非常适合作为提取器。
当前项目的 `/extract` 已采用类似结构。

## 缺点和风险

### README 指标可信度有限

仓库宣称 F1 到 0.929，但测试集很小，并且依赖外部
`privacy-filter/examples/data/sample_eval_five_examples.jsonl`。

问题：

- 样本量不足以代表真实日志、合同、邮件和混合语言。
- exact-match F1 对边界非常敏感，不能单独代表工程可用性。
- 未提供大文件吞吐、批处理吞吐、内存占用和冷启动耗时。

因此这些指标只能作为方向参考，不能直接用于 SLA。

### 正则 backstop 会改变精确率/召回率平衡

Regex 可以提高召回，但一定会引入误报风险。

例如：

- `sk-test-...` 可能是样例 token，不一定是真 secret。
- 长数字可能是订单号、票据号，不一定是银行账号。
- URL 可能是公开页面，不一定是隐私 URL。

需要通过业务标签策略决定是否接受这种“高召回优先”的行为。

### Viterbi tuning 可能拉长 span

鼓励 span 延续可以修复碎片化，但也可能把尾部标点或上下文一起吞进去。
我们在当前服务端测试中也观察到过类似现象，例如 secret 可能包含尾部句号。

### 攻击性叙事不适合生产 README

该仓库 README 使用了偏攻击视角的描述。当前项目应采用数据治理、防泄漏审计、
合规预检等防御性表述，避免“扫描泄露数据”等不必要的表达。

## 对当前项目的借鉴

当前项目已实现：

- `/extract`
- `/extract/batch`
- `labels`
- `include_text`
- `merge_adjacent`
- Demo 和 CPU Benchmark 脚本

建议吸收 `privacy-parser` 的以下经验。

### 1. 升级 span merge

把当前简单合并升级为按 label 配置 gap：

```text
private_person/private_address/private_date: 允许短空格、逗号、斜杠
private_email: 不允许 gap
private_phone/private_url/secret/account_number: 只允许短连接符
```

预期收益：

- 提高多词姓名、地址、日期的实体完整性。
- 减少输出中多个碎片 span。

风险：

- 过度合并相邻但独立的同类实体。
- 需要在 Benchmark 中同时统计 exact match 和 overlap match。

### 2. 增加高确定性 regex backstop

优先只做三类：

- `private_url`
- `secret`
- `account_number`

设计建议：

- 默认关闭或通过参数开启，例如 `enable_regex_backstop=true`。
- 与模型 span 重叠时，默认保留模型。
- 只有强证据 URL/secret/account 才允许覆盖错标。

预期收益：

- 提升 URL、secret、长账号召回。
- 改善短上下文文本中的漏检。

风险：

- 增加误报，需要按业务场景配置。

### 3. 增加尾部标点修剪

针对以下类别做保守后处理：

- `private_email`
- `private_url`
- `private_phone`
- `secret`
- `account_number`

可修剪字符：

```text
.,;:!?)]}"'
```

预期收益：

- 改善 span 边界。
- 提高 exact-match 指标。

风险：

- 某些 secret 末尾可能真实包含 `!` 或 `)`，因此 secret 的修剪应更谨慎。

### 4. 引入 dual metrics

下一轮 Benchmark 不应只看耗时，还要同时评估：

- exact precision/recall/F1：严格边界一致。
- overlap precision/recall/F1：同 label 且区间有交集。
- label recall：只看是否识别出目标类别。
- boundary error：预测边界与真实边界的偏移。

这样可以区分：

- 模型漏检。
- 标签错判。
- 只是边界略偏。

### 5. Benchmark 分层

建议下一轮 Benchmark 分四组：

- `baseline`：当前纯 OPF `/extract`。
- `merge`：只开启增强 span merge。
- `regex`：只开启 regex backstop。
- `hybrid`：merge + regex + 可选 Viterbi tuning。

每组统计：

- 吞吐：bytes/s、docs/s、latency p50/p95。
- 准确率：precision/recall/F1。
- 资源：CPU 占用、RSS 内存、冷启动耗时。
- 输出质量：span 数、平均 span 长度、尾部标点错误数。

## 建议的项目整合路线

### 第一阶段：安全后处理

优先实现低风险改动：

- label-aware merge。
- URL/email/account 的尾部标点修剪。
- Benchmark 脚本增加 exact/overlap 指标。

这些不改变模型解码，只影响输出整理，回滚成本低。

### 第二阶段：可配置 backstop

增加可选参数：

```json
{
  "enable_regex_backstop": true
}
```

仅对 URL、secret、account_number 生效。

### 第三阶段：解码参数实验

如果 OPF 服务端 API 可稳定调用 `set_viterbi_decoder()`，再加入配置化
Viterbi bias 实验。

默认不建议立即启用，因为它会改变模型底层解码行为，影响面比后处理更大。

## 当前项目与 privacy-parser 的差异

```text
当前项目:
  FastAPI 服务
  Docker 化部署
  /extract 和 /extract/batch HTTP API
  适合工程接入和远程服务化

privacy-parser:
  Python 包/CLI
  Hybrid 后处理更丰富
  更适合作为算法实验和后处理参考
```

因此最佳策略不是迁移到 `privacy-parser`，而是把它的后处理策略吸收到当前
HTTP 服务中，并用统一 Benchmark 验证收益。

## 下一步 Benchmark 准备

建议后续创建 `benchmark-after-learned-from-privacy_parser.md`，记录以下内容：

- 测试数据集：合成合同、客服工单、日志、密钥片段、长文件。
- 对照组：baseline、merge、regex、hybrid。
- 指标：latency、throughput、precision、recall、F1、边界误差。
- 环境：CPU 型号、核心数、内存、OPF 配置、chunk size。
- 结论：不同模式下的性能/准确率/召回率取舍。


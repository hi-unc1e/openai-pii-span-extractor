# Project Self Check

本文档回答项目交付后的三个关键问题，并给出生产落地建议。

## 1. 管理层结论：面向 CISO 的电梯演讲

当企业需要把客服工单、日志、邮件、合同和数据湖文本交给下游系统处理时，
最大风险不是“有没有脱敏工具”，而是“不知道敏感信息藏在哪里”。

本项目把 OpenAI Privacy Filter 从脱敏工具扩展为敏感信息发现服务：

```text
输入非结构化文本
  -> 自动识别姓名、邮箱、电话、地址、账号、URL、日期、secret
  -> 返回类别、原文片段、字符索引
  -> 支持审计、治理、脱敏、告警和数据出境前检查
```

对 CISO 来说，它的价值是：

- 在数据泄露前发现风险位置。
- 在大规模日志和文档中建立 PII 资产清单。
- 让脱敏、分类分级、DLP、合规审计从“规则堆砌”升级为上下文感知。
- 支持本地或内网部署，敏感文本不需要发给第三方 SaaS。

一句话总结：

> 这是一个可私有化部署的敏感信息发现引擎，把非结构化文本中的 PII
> 转成可检索、可审计、可治理的结构化安全信号。

## 2. 技术优势：相较于纯正则方案

纯正则适合邮箱、URL、固定格式 token，但很难处理真实业务文本中的上下文。
本方案采用“模型 + 工程后处理”的混合路线。

### 上下文理解

正则只看字符串形态，模型能结合上下文判断：

- `John Smith` 是人名，而不是普通标题词。
- `March 18, 2026` 是日期。
- 地址可能跨多个词和标点。
- 同一串数字在“account number”上下文中更像账号。

### 更好的类别覆盖

纯正则通常只能稳定覆盖：

- email
- URL
- phone
- 部分 secret
- 部分长数字账号

本方案覆盖 OPF 的 8 类标签：

- `account_number`
- `private_address`
- `private_email`
- `private_person`
- `private_phone`
- `private_url`
- `private_date`
- `secret`

### 更好的召回和边界质量

项目吸收 `privacy-parser` 的经验，增加了：

- label-aware span merge：减少姓名、地址、日期碎片化。
- regex backstop：回补 URL、secret、账号等强格式类别。
- punctuation trim：减少尾部标点被吞入 span。
- exact/overlap 双指标评估：区分漏检、错标和边界偏移。

### 可调的精确率/召回率取舍

正则方案通常是“命中或不命中”，很难按业务风险调节。

本方案可按场景选择：

- baseline：只用模型输出，误报相对更少。
- merge：改善边界完整性。
- regex：提升强格式类别召回。
- hybrid：生产建议模式，兼顾模型上下文和规则回补。

## 3. 成本与性能估算

### 已实测环境

远程 CPU 环境：

```text
CPU: 8 vCPU, Intel(R) Xeon(R) Gold 6462C
模式: CPU-only
chunk_bytes: 32768
```

实测：

```text
1K    actual    12.852s
10K   actual    126.462s
1MB   estimate  12949.709s  (~3.60h)
100MB estimate  1294970.88s (~359.71h / ~15 days)
```

解释：

- 该容器当前以纯 CPU 路径运行，吞吐很低。
- 小文本 Demo 可用，但 MB/GB 级文件不应采用同步 CPU 单实例处理。
- 100MB 应使用 GPU、批处理队列、分块并发和更高效运行时。

### 性能估算矩阵

以下矩阵用于容量规划，不是最终 SLA。最终数值必须以目标机器实测为准。

```text
配置                    适用场景                  10KB估算       1MB估算         100MB估算
4核8G CPU               功能验证/低频离线          4-8分钟        7-14小时        30-60天
8核16G CPU              小规模内网 Demo            2-3分钟        3-6小时         15-30天
16核32G CPU             离线小批量                 1-2分钟        1.5-3小时       7-15天
L20 级入门 GPU          生产试点/批量任务          秒级           分钟级          小时级
L20 + 队列 + 分块并发    推荐生产方案               秒级           分钟级          可控小时级
```

成本判断：

- 纯 CPU：部署便宜，但只适合 Demo、小文本、低频审计。
- 入门 GPU：单位吞吐成本更合理，适合生产试点。
- 批处理队列：处理 1MB/100MB 文件的必要工程形态。

## 4. 项目优越性论证

本项目的优越性来自四点：

- **上下文感知**：不是只靠字符串形态，能识别人名、地址、日期等弱格式 PII。
- **工程可控**：FastAPI + Docker + 本地模型，可内网部署。
- **混合增强**：吸收 `privacy-parser` 的 merge/backstop/trim 经验。
- **可衡量**：提供吞吐 Benchmark 和质量评估脚本，不靠主观演示判断效果。

## 5. 交付物自检

### 代码

- `/extract`：单文本结构化提取。
- `/extract/batch`：批量结构化提取。
- `/redact`：保留原脱敏能力。
- hybrid 后处理参数：
  - `merge_adjacent`
  - `merge_strategy`
  - `enable_regex_backstop`
  - `trim_punctuation`

### Benchmark 与测试套件

- `scripts/verify_extract_api.sh`
- `scripts/verify_remote_extract_api.sh`
- `scripts/demo_extract_api.py`
- `scripts/benchmark_extract_api.py`
- `scripts/evaluate_extract_quality.py`

### 演示说明

推荐演示文案：

```text
左侧是一段合同/客服工单/日志，包含姓名、邮箱、电话、地址、账号和 secret。
右侧是模型返回的结构化结果：类别、原文片段、起止索引。
同一服务既可以用于发现敏感信息，也可以继续用于脱敏。
```

可用于生成演示图的 prompt：

```text
Create a clean dark-themed product screenshot mockup for a privacy data discovery tool.
Left panel: a long settlement agreement text with highlighted fake PII spans including
name, email, phone, address, bank account, URL, date, and secret. Right panel: a structured
table titled "PII spans extracted" with columns label, text, start, end. Use professional
security product styling, no real personal data, all values clearly synthetic.
```

## 6. 生产建议

- 默认内网部署，不把 `/extract` 暴露到公网。
- 请求和响应日志默认不记录正文。
- 大文件使用异步队列和分块处理。
- 对不同业务线维护本地评估集。
- 上线前必须跑 `baseline` 与 `hybrid` 对照 Benchmark。


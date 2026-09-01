---
name: data-lens
description: "面向智能体的证据型数据分析 Skill。用于分析表格、文本、图片、PDF、音频、视频及混合资料，先识别决策问题、分析单位与证据边界，再选择统计、质性、时间、检索或多模态方法并生成可追溯结果。适合批量资料、重复经营导出、跨来源研究和用户尚不确定分析方法的场景；不用于单个简单公式计算或脱离数据的文章改写。"
---

# Data Lens

把资料变成能支持判断和行动的分析结果。用户的问题决定分析方法；文件格式只决定读取方式和证据能力。

## 共同流程

```text
用户原始问题 + 资料
→ 清点来源、版本、重复与可读性
→ 确认分析单位、时间、空间、分母和证据通道
→ 决定全量、分层抽样或小型试验
→ 选择少量满足资格的方法
→ 先做确定性解析与计算
→ 形成语义候选
→ 合同校验 → 证据校验 → 采用账本
→ 输出报告、明细、证据位置与运行清单
```

保留用户本轮原话作为 `decision_question`。不得先将问题改写成含“关联、方法、机制”等路由词的摘要，再用改写后的文本选路。

## 选择路线

| 资料与问题 | 首选路线 | 需要读取 |
|---|---|---|
| 先判断有什么、是否重复、能否分析 | `inventory_and_profile` | [references/routing.md](references/routing.md) |
| 普通或重复导出的表格 | `tabular_analysis` | [references/methods/repeated-operational-tables.md](references/methods/repeated-operational-tables.md) |
| 多篇文章、评论、访谈或案例 | `qualitative_corpus` | [references/methods/qualitative-corpus.md](references/methods/qualitative-corpus.md)；确认同一作者后可用 [references/methods/same-author-content.md](references/methods/same-author-content.md) |
| 图文、PDF、音频或视频 | `multimodal_evidence` | [references/multimodal-evidence.md](references/multimodal-evidence.md) |
| 多种资料家族及跨来源关系 | `mixed_corpus` | [references/methods/mixed-corpus.md](references/methods/mixed-corpus.md) |
| 大语料的候选召回 | `vector_retrieval` 支持模块 | [references/vector-retrieval.md](references/vector-retrieval.md) |
| R 更适合的统计、时间、空间或因果方法 | `r_method` 支持模块 | [references/optional-r.md](references/optional-r.md) |
| 现有方法无法保留问题与证据边界 | `novel_route` | [references/methods/novel-route.md](references/methods/novel-route.md) |

同一任务可以调用支持模块，但只保留一条主路线。不要为了展示能力而运行所有方法。

## 执行要求

1. 大批量或混合资料先运行 `python scripts/data_lens.py inventory ...`，再运行 `plan`。用户不需要亲自执行命令。
2. 文件数不等于分析单位数。文章、评论、订单、商品、平台日、图片区域和视频片段必须分别定义。
3. 默认不顺序截取前几项。使用全量、分层、时间分布、主题平衡、表现对照或家族覆盖等明确策略。已完整人工确认的单元应排除出再次语义处理。
4. 先运行确定性解析、去重、匹配、统计和质量检查；模型不得心算权威数字、补造缺失值或确认模糊匹配。
5. 模型输出只是候选。正式发现必须依次通过格式适配、严格合同校验和证据校验，再写入采用账本。请求成功不等于结果采用成功。
6. 跨文档综合只读取已验证证据卡，并设置数量或字符预算。检索命中只能帮助定位候选，不能冒充分母、全量覆盖或独立证据。
7. 事实、计算结果、算法候选、解释和建议分开表达。重要解释至少检查一个替代解释；证据不足时交付清楚的描述和补证计划。
8. 只有核心问题得到至少一条有效采用发现，且必答检查项满足，才可标记 `complete`。否则使用 `preliminary`、`partial` 或 `core_question_unanswered`。
9. 每次正式运行生成 `run_manifest.json`，记录实际输入哈希、方法版本、实现、确定性产物、证据位置、采用计数、警告和交付物。
10. 普通路线交付 Markdown 和数据附件；需要阅读导航时生成 HTML；重复经营表格以可筛选 Excel 为主。读者报告不展示内部路径、哈希、路由 ID 和流水线术语。

深度、证据和交付合同分别见：

- [references/deep-analysis-contract.md](references/deep-analysis-contract.md)
- [references/evidence-lanes.md](references/evidence-lanes.md)
- [references/quality-checks.md](references/quality-checks.md)
- [references/html-output-contract.md](references/html-output-contract.md)

## 可选执行能力

运行 `python scripts/data_lens.py capabilities` 查看本机能力。

- Python 标准库路径是默认基线。
- R 不自动安装。只有方法资格满足且 `Rscript` 可用时，才通过受控适配器运行注册的 R 方法；规则见 [references/optional-r.md](references/optional-r.md)。
- 向量索引默认本地、可删除重建且不是事实源。未安装嵌入模型时可使用确定性哈希向量做召回 smoke；规则见 [references/vector-retrieval.md](references/vector-retrieval.md)。
- 图片、PDF、音频和视频先建立可定位证据，再做语义分析；元数据、OCR、转录和实际语义审核是不同状态。
- 本地图片 OCR 使用 `python scripts/data_lens.py ocr <image> --output <result.json>`；默认有界比较 PSM 6 与 11，保留全部候选、置信度和像素坐标。算法推荐候选仍是未审核文本，规则见 [references/multimodal-evidence.md](references/multimodal-evidence.md)。
- 任何外部模型、远程向量服务或网络发送，都必须在发送前获得当前任务的明确授权；不得自动探测、修复重试或上传原始资料。

## 方法治理

方法定义放在 `methods/`，可执行实现放在 `scripts/` 或 `methods/implementations/`。新增方法必须声明适用问题、分析单位、资格、假设、人工卡点、输出、诊断、允许结论、禁止结论和版本；详细规则见 [references/method-governance.md](references/method-governance.md)。

新类型先用 3—5 个分层样本试验，记录有效输出、失败点、缺失证据和用户反馈。一次成功运行只能产生方法候选，不能自动改写全局方法。

## 不可突破的边界

- 不把高频当真理、相关当因果、异常当错误、聚类当真实类别或转载次数当独立证据。
- 不把缺失、未提供、不适用、未观察到和真实零值混为一类。
- 不用作者自述、行为符合利益或内容风格确认真实动机、人格或群体心理。
- 不静默删除反例、失败样本、未解析来源或未采用候选。
- 不把向量库、R、多模态或复杂算法当装饰；只有它们能回答当前问题且通过资格门时才启用。
- 不建设浏览器工作台、后台服务、项目数据库或 Provider 管理系统；Data Lens 由宿主智能体直接执行。

跨 Codex、Claude Code 和 WorkBuddy/CodeBuddy 的安装与兼容规则见 [references/agent-compatibility.md](references/agent-compatibility.md)。

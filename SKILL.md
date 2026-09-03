---
name: data-lens
description: "面向智能体的证据型深度分析 Skill。用于从表格、文本、图片、PDF、音频、视频及混合资料中识别关键问题、跨来源关系、结构性制约与竞争解释，再选择统计、质性、时间、检索或多模态方法形成可追溯结论。适合批量资料、重复经营导出、跨来源研究和用户尚不确定分析方法的场景；不用于单个简单公式计算或脱离资料的文章改写。"
---

# Data Lens

把资料变成能支持判断和行动的分析结果。用户的问题决定分析方法；文件格式只决定读取方式和证据能力。

## 共同流程

```text
用户原始问题 + 资料
→ 清点来源、版本、重复与可读性
→ 缺少共同对象或共同问题时，只分类并通过资料群选择门
→ 确认分析单位、时间、空间、分母和证据通道
→ 用户未指定角度时，生成候选角度并通过可回答性与证据门筛选
→ 决定全量、分层抽样或小型试验
→ 选择少量满足资格的方法
→ 先做确定性解析与计算
→ 从已观察现象形成问题地图，并按决策影响、解释覆盖和可回答性排序
→ 需要额外结构化推理时，选择可弃权的认知引擎
→ 形成语义候选
→ 角度采用只授权继续分析
→ 发现合同 → 证据 → 反例 → 竞争解释 → 稳健性 → 采用账本
→ 输出报告、明细、证据位置与运行清单
```

保留用户本轮原话作为 `decision_question`。不得先将问题改写成含“关联、方法、机制”等路由词的摘要，再用改写后的文本选路。

Data Lens 与宿主智能体的分工见 [references/host-skill-collaboration.md](references/host-skill-collaboration.md)。多轮承接语由宿主结合可见历史解释；Skill 保留原话并负责可复现的范围、证据和采用门，双方都不能绕过对方的职责。

用户不指定分析角度时，按 [references/angle-discovery.md](references/angle-discovery.md) 先生成最多 8 个候选、采用最多 4 个。不得因为问题开放就直接进入 `novel_route`，也不得用一串泛泛问题冒充分析；每个采用角度都必须有明确分析单位、覆盖计划、反例和失败条件。

输入目录没有已确认的共同对象或共同问题时，按 [references/corpus-scope-gate.md](references/corpus-scope-gate.md) 只做盘点、去重和资料群分类。不得把最大资料群称为目录主线；选中一个合格资料群后才可自动找角度。只有用户问题跨群且共同范围通过证据校验时，才能选择整个语料。

## 认知引擎

主路线决定分析什么对象、单位和证据；认知引擎只决定怎样扩展问题、竞争解释和区分测试。用户追问“真正的问题是什么、为何相互牵制、何时会改变”且已有可观察现象时，读取 [references/cognitive-engine-router.md](references/cognitive-engine-router.md)。普通查数、摘要、确定性分解或范围尚未确认时不调用。

当前实验性 `contradiction_engine` 用于检查共享约束、反馈回路、异质反应和阶段性主导关系，详见 [references/contradiction-engine.md](references/contradiction-engine.md)。它必须允许返回未发现结构性矛盾，不能把差异、相关或最大负项自动命名为核心制约。正式发现继续进入现有证据、反例、竞争解释和稳健性流程。

认知引擎不能只给普通分析换术语。先保留宿主最自然的解释，再尝试产生结构不同且对新证据给出不同预测的候选；找不到具体共同载体、区分预测或优先级切换条件时就弃权。结构上最关键的机制与当前最值得先做的动作分开判断，避免把“容易做、学习快”误写成问题本质。

把宿主原生分析当作必须保留的基线，而不是等待流程替换的草稿。调用认知引擎前，先记下宿主独立发现的高价值问题、异常、张力和普通解释 `E0`；引擎候选 `E1` 只有在解释覆盖、反例处理、区分预测或决策动作中至少一项具体胜过 `E0` 才进入最终竞争。最终报告采用证据支持下最强的组合，不能因为某个发现不是由引擎产生就删除，也不能因为 `E1` 更复杂就自动替换 `E0`。

认知引擎主要服务内部推理。读者报告默认使用现代、具体的决策语言，不强制引用思想来源，不展示晦涩术语；只有用户明确要求方法说明时才在附录解释来源。

## 选择路线

| 资料与问题 | 首选路线 | 需要读取 |
|---|---|---|
| 先判断有什么、是否重复、能否分析 | `inventory_and_profile` | [references/routing.md](references/routing.md) |
| 普通或重复导出的表格 | `tabular_analysis` | [references/methods/repeated-operational-tables.md](references/methods/repeated-operational-tables.md) |
| 多篇文章、评论、访谈或案例 | `qualitative_corpus` | [references/methods/qualitative-corpus.md](references/methods/qualitative-corpus.md)；确认同一作者后可用 [references/methods/same-author-content.md](references/methods/same-author-content.md) |
| ChatLab / 微信会话 JSON 导出 | `qualitative_corpus` | 先读 [references/methods/chatlab-corpus.md](references/methods/chatlab-corpus.md)，运行 `profile-chatlab` 后再做资料群与角度判断 |
| 图文、PDF、音频或视频 | `multimodal_evidence` | [references/multimodal-evidence.md](references/multimodal-evidence.md) |
| 多种资料家族及跨来源关系 | `mixed_corpus` | [references/methods/mixed-corpus.md](references/methods/mixed-corpus.md) |
| 大语料的候选召回 | `vector_retrieval` 支持模块 | [references/vector-retrieval.md](references/vector-retrieval.md) |
| R 更适合的统计、时间、空间或因果方法 | `r_method` 支持模块 | [references/optional-r.md](references/optional-r.md) |
| 现有方法无法保留问题与证据边界 | `novel_route` | [references/methods/novel-route.md](references/methods/novel-route.md) |

同一任务可以调用支持模块，但只保留一条主路线。不要为了展示能力而运行所有方法。

## 执行要求

1. 大批量或混合资料先运行 `python scripts/data_lens.py inventory ...`，再运行 `plan`。用户不需要亲自执行命令。
   多证据角色的开放目录先运行 `compile-scope`；没有 `analysis_ready` 的选择门时，`plan` 必须停在 `inventory_and_profile`，`prepare-mixed` 也不得启动。
2. 文件数不等于分析单位数。文章、评论、订单、商品、平台日、图片区域和视频片段必须分别定义。
   PDF 合集还要先识别目录、页形变化与内部项目/章节；两份 PDF 不等于两个案例。无法从文本层确认边界时，先运行 `profile-pdf`，再用有界 OCR/视觉复核确认内部单元。
3. 默认不顺序截取前几项。使用全量、分层、时间分布、主题平衡、表现对照或家族覆盖等明确策略。已完整人工确认的单元应排除出再次语义处理。
   混合目录中若检测到 `plugin.json`、`pyproject.toml`、`package.json` 或独立 `SKILL.md` 等嵌套项目标记，`prepare-mixed` 会生成 `nested_projects.json`；单独清点时运行 `profile-projects`。抽样同时覆盖顶层目录、业务家族、嵌套项目及其主要组件，不能用“顶层目录已抽到一项”代替项目内部技能、评测、样例和依赖的覆盖。
4. 先运行确定性解析、去重、匹配、统计和质量检查；模型不得心算权威数字、补造缺失值或确认模糊匹配。
   工作簿先按需运行 `workbook-integrity`；存在 WPS `DISPIMG` 或大量内嵌媒体时运行 `workbook-media`。解释规则见 [references/workbook-integrity.md](references/workbook-integrity.md)。
5. 模型输出只是候选。正式发现必须依次通过格式适配、严格合同校验和证据校验，再写入采用账本。请求成功不等于结果采用成功。
6. 跨文档综合只读取已验证证据卡，并设置数量或字符预算。检索命中只能帮助定位候选，不能冒充分母、全量覆盖或独立证据。
   自动角度必须通过 `compile-angles` 形成角度账本；采用角度不等于回答核心问题。候选发现按 [references/deep-finding-engine.md](references/deep-finding-engine.md) 运行 `compile-findings`，只有锚点发现能授权深度综合和核心问题完成状态。
7. 事实、计算结果、算法候选、解释和建议分开表达。重要解释至少检查一个替代解释；证据不足时交付清楚的描述和补证计划。
8. 只有核心问题得到至少一条 `anchor_eligible` 发现，且必答检查项满足，才可标记完整。否则使用 `preliminary`、`partial` 或 `core_question_unanswered`。
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
- PDF 使用 `python scripts/data_lens.py pdf <file.pdf> --output-dir <empty-directory>`；默认在全文均匀抽取至多 6 页，也可用 `--pages 1,3-5` 明确页码。每页保留原 PDF 哈希、页码、渲染图哈希、OCR 产物哈希和失败账本；不自动重试，不把抽样、渲染或 OCR 标成语义审核。
- PDF 合集先使用 `python scripts/data_lens.py profile-pdf <files...> --output <profile.json>` 建立页数、页形、文本层状态和内部单元风险画像。推荐页码采用首页/页形变化/全文均布组合，只是结构试样；不得把文件数或抽样页数当作项目数。
- 视频使用 `python scripts/data_lens.py video <file> --output-dir <empty-directory>`；默认在全时段均匀抽取至多 6 帧，也可用 `--timestamps 0.5,10,42.25` 指定秒数。每帧保留原媒体哈希、毫秒时间戳、帧哈希和失败账本。
- 本地转录使用 `python scripts/data_lens.py transcribe <file> --output-dir <empty-directory> --model-checkpoint <local.pt>`。只接受已存在的本地 Whisper 检查点路径；默认最长 20 分钟，超长媒体必须同时指定 `--start-ms` 与 `--end-ms`。不得下载模型、自动换模型或把转录标成说话人/语义审核完成。
- 任何外部模型、远程向量服务或网络发送，都必须在发送前获得当前任务的明确授权；不得自动探测、修复重试或上传原始资料。

## 方法治理

方法定义放在 `methods/`，可执行实现放在 `scripts/` 或 `methods/implementations/`。新增方法必须声明适用问题、分析单位、资格、假设、人工卡点、输出、诊断、允许结论、禁止结论和版本；详细规则见 [references/method-governance.md](references/method-governance.md)。

新类型先用 3—5 个分层样本试验，记录有效输出、失败点、缺失证据和用户反馈。一次成功运行只能产生方法候选，不能自动改写全局方法。

认知引擎或深度分析规则发生实质变化时，按 [evals/README.md](evals/README.md) 做同源成对盲测：裸宿主与 Skill 组使用相同基础任务，保留失分案例，并区分 fixture 行为检查与真实分析增量。不能用合同通过、字段齐全或报告更长证明分析更深。

## 不可突破的边界

- 不把高频当真理、相关当因果、异常当错误、聚类当真实类别或转载次数当独立证据。
- 不把缺失、未提供、不适用、未观察到和真实零值混为一类。
- 不用作者自述、行为符合利益或内容风格确认真实动机、人格或群体心理。
- 不静默删除反例、失败样本、未解析来源或未采用候选。
- 不把向量库、R、多模态或复杂算法当装饰；只有它们能回答当前问题且通过资格门时才启用。
- 不建设浏览器工作台、后台服务、项目数据库或 Provider 管理系统；Data Lens 由宿主智能体直接执行。

跨 Codex、Claude Code 和 WorkBuddy/CodeBuddy 的安装与兼容规则见 [references/agent-compatibility.md](references/agent-compatibility.md)。

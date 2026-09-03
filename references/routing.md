# 分析路线选择

根据用户要解决的决策问题选路线，不要根据文件扩展名选路线。

路由输入使用用户原话。不得在路由前改写目标并加入“方法、分析、关联”等关键词；关于 Skill 怎么工作的元讨论也不等于用户要把资料当作方法论语料。宽泛的“先看看能分析出什么”若包含多个证据角色且无法确认共同作者、账号、业务对象或决策问题，先进入 `inventory_and_profile` 并编译资料群选择门；不得直接进入 `mixed_corpus` 或 `novel_route` 综合。

## 已知路线

| 路线 ID | 适用的主要问题 | 主要分析单位 | 常见辅助证据 |
|---|---|---|---|
| `same_author_content` | 作者如何选题、吸引读者、组织结构、写作和排版？ | 文章 | 封面或首屏图片 |
| `account_content_performance` | 账号哪些内容表现更好或更差，下一步应验证哪些内容线索？ | 已确认指标状态的文章 | 正文、封面、发布日期 |
| `comment_voc` | 评论中出现了哪些需求、异议、问题和用户语言？ | 评论 | 帖子或文章上下文 |
| `xiaohongshu_account` | 账号的定位、封面、标题、钩子、正文和互动模式是什么？ | 笔记 | 评论和可见互动数据 |
| `method_corpus` | 一批资料中有哪些可复用方法、条件、步骤、冲突和空白？ | 原子方法主张 | 原文摘录和证据等级 |
| `mixed_corpus` | 资料包含哪些家族、各自能学到什么、哪些跨家族关系有证据？ | 每个家族自己的单位 | 所有证据通道，家族合成前保持分离 |
| `multimodal_course` | 文字、幻灯片、截图、音视频共同教了什么，如何组织？ | 课程或章节 | 画面、转录、练习 |
| `repeated_operational_tables` | 连续经营导出表发生了什么变化，哪个平台或实体贡献最大，接下来查什么？ | 业务日期 × 平台 | 店铺、商品、推广、库存、退款和履约 |
| `inventory_and_profile` | 先清点资料、字段、重复、缺失与可读性 | 来源容器或已声明数据单位 | 来源元数据、哈希、解析状态 |
| `tabular_analysis` | 通用 CSV/TSV/工作簿画像、分组描述、异常或变化候选 | 表格行或已声明业务单位 | 表格单元格、行定位、指标定义 |
| `qualitative_corpus` | 多篇文本、评论、访谈或案例的主题、差异、条件和反例 | 文档、案例、评论或原子主张 | 经语义审阅的文本范围 |
| `multimodal_evidence` | 图片、PDF、音频或视频中的可定位观察 | 图片区域、PDF 页、音视频片段 | 视觉、页面、转录或时间码证据 |
| `novel_route` | 现有路线无法保留用户目标和证据边界 | 试验后确定 | 实际存在的证据通道 |

已验证或带明确实验状态的方法覆盖 `inventory_and_profile`、`tabular_analysis`、`qualitative_corpus`、`same_author_content`、`account_content_performance`、`method_corpus`、`mixed_corpus`、`repeated_operational_tables`、`multimodal_evidence` 和 `novel_route`。向量召回和 R 是支持模块，不能独立升级结论强度。其他路线优先调用已安装的专门 Skill并记录为支持模块；没有可用专门方法时按新类型试验，不要假装已经验证。

## 条件式情境与机制透镜

原因、时间、参与者、空间和规则不是五条新路线。主路线确定分析对象；只有用户问题与实际证据同时涉及这些情境时，才读取 [reasoning-and-context.md](reasoning-and-context.md) 作为内部推理护栏。

- 用户问“为什么”时，先确认要解释的现象，再比较候选机制；
- 用户问“怎么演变”时，先判断证据只支持时间点、变化、局部趋势，还是确有阶段或周期；
- 用户问“人为什么这样做”时，把陈述、行为、结果、角色、约束和动机证据分开；
- 用户问“在哪里发生、平台有何不同”时，先声明地理、平台生态、组织、网络、信息可达或渠道等空间类型；
- 用户问“规则如何影响”时，先核对规则文本、适用对象、执行方式和前后行为，不预设规则制定者目的。

这些透镜只回答当前决策问题，不自动生成五个可见章节，也不写入现有分析计划的数据契约。

## 认知引擎路由

主路线和资料范围确认后，如果多个现象可能由同一结构解释、候选机制产生互斥预测、局部改善可能损害整体结果，或驱动因素随阶段转换，再读取 [cognitive-engine-router.md](cognitive-engine-router.md)。认知引擎是支持控制层，不得成为新的 `primary_route`，也不得绕过资料群、角度和发现采用流程。

结构性矛盾分析只在存在可检查的共享约束、反馈、异质反应或阶段切换信号时启用。普通差异、意见冲突、单点故障和可直接闭合的确定性问题不适用；检查后可以正常弃权。

## 默认分析深度

| 路线 | 默认深度 | 理由 |
|---|---|---|
| `account_content_performance` + 后台指标 | `deep` | 需要指标定义、正文匹配、反例和明确边界 |
| `same_author_content` | `standard` | 通常需要文章间比较，但不一定需要完整表现层 |
| `method_corpus` | `standard` | 需要条件、冲突和证据强度；大规模全量或重要决策使用 `deep` |
| `mixed_corpus` | `deep` | 家族、证据边界、版本关系、无关项和跨家族关系都要保留 |
| `repeated_operational_tables` | `deep` | 需要时间对齐、平台拆分、质量门、分解、实体变动和异常边界 |
| `novel_route` 试验 | `brief` | 先验证临时方法是否有用，成功后再升级 |

用户可以要求更深分析。不得用较低深度删除已经形成的有效内容。

## 路线置信度

- `high`：一条路线直接回答问题，所需证据也存在；
- `medium`：主路线明确，但需要支持模块或存在重要证据缺口；
- `low`：两条路线会得到本质不同结果，或没有路线能保留问题。

`high` 直接执行；`medium` 带边界执行；`low` 时若用户在线，只问一个真正会改变分析对象的问题，否则先运行小型 `novel_route` 试验。

## 内部分析计划

正式运行前创建精简 JSON 计划：

```json
{
  "plan_version": "1.0",
  "user_goal": "...",
  "primary_route": "account_content_performance",
  "route_confidence": "high",
  "supporting_modules": ["same_author_content"],
  "comparison_unit": "article",
  "input_roles": [],
  "deterministic_steps": [],
  "model_judgments": [],
  "evidence_boundaries": [],
  "report_depth": "deep",
  "required_outputs": ["deep_analysis.json", "report.html", "report.md", "run_manifest.json"]
}
```

这是内部控制产物，不得复制到读者报告。第一版由 `scripts/plan_analysis.py` 生成；模型读完完整需求后可以修订，但必须保留已识别维度、缺失证据和改路线理由。路线回答决策问题，支持维度不需要各自扩写成完整章节。

# 深度分析产物合同

`deep_analysis.json` 是普通路线的权威分析产物。读者 HTML 完整保留决策分析，但隐藏机器控制字段；审计 Markdown 同时保留分析和控制字段。两者都不能删减发现、比较、动作、证据边界或其他重要结论。

新运行使用合同 `2.3`，渲染器继续兼容旧版 `2.0`—`2.2`。

## 深度等级

- `brief`：执行摘要、完整发现、建议、限制和证据索引；
- `standard`：在 brief 基础上增加比较和路线专属章节；
- `deep`：在 standard 基础上增加反例、边界、完整路线模块、未回答问题和可验证的来源位置。

文章资料加后台指标的 `account_content_performance` 默认使用 `deep`。

合同 2.2 对 `standard` 进行机械深度检查：

- `same_author_content`：至少 5 条发现、2 组比较、3 个路线章节、3 条建议和 8 条有限证据；
- `method_corpus`：至少 5 条发现、2 组比较、3 个路线章节、2 条建议和 8 条证据；
- `mixed_corpus`：至少 5 条发现、2 组比较、4 个路线章节、4 条建议和 10 条证据；
- `novel_route` 的 standard：至少 3 条发现、1 组比较、2 个路线章节、2 条建议和 5 条证据。

真正的小型试验应使用 `brief`，不能为了通过 standard 而凑内容。

## 顶层必填字段

```json
{
  "contract_version": "2.3",
  "completion_status": "preliminary",
  "report_depth": "deep",
  "route": "account_content_performance",
  "title": "...",
  "subtitle": "...",
  "run_gate": {"validation_path": ".../run_gate_validation.json", "sha256": "..."},
  "presentation": {},
  "analysis_intent": {},
  "analysis_units": {},
  "scope": {},
  "sampling": {},
  "evidence_coverage": [],
  "analysis_checklist": [],
  "metric_definitions": [],
  "executive_summary": [],
  "evidence": [],
  "findings": [],
  "comparisons": [],
  "analysis_sections": [],
  "recommendations": [],
  "experiments": [],
  "limitations": [],
  "unanswered_questions": [],
  "method": {}
}
```

## 目的、抽样和证据覆盖

`analysis_intent` 保存用户决策问题、主要问题、请求维度、主动排除维度、所需证据、现有证据和未解决选择，防止所有宽泛资料默认套同一分析。

`sampling` 保存抽样策略、请求和选中数量、合格分母、纳入规则、排除和重要偏差。方便样本不能称为代表性样本。

`analysis_units` 分开来源容器和观察单位，记录：

- `source_container_unit`；
- 已确认或临时的 `analysis_unit`；
- `unit_status`；
- 来源、合格、选中、观察、缺失数量；
- `unselected_count`、`unreadable_count`、`not_applicable_count`；
- 去重、版本和分组规则。

PDF 是来源容器，其中 66 个项目可能是 66 个分析单位；30 张截图可能合并成 26 个岗位单位。除非文件本身就是声明的分析单位，否则不得用文件数作分母。

`evidence_coverage` 为每个必要或已使用证据通道保存一条记录，包含 `lane`、`status`、`items`、`processing_states`、`proves` 和 `cannot_prove`。

状态是 `available`、`partial`、`uninspected`、`missing` 或 `not_required`。处理状态区分 `source_only`、`parsed`、`pixel_readable`、`ocr_complete`、`semantically_reviewed`、`matched`。像素可读不是语义审核；只有实际图片、页面或画面经过语义审核并有有限位置时，视觉证据才算 available。

## 稳定深度检查表

`analysis_checklist` 让不同对话的分析深度可重复。每项包含：

- `id`；
- 与决策有关的 `question`；
- `status`：`answered`、`evidence_missing` 或 `not_applicable`；
- `evidence_ids`；
- `finding_ids`；
- 说明。

`answered` 必须有可追溯证据和至少一条关联发现。缺少证据可以成为答案，但不能静默省略必答问题。

检查表不是读者可见的流程标题。有效答案渲染为发现，缺失项放进边界或未回答问题。各方法文件定义必答 ID；`novel_route` 至少覆盖决策问题、单位定义、证据边界、模式、反例和下一步。

`mixed_corpus` 必须覆盖家族定义、通道边界、家族内模式与差异、组件/版本关系、有证据的跨家族关系、无关项、覆盖/稳定状态和下一步。来源图和三类语义台账是中间证据产物，不是可选备注。

## 指标定义和名称保护

每条计算发现关联一个或多个 `metric_ids`。每个 `metric_definitions` 项记录：

- `id`、读者可见 `label`；
- `metric_type`：`exact`、`proxy` 或 `descriptive_count`；
- 单位、分子、分母；
- 合格规则、缺失规则、排除；
- 来源通道、算法版本；
- 有效条件和解释边界。

指标名称必须符合数据实际支持的含义。账号日阅读不等于文章阅读；次日上涨不等于策略胜率；截图数不等于岗位数。

只有指标明确入场、出场和成本条件时才能使用“胜率”或“收益率”；“转化率”需要明确分子和分母总体。条件不足时使用有边界的代理指标名称。

## 读者呈现

`presentation` 把读者语言和内部字段分开，包含：

- `kicker` 和三个描述真实资料范围的简短 `header_metrics`；
- 普通中文 `section_labels`；
- `toc_groups`，每组包含大白话组名和锚点/标签；
- 面向读者的 `footer_note`。
- 可选 `completion_note`，用一句话准确说明本轮完成了哪些声明范围；不得把样本完成写成作者全部历史或所有证据通道完成。

可见导航不得暴露路线 ID、深度、合同版本、原始证据 ID、哈希、本地路径、方法文件、限制清单、未回答问题清单和流水线记录。这些保留在分析与审计产物中。

## 发现不变量

每条发现必须包含：

- `fact`：观察结果或有来源支持的陈述；
- `evidence_ids`：至少一条证据引用；
- `explanation`：解释或机制线索；
- `counterexamples`：相反、较弱或限定观察；没有观察到时显式写明，不能省略；
- `boundaries`：证据不能证明什么；
- `recommendation_ids`：零条或多条关联动作；
- `classification`：`fact`、`calculation`、`inference` 或 `hypothesis`；
- `confidence`：`high`、`medium` 或 `low`。

建议包含动作、理由、关联发现 ID、验证指标、时间盒、风险、备用方案和 `priority`（`now`、`next`、`later`）。比较保留两边内容、解释、反例、边界和证据。

所有复数字段必须是 JSON 数组，即使只有一个值也不能写字符串，否则渲染器可能按字符遍历。

## 实验不变量

重要建议应转成实验，而不是泛泛建议。每个 `experiments` 项包含：

- `id`、`title` 和 `linked_finding_ids`；
- `question` 和可证伪 `hypothesis`；
- `comparison_design`、单一 `changed_variable` 和 `baseline`；
- `primary_metric` 和一个或多个 `guardrail_metrics`；
- `measurement_window` 和 `minimum_sample`；
- 预先声明的 `decision_rule`；
- `required_data`、已知 `confounders` 和 `stop_condition`。

最小样本是执行下限，不代表自动获得统计效力。发布频率不足以支持可信比较时，明确说明限制，不能伪造精度。

## 证据定位

合同 2.3 的每条证据包含 `source_path`、`lane`、`review_status`、`source_family`、locator 和 `trace`。`trace` 包含 `origin_path`、`origin_sha256`、`directness`，使用提取物时还包含 `artifact_sha256`。

`review_status` 记录最强的已完成操作，如 `parsed`、`matched`、`ocr_complete` 或 `semantically_reviewed`。文件可读不能冒充语义审核。

- `text_span`：确定性文本 `artifact_path`、起止行和必须出现在范围内的引用；
- `table_extract`：确定性表格产物、JSON 指针和该位置必须存在的引用/值；
- `image`：原始图片路径、描述和可选区域；
- `pdf_pages`：原始 PDF 路径和一个或多个已审核页码；
- `video_frames`：原始视频路径和一个或多个已审核时间点。

图片 locator 必须指向真实本地图片并包含描述。可选 `region` 为 `[x, y, width, height]`，图片尺寸可读时必须位于图片内部。

`scripts/validate_deep_analysis.py` 会机械检查来源文件、哈希、位置和引用值，并重新核对 `run_gate_validation.json` 记录的每个输入文件哈希。语义台账和旧报告不得作为新分析的主证据。`completion_status` 必须匹配经过哈希绑定的有效运行门；验证后输入发生变化时，旧门不能授权渲染。

## 运行追踪

分析前使用 `scripts/materialize_run_context.py` 实际读取并哈希所选方法文件和确定性产物。渲染器拒绝陈旧或手改的运行上下文。最终清单来自这些哈希、证据位置、分析产物和渲染结果，不能复制自由填写的声明清单。

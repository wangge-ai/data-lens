# 混合资料分析方法

当一个资料集合包含多个真实分析对象或生产角色时使用，例如文章、提示词、Skill、项目方案、截图、经营表、评论、课程和产出。目标是按各家族自己的逻辑分析，再检查真正有证据的跨家族关系。

## 主要问题和分析单位

顶层单位是 `family_specific`。每个家族在计算和合成前声明自己的比较单位。来源文件在语义审核前只是容器，不能默认等于一个分析单位。

多种扩展名不等于混合资料。同一文章的 Markdown 和 HTML 副本可能仍是一个文章家族。只有决策问题跨越多个家族、证据角色或生产阶段，而且一套字段会造成扭曲时才使用 `mixed_corpus`。

## 必须按顺序执行

1. 先按 [../corpus-scope-gate.md](../corpus-scope-gate.md) 编译资料群选择门。只有用户问题确实跨家族、共同对象与问题有已验证证据且用户授权整个语料时，才运行 `scripts/prepare_mixed_run.py --scope-gate ...` 原子化创建工作区；否则选择单一资料群并转入该群自己的路线。
2. 用 `scripts/build_source_graph.py` 创建 `source_graph.json`。自动生成的边只是技术候选，不是语义结论。
3. 使用 `family_stratified` 抽样。扩展大体量家族前，先覆盖用户提供的每个顶层目录和每个临时业务角色。目录和业务家族是两套不同分层。`prepare-mixed` 会生成 `nested_projects.json`；若只运行了清点，则用 `python scripts/data_lens.py profile-projects inventory.json --output nested-projects.json` 补齐。出现 `.codebuddy-plugin/plugin.json`、`.codex-plugin/plugin.json`、`pyproject.toml`、`package.json` 或项目外的独立 `SKILL.md` 时，抽样还必须覆盖嵌套项目及其主要组件，`skills/`、`modules/`、`packages/`、`plugins/` 下的二级目录分别登记。
4. 用 `scripts/plan_batches.py` 创建 `run_state.json`，不得把整个资料库放进一个模型上下文。
5. 运行 `extract_source_evidence.py`；解析工作簿并完成 `table_reviews.jsonl`；同步保存视觉审核决定；用 `prepare_semantic_review_packets.py` 组装批次。
6. 语义审核时写入 `evidence_units.jsonl`。每条只保存一个原子事实，并绑定原始文本、表格行、图片、PDF 页或视频时间。解释另存，并说明该证据不能证明什么。
7. 试验后用来源级审核决定拆分、合并或重命名家族。家族变化后，未选来源重新分类前，合格总体未知，不能把选中样本称为全量。每个确认家族写一条 `family_analyses.jsonl`，声明自己的方法路线和比较单位。
8. 如果问题要跨格式追踪同一项目、商品、课程、账号或岗位，先建立可选实体表再连关系。`relations.jsonl` 尽量使用实体、来源、素材或文档级端点；只有方法级关系才使用家族级端点。确认关系必须有明确引用、输入输出交接、共同业务 ID 或有限时间/版本记录。
9. 运行 `scripts/validate_mixed_workspace.py` 和 `scripts/validate_run_gates.py`。深度分析仍有不稳定家族时必须标为 `preliminary`，不能只改显示文字而保留最终状态。
10. 报告来自家族发现和已确认关系，候选关系必须标边界。本地路径、ID、状态和字段名只保留在审计产物。

## 家族规则

- 家族按相同分析对象或生产角色划分，不按关键词划分；
- 方法、提示词、Skill、模板、产出、表现记录、版本、同级副本和无关项是不同关系；
- 项目里的入口、代码、样例、测试、报告/输出、依赖和发布归档是不同实现层。脚本或样例存在只能支持实现成熟度画像，不能证明采用或效果；压缩包和解压目录需先按逐文件哈希判断是否只是同一版本的两个容器；
- 一项来源只有在每个归属都有明确证据时，才能支持多个家族；
- `unrelated`、`unknown`、`candidate` 都是有效结果，不能强行塞进主线；
- 家族结论引用证据单位，并说明覆盖、差异、冲突和边界。

## 抽样和规模

- 小型去重家族可以全量分析；
- 其他家族先做覆盖所有家族的试验，再分批扩展；
- 新批次仍增加方法、条件、冲突、版本角色或证据边界时继续；
- 只有已知全量完成，或必要证据通道都覆盖且两个比较键相同的批次不再新增信息时才停止。不同证据通道不能互相代替。状态记录为 `coverage_and_saturation`，不能宣称普遍理论饱和；
- 只有来源指纹、路线、家族、Skill 版本和方法版本未变化时，才能复用批次；
- 未处理和被排除来源继续显示在覆盖统计中，不能算成已分析。

## 必答检查项 ID

- `family_definition`
- `lane_boundaries`
- `family_patterns`
- `family_differences`
- `version_and_component_relations`
- `cross_family_relations`
- `unrelated_items`
- `coverage_and_saturation`
- `next_action`

## 跨家族证据门

确认关系至少需要一条可追溯证据。文件名相似、位于同一文件夹、主题重合和模型直觉都只能形成候选。涉及业务效果时，还必须是同一对象、同一版本和同一测量窗口，否则生产证据和表现证据保持分离。

共同出现、路径接近、日期相邻或主题相似不能证明社会关系、生产交接、影响方向或因果关系。不同家族可以保留不同解释尺度和方法，不要为了统一叙事把它们合成为一个作者世界观、行业规律或单一底层逻辑。

## 交付重点

先讲资料实际包含什么、哪些家族成熟或未完成、各家族可复用方法、真实跨家族交接、断裂环节和最小验证动作。文件清单放在覆盖或审计附录，不放开头。

# 混合资料中间产物合同

本合同保证从文件清点到最终报告之间的语义分析可审计。所有文件使用 UTF-8；JSONL 表示每行一个 JSON 对象。

## `source_graph.json`

用 `scripts/build_source_graph.py` 创建。节点保存来源身份和可审核的素材元数据。自动关系可以确认精确副本或格式副本；文件名版本、连续页和截图会话仍是候选。语义生产关系必须审核后添加。

## `run_state.json`

用 `scripts/plan_batches.py` 创建。它是选中来源、批次、家族覆盖、排除、恢复状态和阶段完成情况的执行权威。

批次状态只能是 `pending`、`completed`、`failed`、`excluded` 或 `reused`。失败批次记录 `failure_reason`。被选中却没有证据的来源，在语义阶段完成前必须进入 `excluded_sources` 并说明理由。

不得直接修改语义完成状态或排除项。每个选中来源写一条审核决定，再运行 `scripts/compile_source_dispositions.py`。它根据有证据的 `analyzed`、有理由的 `excluded` 或未解决的 `pending`，同步来源台账、批次、家族、排除和语义阶段。

## `source_dispositions.jsonl`

版本 0.7 的混合运行要求每个选中来源都有一条记录：

```json
{"source_container_id":"SRC-...","disposition":"analyzed","reason":"","reviewer":"model","evidence_unit_ids":["EU-..."]}
```

`analyzed` 必须有已编译证据；`excluded` 必须有理由；`pending` 保持可见并阻塞完成。该台账是 `run_state.json` 的审计来源，本身不是内容证据。

## `evidence_units.jsonl`

每条记录示例：

```json
{
  "evidence_unit_id": "EU-001",
  "source_container_id": "SRC-...",
  "family_id": "FAM-...",
  "lane": "content_text",
  "unit_type": "atomic_method_claim",
  "review_status": "parsed",
  "locator": {
    "type": "text_span",
    "artifact_path": ".../content_extracts/SRC-....txt",
    "start_line": 10,
    "end_line": 16,
    "quote": "先核验产品事实"
  },
  "trace": {
    "origin_path": ".../原始资料.md",
    "origin_sha256": "...",
    "artifact_sha256": "...",
    "directness": "direct"
  },
  "observed_facts": ["资料明确要求先核验产品事实"],
  "interpretations": ["事实核验是生图前的质量门"],
  "cannot_prove": ["不能证明该流程提高了转化"],
  "sensitivity": "internal",
  "allowed_use": "analysis_only"
}
```

`observed_facts`、`interpretations`、`cannot_prove` 永远是数组。版本 0.6 之后每条证据必须且只能包含一个观察事实。`trace.origin_path` 和哈希绑定原始文件；原格式无法按行定位时，`artifact_sha256` 绑定确定性提取物。

`evidence_units.jsonl`、家族合成、关系文件和旧报告不得作为直接证据。视觉证据必须达到 `semantically_reviewed`；仅像素可读不合格。

## `table_reviews.jsonl`

先用 `scripts/prepare_table_reviews.py` 创建队列，填写审核决定后再次运行。选中工作簿的每个非空工作表都有一条记录，包含 `sheet_id`、工作簿和工作表身份、`analysis_role`、`review_status`、`can_support_claims`、`source_kind`、指标范围和决定理由。

只要存在 `pending` 或 `unassigned`，任何报告都不能完成。合成用户声音、编码模板和被排除工作表不得支持用户或表现结论。

`scripts/prepare_semantic_review_packets.py` 会提供有限行预览，帮助审核者理解工作表。预览不能证明未展示行已审核，也不能替代指向已解析表格行的 `table_extract`。

## 家族细化

初始家族都是临时的。首轮试验后，用审核过的来源级决定运行 `scripts/compile_family_refinements.py`，完成拆分、合并、重命名并确认比较单位。根据新样本重建批次，不得直接修改旧批次。

家族标签变化后，未选资料重新分类前，合格总体为未知。设置 `eligible_count=null` 和 `eligibility_status=requires_full_corpus_reclassification`，防止把选中样本误称为全量。在 `family_registry.json` 中保留 `supersedes_labels`。

## 可选实体层

只有当问题需要跨文件或证据通道追踪同一项目、商品、课程、账号或岗位时，才运行 `scripts/compile_entity_decisions.py`。实体写入 `entity_registry.json`，来源归属写入 `source_entity_links.jsonl`。

确认归属需要证据和理由；文件名相似或位于同一文件夹只能标 `candidate`。每条归属标记为 `input`、`output`、`delivery`、`measured_result`、`context` 或 `unknown`。确认 `measured_result` 还要求对象版本、测量窗口和平台一致，否则继续保留候选。

这是有限身份层，不是通用知识图谱。用途是连接 `需求简报 → 表格 → 视觉素材 → 交付 → 实测结果` 等链条，而不是合并无关文件。

## 多模态补充计划

选中的 PDF 无文本或问题要求可见/口述内容时，运行 `scripts/plan_multimodal_fallbacks.py`。它为 PDF 渲染/OCR、图片审核、关键帧和转录创建有预算的待办队列，但不会把这些操作标记为已完成。

最终证据仍必须绑定原始 PDF 页、图片区域、视频时间或转录片段。

## `family_analyses.jsonl`

每个确认家族示例：

```json
{
  "family_id": "FAM-...",
  "label": "教程与Skill生产链",
  "method_route": "method_corpus",
  "comparison_unit": "production_step",
  "source_container_ids": ["SRC-..."],
  "evidence_unit_ids": ["EU-001"],
  "coverage": {"eligible": 12, "selected": 8, "processed": 8, "excluded": 0},
  "common_patterns": [],
  "differences": [],
  "version_relations": [],
  "reusable_methods": [],
  "conflicts": [],
  "boundaries": ["没有实际使用数据"],
  "status": "reviewed"
}
```

模式、差异、方法、冲突和边界都是数组。比较单位和证据成员未确认前，家族保持临时状态。

## `relations.jsonl`

每条语义关系示例：

```json
{
  "relation_id": "SR-001",
  "from_id": "FAM-...",
  "to_id": "FAM-...",
  "relation_type": "output",
  "status": "confirmed",
  "evidence_unit_ids": ["EU-001"],
  "rationale": "教程明确引用该Skill和模板作为输入",
  "boundary": "没有运行日志，不能确认具体版本"
}
```

状态只能为 `confirmed`、`candidate`、`rejected` 或 `unrelated`。确认关系必须有证据；候选关系不得进入计算或因果结论。

## 完成门

依次运行：

```powershell
python scripts/validate_mixed_workspace.py <workspace>
python scripts/validate_run_gates.py <workspace> --report-mode preliminary --depth deep --json-report <workspace>/run_gate_validation.json
```

以下情况最终验证失败：

- 已完成语义阶段仍有选中来源既无证据也无明确排除；
- 直接证据无法追溯到带哈希的原始文件；
- 家族阶段已完成但计划家族没有分析记录；
- 确认关系缺少证据；
- 本应为数组的字段写成字符串；
- 顶层目录未覆盖；
- 选中工作表尚未审核。

`final + deep` 还要求每个选中家族达到 `full_census_complete` 或 `stable_two_batches`。`preliminary` 保留未完成警告，不能假装完成。

版本 0.7 只有在家族合格总体已知时才接受 `full_census_complete`。`stable_two_batches` 还要求所有计划证据通道已覆盖，并且两个无新增信息批次使用相同且经过审核的 `comparison_key`。两个不同通道都没有新增，不代表已经稳定。

渲染或分享前，对报告所用文本运行 `scripts/scan_sensitive_content.py`。它只记录类别、位置、严重性和指纹，不保存命中内容。高风险项必须处理或明确保留；二进制文档和未转录媒体不在扫描范围内。

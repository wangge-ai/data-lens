# 资料群选择门

当输入目录缺少已确认的共同对象或共同问题时，先完成盘点、去重和资料群分类，不得直接进行全目录综合。文件数量、路径接近、主题相似和同处一个文件夹都不能证明某个资料群是目录主线。

## 运行顺序

```text
inventory.json
→ 宿主智能体提出资料群候选和每群可分析问题
→ compile-scope 核对来源、证据和选择授权
→ selection_required：只交付分类目录，等待选择
→ analysis_ready：只把选中资料群交给 plan 和后续方法
```

资料群按共同分析对象或生产角色划分，不按扩展名或关键词简单聚类。无法归组的来源保留在 `unassigned_source_ids`，不能静默删除。

候选输入遵守 `contracts/corpus-scope-candidates.schema.json`：

```text
python scripts/data_lens.py compile-scope --candidates corpus-scope-candidates.json --evidence-cards scope-evidence-cards.json --inventory inventory.json --output corpus-scope-gate.json
python scripts/data_lens.py validate-scope corpus-scope-gate.json
python scripts/data_lens.py plan --goal "用户原话" --inventory inventory.json --scope-gate corpus-scope-gate.json --output analysis-plan.json
```

`selection.scope_type=family` 只允许选中一个已通过合同和证据校验的资料群，并要求当前用户授权。未授权的自动选择不能解锁分析。

`selection.scope_type=whole_corpus` 只在以下条件全部满足时允许：

- 共同对象已确认；
- 共同问题已确认；
- 用户问题确实跨越这些资料群；
- 共同范围有已验证证据；
- 用户明确授权把整个语料作为分析范围。

没有选择时，`next_action` 只能是 `inventory_only`、`selection_required` 或 `review_required`。只有 `analysis_ready` 可以把 `deep_analysis_allowed` 设为 true。

`prepare-mixed` 必须读取已验证的全语料选择门；选中单一资料群时，应使用该资料群自己的路线，不得继续调用混合语料综合。

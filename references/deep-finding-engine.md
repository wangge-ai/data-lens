# 证据门控的深度发现

深度不由报告长度或条目数量定义。新版深度分析要求至少一条锚点发现通过范围、合同、证据、反例、竞争解释、稳健性和决策价值检查。

## 分析链

```text
已选资料群
→ 确定性基线和分析单位 × 维度地图
→ 已采用角度
→ 发现候选
→ 合同校验
→ 证据与资料群边界校验
→ 反例检查
→ 竞争解释检查
→ 稳健性检查
→ 发现采用账本
→ 锚点发现
→ 有界综合与报告
```

采用角度只表示值得继续分析，不能把核心问题标记为已回答。采用发现可以成为报告中的有边界描述；只有同时通过全部深度质量门的 `anchor_eligible` 发现，才能回答核心问题。

认知引擎只扩展发现候选。问题地图、结构性矛盾候选、阶段转换条件或实践预测都必须适配为本流程已有的 `pattern`、`relationship` 或 `mechanism_hypothesis`；竞争解释、反例、稳健性和决策增量分别进入已有字段。不得为认知引擎另建一套平行的发现采用链。

## 发现候选

候选输入遵守 `contracts/deep-finding-candidates.schema.json`。每条候选至少保存：

- `claim` 与 `claim_level`；
- 分析单位、基线、覆盖和独立来源组；
- 支持证据；
- 反例搜索状态和反证；
- 竞争解释及区分它们所需的测试或证据；
- 稳健性检查及结果；
- 证据边界、决策相关性和决策增量。

V1 支持 `fact`、`calculation`、`pattern`、`relationship` 和 `mechanism_hypothesis`。不接受 `causal`；因果结论必须另有合格实验或准实验方法合同。

深度证据卡遵守 `contracts/deep-evidence-cards.schema.json`。除来源和 locator 外，还必须声明来源 SHA-256、`unit_id`、`independence_group`、`family_id`、`lane` 和 `directness`。编译器重新检查本地来源存在性、哈希和 locator；同内容副本不得伪装成独立来源组。选中单一资料群后，群外证据不能进入该群的发现采用。

## 运行命令

```text
python scripts/data_lens.py compile-findings --candidates deep-finding-candidates.json --evidence-cards deep-evidence-cards.json --scope-gate corpus-scope-gate.json --output finding-adoption-ledger.json
python scripts/data_lens.py validate-findings finding-adoption-ledger.json
python scripts/data_lens.py deep-synthesis-context --ledger finding-adoption-ledger.json --output deep-synthesis-context.json --max-findings 6 --max-cards 36 --max-chars 36000
```

有界综合优先保留锚点发现，并完整携带支持、反证、替代解释、区分证据和稳健性证据的角色。预算不足时省略整条发现，不截断主张，也不得从原始语料补写新结论。

## 完成门

`deep_analysis.json` 合同 2.4 通过 `finding_adoption` 绑定发现账本路径、哈希和锚点 ID。`final` 至少要求：

- 账本有效且哈希未变化；
- 核心问题至少有一条锚点发现；
- 报告包含全部已采用发现；
- 路线必答检查项没有 `evidence_missing`；
- 运行门、来源哈希和证据位置继续有效。

证据只支持描述时，交付深度描述；竞争解释无法区分时，使用机制假设；不得通过增加篇幅把它包装成因果分析。

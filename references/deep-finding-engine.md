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
- 用于补齐计划实质层的 `analysis_coverage_evidence_refs`；它与高级结论自身的 `claim_design.result_evidence_refs` 分开。

普通层级支持 `fact`、`calculation`、`pattern`、`relationship` 和 `mechanism_hypothesis`。`relationship` 的可发布文字必须明确保持在相关、关联或共同变化层面；非 `causal_effect` 结论不得使用明确因果措辞或“令/让/使某结果更好”等施事结构，机制假设即使使用因果动词也必须同时标明“可能、假设或待检验”。非 `prediction` 结论不得用“未来时间＋确定数值或状态”断言未来，非 `decision_rule` 结论不得用规范词或“统一/固定＋动作”发布行动命令。这些检查覆盖标题、主结论、决策相关性、基线与决策变化等所有会进入报告的结论性字段，不能靠省略情态词或换字段绕过。`prediction`、`causal_effect` 和 `decision_rule` 只在同时满足以下条件时进入采用链：

- 已提供由 `compile-question` 生成且决策问题一致的深度分析计划；
- 对应 `predictive`、`causal` 或 `decision` 权限为 `allowed`；
- 候选携带 `claim_design`，明确目标、方法、关键假设、匹配声明层级的验证类型和结果证据；
- `validation_status` 为 `supported`，结果证据已验证并通过同一套反例、竞争解释和稳健性检查。

结果证据卡必须使用 `lane=analysis_result` 与 `directness=derived`，并声明与源 JSON 顶层字段一致的 `result_contract_version` 和成功状态；不能拿原始文章、表格行或模型解释冒充实验/估计输出。结果文件还要回显 `analysis_binding`，绑定唯一组件、层级、目标、验证类型和实际测量方法。异质性另外绑定分群、组值、最小样本量和因果/描述边界；机制另外绑定机制变量、实际改变变量、同一测量和两组冻结预测；预测另外绑定验证方式、预测期、截止点、指标、基线及全部竞争模型；因果另外绑定干预、比较条件、识别策略及设计证据；决策另外绑定动作、收益、成本、约束、阈值、基线、fallback 和撤回条件。任何一项与问题计划或 `claim_design` 不同都拒绝采用。

预测只接受样本外验证，因果效果只接受随机实验或已识别的观察性估计，决策规则只接受决策分析或策略评估。`run-deep-analysis` 可签发异质性、直接机制、滚动起点模型竞争和期望净效用策略结果；旧 `run-experiment` 继续签发原子评分及合格的单项预测/因果探针。`inconclusive` 是可核验结果，但不能写成 `supported` 或计入已执行覆盖。机械绑定阻止同一结果被跨层改名，但设计证据是否真的支持随机化、平行趋势或排除限制，仍需宿主复核其语义。

分析计划只说明“这个问题具备怎样分析的条件”，不等于实验已经支持结论。`ready` 与 `executed` 分开记录：只有已验证、可按内嵌规格重跑、`coverage_status=completed` 且绑定到当前问题全部关键参数的实际结果，才能覆盖对应实质层。机制假设也不会因为采用了回归、双重差分或机器学习方法名而自动成为因果效果。

深度证据卡遵守 `contracts/deep-evidence-cards.schema.json`。除来源和 locator 外，还必须声明来源 SHA-256、`unit_id`、`independence_group`、`family_id`、`lane` 和 `directness`。编译器重新检查本地来源存在性、哈希和 locator；同内容副本不得伪装成独立来源组。选中单一资料群后，群外证据不能进入该群的发现采用。

## 运行命令

```text
python scripts/data_lens.py compile-findings --candidates deep-finding-candidates.json --evidence-cards deep-evidence-cards.json --scope-gate corpus-scope-gate.json --analysis-plan deep-analysis-plan.json --output finding-adoption-ledger.json
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

证据只支持描述时，交付深度描述；竞争解释无法区分时，使用机制假设；预测没有时间外验证、因果没有识别与反驳、决策没有价值和成本时，分别停在较低层级，不得通过增加篇幅或方法名称包装成高级结论。

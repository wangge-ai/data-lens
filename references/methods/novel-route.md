# 新类型试验方法

当现有方法无法保留用户的决策问题或输入组合时使用。

## 先试验，不强套

1. 用一句话写清实际决策问题；
2. 提出临时比较单位；
3. 把现有输入分配到证据通道；
4. 选择一种主要通用方法：描述、结构、比较、质性编码、量化表现、流程拆解、视觉分析或时间分析；
5. 只分析 3—5 个代表样本或一个有限切片；
6. 交付临时发现、证据、限制和建议的全量方法。

保存临时分析维度、证据角色、抽样理由和比较单位。新路线可以借用通用方法，但不能借用不适合的正式路线结论或必填字段。

新类型不能默认套用某一作者的人性或社会观点、固定行业阶段、周期模型、信息差或博弈解释。只有用户问题与实际证据同时涉及原因、时间、参与者、空间或规则时，才使用 [../reasoning-and-context.md](../reasoning-and-context.md) 形成可反驳的候选解释；只有问题但缺少相应证据时，不启动机制归纳，把必要证据列入试验结果。

缺少证据但试验仍然有用时，显示限制并继续。只有缺失选择会改变分析对象或结论含义时才向用户提问。

## 案例记录

创建 `novel_case.json`：

```json
{
  "case_id": "novel-YYYYMMDD-NNN",
  "status": "experimental",
  "user_goal": "...",
  "requested_dimensions": [],
  "input_combination": [],
  "evidence_roles": [],
  "nearest_routes": [],
  "why_existing_routes_do_not_fit": [],
  "pilot_method": "...",
  "comparison_unit": "...",
  "sampling_reason": "...",
  "pilot_scope": "3 items",
  "what_worked": [],
  "what_failed": [],
  "missing_evidence": [],
  "user_accepted": null,
  "promotion_recommendation": "hold"
}
```

真实运行产生有用结果且用户接受方法之前，不得升级为永久方法。升级时增加一份聚焦的方法说明和一个回归样例。

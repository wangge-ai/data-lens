# Open Bandit forward blind test 001

本案例使用从未进入 Data Lens 开发、候选生成或历史评审的公开真实电商推荐日志，检验 Skill 是否能在裸宿主已经具备较强分析能力时产生可验证增量。

## 冻结材料

- 来源：ZOZO Research / `st-tech/zr-obp`
- 本地执行时将数据根目录记为 `<open-bandit-data-root>`；该目录不进入仓库
- Git commit：`8cbd5fa4558b7ad2ba4781546d6604e4cc3e07c4`
- 文件选择：`obd/README.md`、`obd/README_JN.md` 以及 `obd/{bts,random}/{all,men,women}/*.csv`
- 资料规模：六份各 10,000 次曝光的真实日志及对应商品上下文

Git commit 已经冻结内容，不再额外增加重复的文件哈希门禁。候选任务只能读取上述材料；本目录中的提示词、协议和未来候选输出不属于分析材料。

## 执行顺序

1. 裸 Codex 使用 `raw-codex-prompt.md`，不得读取 Data Lens、评分量表或其他候选。
2. Codex + Data Lens 使用 `data-lens-prompt.md`，只比裸组多调用当前 `$data-lens`。
3. WorkBuddy + Data Lens 使用 `workbuddy-prompt.md`；由用户在安装当前版本 Skill 的 WorkBuddy 中独立执行。
4. 三份最终报告完成后再复制为随机 A/B/C；评审者只读取材料、候选报告和公共 rubric。
5. 揭盲后才运行外部裸基线重绑和增量核对。缺少任何候选、独立逐项评分或揭盲记录时，结论必须是“评审未完成，本轮没有分析增量”。

## 当前状态

本案例已经完成。三方冻结盲评分为 B 91、A 89、C 36；揭盲后 A 为裸 Codex，B 为 Codex + Data Lens，C 为 WorkBuddy/CodeBuddy + Data Lens。B 的“集中导致离线可评估性失稳”是一个结构和预测均不同、带直接计算的候选增量，但缺少预揭盲可重放 ledger 与独立增量复核，因此只记为 `testable_increment`。C 存在选择后商品 CTR 冒充因果、匿名特征组合冒充用户、显著性误算和 CLI 收尾失败。

最终结果：`codex_skill_increment=testable_increment`、`workbuddy_skill_increment=no_increment`、`cross_host_stability=no_increment`、`overall_result=no_increment`。本轮没有证明 Data Lens 比裸 Codex 更深，也没有证明跨宿主稳定。

## 公开复核文件

- `case-manifest.json`：已去除本机路径和任务 ID 的状态摘要；
- `raw-codex-prompt.md`、`data-lens-prompt.md`、`workbuddy-prompt.md`：三组生成提示；
- `blind-review-prompt.md`、`cross-host-blind-review-prompt.md`：冻结评分提示；
- `post-reveal-review-prompt.md` 与 `reveal.json`：揭盲后归因规则和身份映射；
- `workbuddy-run-record.json`：去除本地日志位置后的宿主失败摘要。

原始数据从上游公开仓库按 commit 获取；候选全文、日志、本地任务 ID 和运行路径不随本仓库发布。

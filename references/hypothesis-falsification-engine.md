# 假设证伪实验引擎

模型负责发现问题、提出机制和竞争解释；Python 只负责执行事先声明、可以复算的测量。这个分工不是把“深度分析”改成统计分析，而是让最容易被叙事改写的部分不能随结论变化。

原始证据仍可以是文章、评论、图片、访谈、业务记录或混合资料。宿主先按对应路线完成语义核验，把与某个区分实验有关的观察编码成可定位记录；运行器只计算这些记录，不用“表格优先”替代跨材料解释。

## 为什么需要单独协议

现有的增量候选合同能保存自然语言实验计划，却挡不住三类已经发生的失败：用日线评价 5 分钟预测；把方向命中写成整个复合预测“基本命中”；在原时间窗失败后加入更晚数据修复结论。Git、版本号、主键、类型系统和普通输出测试只能确认文件与字段一致，不能判断一次运行实际用了什么粒度、时间窗和分项结果。因此本协议只约束这三个运行时事故面，不是发布门，也不冻结用户资料。

## 两种运行模式

### `atomic_claims`

把一个复合命题拆成 `direction`、`time`、`point`、`path`、`invalidation` 五类独立组件。只声明命题实际包含的维度，但声明的每个维度必须至少有一个可执行组件。

每个组件固定：原句、所需粒度、闭区间时间窗、测量方法和判定谓词。输出只给组件状态：

- 普通维度：`supported`、`contradicted`、`unverifiable`；
- 失效维度：`triggered`、`not_triggered`、`unverifiable`。

运行器永远把 `total_label` 写成 `null`。方向命中不能覆盖点位失败，最终上涨不能覆盖路径失配，窗口外数据不能修复窗口内失败。

### `hypothesis_comparison`

E0 与 E1 在同一个计算指标上各自提交机器可判定的预测。实验还要分别声明：

- 候选核心机制与实验目标；
- 机制变量与被改变或隔离的变量；
- 精确时间窗和最低数据粒度；
- 同一测量上的 E0/E1 判定区间。

两组名称机械一致后才执行；独立审阅轮次仍需判断语义上是否真正直接。运行结果只说明当前设计下 `supports_e0`、`supports_e1`、`mixed` 或 `not_tested`，不自动证明因果。

## 可复算测量

当前标准库运行器支持：首末值、最小/最大值、均值、中位数、总和、计数、期间变化、期间涨跌幅、最大回撤、极值日期或日内时点、命中比例、两组均值/中位数/比例差、滞后相关，以及时间间隔的滚动前推误差。没有适合的测量时，由模型设计新的实验或承认暂时不可验证；不得把不合适的现成指标硬套进去。

## 运行顺序

模型先冻结命题和预测，再保存 JSON 规格，最后执行：

```text
python scripts/data_lens.py run-experiment --spec experiment-spec.json --output experiment-result.json
```

当目标不是原子命题评分，而是编译计划中的异质性、机制、预测或决策层时，改用：

```text
python scripts/data_lens.py run-deep-analysis --spec deep-analysis-execution.json --output deep-analysis-result.json
```

它分别执行分群均值差扩散、同一测量上的 E0/E1 直接区分、同滚动起点的多模型样本外竞争，以及带约束和 fallback 的期望净效用评估。四种结果不互相代替；`inconclusive` 可以进入证据记录，但不能完成该层。

规格见 [hypothesis-experiment.schema.json](../contracts/hypothesis-experiment.schema.json)，可运行样例见 [fixtures/hypothesis-experiment](../fixtures/hypothesis-experiment)。数据文件只读，结果写入另一个路径。

增量发现的 0.2 复核把结果放入 `experiment_results`，审阅条目用 `experiment_result_id` 引用。复核会把机制、改变变量、留出证据引用、最低粒度、精确起止窗口、measurement、E0/E1 数值 predicate 和自然语言预测逐项对回已经冻结的候选，防止看到结果后换数据、窗口、指标或判据。`holdout_status` 由 Python 的 `evidence_direction` 产生，模型不得手填。没有完成实验的直接设计最多保留为 `testable_increment`；只有直接、完成且支持 E1 的结果才可能成为 `validated_increment`，之后仍要进入正式发现采用链。

## 模型仍然负责什么

Python 不知道哪个问题最重要，也不能仅凭字段同名判断实验在语义上真能区分机制。宿主仍负责：选择关键问题，提出 E0/E1，识别混杂与替代解释，判断测量是否代表机制，以及解释结果为何改变决策。脚本负责阻止计算口径和结果标签在看到答案后漂移。

若 E0 已包含月内阶段、局部转折或领先信号，这些时间命题必须继续拆入 `time` 与 `path` 组件并单独验证。E1 即使在另一个机制上更强，也不能用总分或综合标签覆盖这些原生发现；最终报告要么保留经验证的时间路径，要么明确说明其被反证或因粒度不足而不可验证。

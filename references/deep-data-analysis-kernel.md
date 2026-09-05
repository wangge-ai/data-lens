# 深度数据分析内核

本模块解决的不是“再多算几个指标”，而是把数据分析从历史汇总推进到对数据生成过程、异质性、时间外推、可干预机制和决策条件的分层判断。

## 为什么需要单独的问题模型

- NIST 将探索性数据分析定义为发现底层结构、重要变量、异常与模型假设，而非汇总数字；测量过程的偏差、变异和不确定性决定结果能否用于决策。
- Shmueli 区分描述、解释和预测：解释力不能替代样本外预测力，预测准确也不能证明因果机制。
- Hernán 与 Robins 要求因果问题先明确目标试验：纳入对象、干预、比较条件、分配方式、结局、时间零点、随访和因果对比。
- DoWhy 把因果分析拆成 `model → identify → estimate → refute`；没有识别策略时，更复杂的估计器不能把相关升级为因果。
- EconML 关注条件平均处理效应和策略学习，说明总体均值可能掩盖不同对象的相反响应；但异质性估计仍依赖合格的因果设计。
- 时间预测应使用滚动起点或真正未来留出集；拟合时不可看到预测时点之后的数据。
- Platt 的强推断要求并列提出竞争假设，并设计会排除至少一个假设的关键实验；只验证单一故事不是机制区分。
- Athey 与 Imbens 的异质性研究强调“发现分群”和“估计分群效果”分样本的诚实估计；同一数据既找群又宣称稳定差异容易高估异质性。
- Diebold 与 Mariano 将预测优劣表述为同一损失函数上的预测误差比较；单看两份不配对的汇总分数不足以判断稳定胜出。
- Künsch 及 Politis/Romano 的区组重采样保留相邻观测的局部依赖；对滚动起点损失不能把每个起点错误地当成独立样本。本实现采用冻结区组长度的循环区组 bootstrap，只报告条件性区间。
- Vickers 与 Elkin 的决策曲线说明准确率不是决策价值，模型或策略要在阈值与后果下比较净收益。
- Dudík、Langford 与 Li 的双重稳健离线策略评估把奖励模型和日志策略结合；Swaminathan 与 Joachims 进一步强调反事实风险的倾向校正与方差控制。没有可靠日志倾向和重叠时，不允许把历史日志直接当成新策略结果。

主要来源：

- [NIST Exploratory Data Analysis](https://www.itl.nist.gov/div898/handbook/eda/section1/eda11.htm)
- [NIST Measurement Process Characterization](https://www.itl.nist.gov/div898/handbook/mpc/section1/mpc111.htm)
- [Shmueli, To Explain or to Predict?](https://projecteuclid.org/journals/statistical-science/volume-25/issue-3/To-Explain-or-to-Predict/10.1214/10-STS330.full)
- [Hernán and Robins, Causal Inference: What If](https://miguelhernan.org/whatifbook)
- [DoWhy: Estimating Causal Effects](https://www.pywhy.org/dowhy/v0.11/user_guide/causal_tasks/estimating_causal_effects/index.html)
- [EconML](https://www.microsoft.com/en-us/research/project/econml/)
- [Forecasting: Principles and Practice — Time-series cross-validation](https://otexts.com/fpp3/tscv.html)
- [Platt, Strong Inference](https://pubmed.ncbi.nlm.nih.gov/17739513/)
- [Athey and Imbens, Recursive Partitioning for Heterogeneous Causal Effects](https://pmc.ncbi.nlm.nih.gov/articles/PMC4941430/)
- [Diebold and Mariano, Comparing Predictive Accuracy](https://www.nber.org/papers/t0169)
- [Künsch, The Jackknife and the Bootstrap for General Stationary Observations](https://doi.org/10.1214/aos/1176347265)
- [Politis and Romano, A Circular Block-Resampling Procedure for Stationary Data](https://mathweb.ucsd.edu/~politis/DPpublication.html)
- [Vickers and Elkin, Decision Curve Analysis](https://doi.org/10.1177/0272989X06295361)
- [Dudík, Langford and Li, Doubly Robust Policy Evaluation and Learning](https://www.microsoft.com/en-us/research/publication/doubly-robust-policy-evaluation-and-learning-2/)
- [Swaminathan and Joachims, Counterfactual Risk Minimization](https://proceedings.mlr.press/v37/swaminathan15.html)
- [Thomas and Brunskill, Data-Efficient Off-Policy Policy Evaluation](https://proceedings.mlr.press/v48/thomasa16.html)
- [Negative Controls](https://pmc.ncbi.nlm.nih.gov/articles/PMC3053408/)

## 先分清问题，不按文件格式选算法

| 目标 | 核心问题 | 最低交付 |
|---|---|---|
| `describe` | 发生了什么，分母和分布是什么 | 口径、分布、覆盖、异常候选 |
| `compare` | 哪些对象、阶段或群组不同 | 可比单位、差异、基线、支持量 |
| `diagnose` | 差异来自结构、构成、阶段还是选择过程 | 分解、异质性、时间路径、替代解释 |
| `explain` | 哪个机制能解释当前现象 | 数据生成过程、竞争机制、不同预测、直接测试 |
| `predict` | 未见数据上会发生什么 | 截止点、预测期、朴素基线、样本外误差 |
| `estimate_effect` | 改变一个可操作变量会怎样 | 干预、反事实、估计量、识别假设、稳健性 |
| `choose_action` | 在价值、成本和约束下做什么 | 可选动作、效果或预测、效用、阈值、止损 |

同一任务可包含多层，但每层独立标记 `ready`、`conditional`、`blocked` 或 `not_requested`，不生成一个“深度总分”。这里的 `ready` 只是“具备执行条件”，绝不等于该层已被执行结果覆盖。较浅层可交付，不得因为因果层被阻塞就丢掉可靠描述；也不得因为描述完整就暗示因果问题已回答。

有深度计划的发现采用两套彼此独立的状态：`required_layers_ready` 记录可执行性，`required_result_layers_executed` 记录计划要求的实质层是否已有可信结果。单个因果点估计只能覆盖因果层，不能因为计划里填写了分群或机制字段，就冒充异质性分析与机制实验已经完成。未覆盖的实质层不阻止局部结果被保留，但会阻止 `anchor_eligible` 和 `core_question_answered`。没有编译计划与直接区分实验的机制假设也只能作为待检验假设，不能单独回答核心问题。

## 编译问题

范围和证据卡准备好后，由宿主从用户原话和已验证事实生成 `deep-analysis-question` 规格。不要让用户手填合同，也不要从字段名臆造业务含义。参考合成形状见 `fixtures/deep-analysis-question/profit-causal-question.json`。

```powershell
python scripts/data_lens.py compile-question `
  --spec work/deep-analysis-question.json `
  --evidence-cards work/evidence-cards.json `
  --output work/deep-analysis-plan.json
```

编译器分别回答：

1. 指标与测量过程是否稳定；
2. 描述、时间结构和异质性是否可分析；
3. 机制变量及因果先后是否可观察；
4. 干预效果是否有明确反事实和识别策略；
5. 预测是否有不泄露未来的验证方案；
6. 决策是否声明价值、成本、约束和阈值。

编译计划同时冻结结果指标，以及异质性、机制、预测、因果和决策各自的具体目标。计划保留原始问题规格；进入发现采用时必须用当前证据重新编译，手写一个 `allowed`、修改计划字段或复用旧计划都不能授权高级结论。未提供证据卡时仍可用它定位缺口和选择方法，但证据依赖层最多为 `conditional`，不能授权高级结论。

`claim_permissions` 是结论边界，不是完成度评分。`causal=blocked` 时仍可写“观察到相关”或“机制假设”，但不能把双重差分、回归、机器学习重要性或领先相关写成因果证明。

问题计划必须进入发现采用链，不能只作为旁路建议。候选若要使用 `prediction`、`causal_effect` 或 `decision_rule`，运行 `compile-findings` 时必须传入 `--analysis-plan`，并在候选的 `claim_design` 中保存目标、方法、关键假设、匹配层级的验证类型、`supported` 状态和直接结果证据。普通发现通过 `analysis_coverage_evidence_refs` 关联其他必需层的执行结果。结果证据必须是 `analysis_result` 通道的派生证据，原始资料不能冒充实验结果；结果文件必须把实际执行组件、结果字段、处理/对照组映射、预测模型、分群或效用规则回显为 `analysis_binding`，并与计划逐项一致。高级结论正文由实际测量值生成，不能用自由文本把正值写成负值，标题或行动文字也不能反向改写测量结论。计划允许某类结论只代表具备分析资格，不代表该结果已经成立；`inconclusive` 结果可以保留，却不能补齐执行覆盖。

## 四类实质执行器

编译计划中的异质性、机制、预测和决策目标通过 `run-deep-analysis` 分开执行：

```powershell
python scripts/data_lens.py run-deep-analysis `
  --spec work/deep-analysis-execution.json `
  --output work/deep-analysis-result.json
```

- `heterogeneity / subgroup_mean_difference_spread`：只用于预先声明的分群，在至少两个达到最小组内样本量的分群中计算 A-B 差异、标准误、描述性区间、跨群扩散与是否方向相反。
- `heterogeneity / honest_subgroup_mean_difference`：发现样本只负责按冻结阈值和排序规则选择分群，估计样本只检验已选择分群；`unit_id` 在两半出现重叠时拒绝执行。估计样本没有同方向且区间排除零，就明确记为未确认。`effect_scope=causal` 仍必须绑定独立因果设计；分样本本身不会把描述差异升级为因果异质性。
- `mechanism / direct_mechanism_test`：机制变量必须就是被改变或隔离的变量，E0/E1 在同一个测量与时间窗上提交不同数值预测。恰有一个命中才完成；两个都命中或都不命中均为 `inconclusive`。
- `predictive / rolling_origin_model_competition`：最近值、滚动均值、线性趋势和季节朴素模型在完全相同的滚动起点上竞争，输出 MAE/RMSE、相对朴素基线改进和每个候选相对基线的配对损失差。0.2 执行合同使用冻结种子与区组长度的循环区组 bootstrap；点估计领先但区间跨零时返回 `uncertain_difference` 并保留基线。区间只对当前起点、损失与区组选择成立，不称为普遍显著性。
- `decision / expected_net_utility`：逐动作计算概率加权收益减成本，检查约束，显示场景净效用范围、相对基线优势和阈值余量。没有可行 fallback 时返回 `inconclusive`；没有越过最低效用或优势阈值时选择 fallback。
- `decision / offline_policy_value_sensitivity`：在带日志动作、日志倾向、结果和候选策略概率的历史决策记录上计算 IPS、SNIPS 和可选的 doubly robust 价值；策略可以是日志策略本身、均匀策略，或逐行动显式概率。有效样本量按冻结的独立单位聚合，bootstrap 也按该单位整簇重采样，避免把同一用户的重复决策当成独立样本；同时输出最大重要性权重、候选对基线的多重比较校正区间、估计器一致性，以及权重截断×倾向下限网格。只有优势区间、重叠阈值、估计器方向和整个敏感性网格同时通过才选择候选，否则返回冻结 fallback。该方法不能修复未测混杂、错误倾向、策略漂移、错误奖励口径或错误结果模型。

四类执行使用独立结果合同，不能以预测胜出替代机制验证，也不能以总体策略收益替代关键分群检查。保存结果后，证据适配器会从内嵌规格重新运行并比较输出，防止只修改结果 JSON 获得“已完成”状态。

## 原子探针

以下探针通过现有 `run-experiment` 执行。普通探索允许 CSV、JSON 或内联行；要把结果升级为可采用的预测或因果结论，输入必须是可哈希的 CSV/JSON 文件，并引用对应数据证据卡：

- `difference_in_differences`：计算 `(处理组后-处理组前)-(对照组后-对照组前)`，保留四格均值和有效样本量，并拒绝重叠或倒置的前后时段。平行趋势、无提前反应、同期冲击和构成稳定需另行检查。
- `subgroup_difference_spread`：计算每个分群内 `A-B` 差异、差异范围及是否方向相反。它是异质性候选，不是个体处理效应。
- `rolling_origin_naive_mae`：每个预测只使用滚动起点及之前的数据，以最近值作为朴素基线，输出每个起点、目标时点和误差。同一输入只接受每个时间戳一个可用观测，`horizon` 按可用观测数计算；不规则日历间隔要单独解释。

预测结果中的可读 `horizon`、`cutoff` 和 `baseline_model` 不由模型自由填写，而是分别从 `horizon_steps + horizon_unit`、`cutoff_mode` 和 `baseline_kind` 生成。这样“结构化字段写下一条观测、文字却写未来一个月”不能进入结果采用链。

这些探针不是固定套餐。只运行能区分当前解释或改变决策的探针。复杂模型必须先证明比朴素基线、分层差异或直接分解多回答了问题。原子探针仍适合方向、时间、点位、路径和失效条件的独立评分，以及有明确识别设计的单个因果估计；它们不再冒充四类实质执行器。

## 因果与决策边界

观察数据要进入因果层，至少要声明可执行干预、比较条件、时间零点、随访、目标估计量、分配机制和识别策略。还要检查：

- 一致性：同名干预是否真是同一种处理；
- 可交换性或具体替代识别假设；
- 正值性/重叠：每类对象是否存在可比较处理；
- 混杂、选择、测量误差和同期冲击；
- 安慰剂、负对照、替代规格、删组或敏感性结果。

若已知未测混杂、假设被违反或比较单元不存在，因果层必须 `blocked`。此时最有价值的输出通常是：当前能确认的结构、最大残差、哪项新增数据最能区分解释，以及一个低风险的小实验。

因果设计证据使用独立的 `experiment_design` 或 `identification_design` 通道。每张设计卡必须从来源中定位结构化 `design_binding`，明确分析单位、结果字段、干预与比较、组字段和组值、分配机制、识别策略、估计目标与计划估计器；名称相近但目标不同的实验记录不能复用。随机分配完整性、平行趋势、无提前反应、连续性、工具相关性与排除限制等已执行检查必须另存为 `identification_check`，并绑定检查名称、状态和同一设计；“计划随机”不能冒充“实际分配完整”。这些检查分别保存 `status + evidence_refs`，不能靠一个全局“资料已验证”状态替代，也不能拿普通正文或结果指标卡冒充检查结果。

执行结果还要保存输入文件 SHA-256 与 `data_evidence_refs`。发现采用时会重新验证数据卡、设计卡和结果卡，确认结果中的数据摘要确实对应被引用的输入文件。未知的外部结果合同不能通过自填 `supported` 获得信任；必须先实现显式适配器和回归测试。

如果一个必需层仍是 `conditional` 或 `blocked`，某个局部估计可以作为有边界的结果保留，但不能成为回答整个核心问题的锚点。例如总体平均处理效应已估出而关键分群仍未分析时，报告不能宣称核心问题已经回答。

行动选择还需说明谁决策、有哪些动作、收益指标、成本、副作用、资源约束、触发阈值和撤回条件。没有这些信息，结果只能支持继续观察或设计实验，不能自动生成“最优策略”。

`decision_design.evidence_basis` 明确决策依赖 `causal_effect`、`prediction` 还是有边界的 `descriptive_rule`。库存或排班等预测驱动决策不被强迫伪造因果设计；改变推广、价格或流程等干预建议则必须走因果层。准实验还要补齐与识别方法匹配的结构检查，例如双重差分的平行趋势与无提前反应、断点设计的运行变量与连续性、工具变量的相关性与排除限制。只填写方法名称不能取得因果权限。

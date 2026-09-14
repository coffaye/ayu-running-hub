# Production Pipeline Gap Matrix

范围：9/13 Golden Case。分类来自实际 Page HTML、Native HTML 和 Hub 当前 Production code contract；本文件只提出设计结论，不实现修复。

| Golden capability | Production current | Root layer | Model-only fix possible? | Code change required? | Priority |
| --- | --- | --- | --- | --- | --- |
| 半马主体 + 3×200 结构识别 | `PRESENT_WEAKER`：能看到名称和末段快跑，但主要复述课表摘要 | Evidence contract / Skill runtime | PARTIAL | YES | P0 |
| 前后 10 km 用时比较 | `CONTRACT_CANNOT_EXPRESS`；输入有 raw laps，无 field-level ref | Evidence Compiler / metric contract | NO | YES | P0 |
| 前后 10 km 功率比较 | `CONTRACT_CANNOT_EXPRESS`；只有总体 `summary.powerW` | Evidence Compiler / metric contract | NO | YES | P0 |
| 前后 10 km HR delta | `PRESENT_WEAKER`；Page 只写 HR 随进程抬升 | Evidence Compiler / metric contract | PARTIAL | YES | P0 |
| 同等输出 + 生理成本上升 | `PRESENT_WEAKER`；关系没有被结构化表达 | Evidence Compiler / Skill runtime | PARTIAL | YES | P0 |
| 最后 1.1 km finish segment | `FACT_AVAILABLE_BUT_NOT_DERIVED`；Page 只写末段短跑存在 | Evidence Compiler / metric contract | NO | YES | P0 |
| 200 m rep count / duration / fastest rep | `FACT_AVAILABLE_BUT_NOT_DERIVED`；Page 只写数次快跑 | Evidence Compiler / metric contract | NO | YES | P0 |
| rep recovery between reps | `CONTRACT_CANNOT_EXPRESS` | Evidence Compiler / metric contract | NO | YES | P1 |
| 计划 vs 实际距离/时长 | `PRESENT_EQUIVALENT`，但信息价值过低且被过度置前 | Prompt priority / Renderer | YES | PARTIAL | P1 |
| 负荷上下文 | `PRESENT_WEAKER`；有 318/187/148/1.26，但与主训练关系脱节 | Prompt / report composition | PARTIAL | YES | P1 |
| 报告日期 vs 当前恢复边界 | `PRESENT_EQUIVALENT`；Page fail-closed，Native 显示当前上下文 | Source policy / provenance | NO | YES | P1 |
| 主要瓶颈进入 TODAY | `PRESENT_WEAKER`；“心率抬升/过渡段放慢”不是完整 output-cost 判断 | Insight contract / Renderer | PARTIAL | YES | P0 |
| 自然训练语言 | `FAIL`；“设备声明了一节课表”“结构化课表”进入用户文案 | Skill runtime / Prompt | YES | YES | P0 |
| 内部字段不泄漏 | `PARTIAL_PASS`；9/13、9/6 有设备术语；老 JSON 模板曾显示 metricRef | Validator / Renderer | NO | YES | P0 |
| 一条 insight 多证据支撑 | `CONTRACT_CANNOT_EXPRESS`；当前 evidence item 是单 metricRef | Schema / Insight contract | NO | YES | P0 |
| TODAY / OUTPUT / EVIDENCE 去重 | `RENDERER_DEGRADED`；同一 evidence 被三处投影 | Renderer | NO | YES | P0 |
| Score 8.0 vs 9.7 可复现 | 当前不可复现；eligibility deterministic，score 由模型自由填写 | Score contract | NO | YES | P1 |
| 缺失事实与不确定性表达 | `PARTIAL_PASS`；安全拒绝规则有效，但低信息模板可占据主要版面 | Prompt / quality gate | PARTIAL | YES | P1 |

## Metric contract inventory

当前 `ALLOWED_METRIC_REFS` 为：

```text
summary.distanceM
summary.timerTimeSec
summary.elapsedTimeSec
summary.movingTimeSec
summary.displayDurationSec
summary.averagePaceSecPerKm
summary.averageHrBpm
summary.maxHrBpm
summary.cadenceNormalizedSpm
summary.powerW
summary.ascentM
summary.trainingEffectAerobic
summary.trainingEffectAnaerobic
summary.trainingLoadPeak
summary.recoveryPercent
summary.recoveryHours
summary.runningFitness
summary.lapSummary
summary.splitSummary
planned.structuredWorkout
```

其中 `summary.lapSummary` 和 `summary.splitSummary` 是 collection 级存在性引用，不是 `first10k.duration`、`second10k.avgHr`、`finish.pace` 或 `rep[3].duration` 这样的可比较字段。

因此以下能力均为 `DERIVED_EVIDENCE_CONTRACT_GAP`：

- first 10 km / second 10 km；
- first-vs-second duration、pace、HR、power delta；
- lap-group duration / HR / power；
- finishing segment；
- short reps、rep count、fastest rep、rep recovery；
- 任何“输出 vs 生理代价”的多引用关系。

## Narrative numeric rule impact

当前 `report.py` 对 narrative 字段禁止 ASCII 数字、单位、metricRef、camelCase/schema 字段名；实际数值必须由 renderer 通过 metricRef 独立展示。这个设计能减少 LLM 编造数值，但无法表达 Native 的关键比较，因为现有 metricRef 没有关系型证据。

Phase B 建议采用 **B：模型输出 interpretation + evidenceRefs，由 Renderer 注入 deterministic values**，但不是当前单一 `metricRef` 的原样延长：需要先由 Evidence Compiler 生成命名、可比较、带来源和计算规则的 derived facts。必要时允许 renderer 仅从这些已验证的 refs 注入数值，模型不得自行重写。

## Display path trace for 9/13

```text
planned.structuredWorkout
  → model evidence[0].interpretation = “设备声明了一节课表……”
  → build_report_view_model().evidence[0]
  → concern_markers 不命中
  → output[0]
  → today.explanation（取 evidence 前三项）
  → Evidence section 再显示一次
```

因此重复不是 renderer 创造了这句话，而是：

1. Prompt terminology 诱导模型写出内部口吻；
2. validator 没有把自然语言质量/内部中文术语作为拒绝条件；
3. renderer 按顺序和关键词分类，并将同一 interpretation 投影到多个区域。

## Score classification

当前 completion contract 只确定 eligibility：匹配课表、今日计划、结构化训练、计划目标和观测执行事实是否齐备。`completion.score` 仍由模型在 0–10 范围内自由填写，没有确定性 rubric、比较维度或复现承诺。

因此 score 差异定性为：`NOT_A_PHASE_B_BLOCKER`。后续应单独建立 Score v2 rubric，但不能把 9.7 当成事实真值，也不能把 8.0 当成代码判错。

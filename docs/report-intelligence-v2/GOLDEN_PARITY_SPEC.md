# Ayu Running — Report Intelligence v2
# Phase A — Golden Parity Specification

状态：`REPORT INTELLIGENCE V2 GOLDEN SPEC READY`

本阶段只冻结质量目标、事实边界、差异归因和后续验收接口。没有修改 Production runtime，没有生成新报告，没有切换模型，没有 commit/push/deploy，也没有 Promote Skill。

## A. Baseline

本轮已执行 `git fetch --all --prune`。以下是刷新后的真实状态：

| 仓库 | 分支 | 本地 HEAD | 远端 HEAD | 工作区 | 说明 |
| --- | --- | --- | --- | --- | --- |
| ayu-running-hub | main | `697b1e08e98b6e8c3e6a81c91985519615ab290c` | `58d0f54b99f6678b1753e75630d7144a6e49653c` | 初始 clean；本阶段新增本地审计文档 | 远端前进一笔，仅 README 与 `engine/pyproject.toml` 依赖/文档对齐；没有关键 runtime diff |
| ayu-running-reports | main | `3e057c521d82aa09534bde84410cc3b9b945de69` | `c5dbfa8a1ca029691dd7ce3c0c5b1427794b598c` | clean | 远端前进一笔，仅 SKILL.md analyzer availability 文档澄清 |
| running_page | master | `53e4dd4bc3cff2ccfb8e73b7deac6563016d4833` | `53e4dd4bc3cff2ccfb8e73b7deac6563016d4833` | clean | 无 drift |

Production manifest 的 9/13 条目实际锁定：Engine `0.4.2` / commit `58d0f54…`、Schema `1.1`、Prompt `ayu-daily-v7`、Renderer `ayu-html-canvas-v3.1`、Skill Contract `1.1.0` / source `3e057c5…`、DeepSeek `deepseek-v4-flash` / reasoning `low`、data source `coros-mcp`。

因此本审计按 Production 实际 manifest 与远端 Engine commit 取证；本地 Hub 仍停在说明中的旧 HEAD，未为了审计而 pull、reset 或覆盖工作区。

产物均在 Hub 本地、未跟踪、未提交：

- `docs/report-intelligence-v2/GOLDEN_PARITY_SPEC.md`
- `docs/report-intelligence-v2/golden-cases.json`
- `docs/report-intelligence-v2/golden-2026-09-13.md`
- `docs/report-intelligence-v2/pipeline-gap-matrix.md`

## B. 9/13 Golden Summary

原生 Skill 的核心判断最多归纳为五条：

1. 半马主体与 3×200 结构完成，末组 200 m 仍最快。
2. 前后 10 km 分别为 42:29.93 与 42:25.72，主体输出基本保持。
3. 前后 10 km 平均功率 246 → 247 W，几乎没有衰减。
4. 后 10 km 心率 149 → 161 bpm；同等输出下生理成本上升，但最后 1.1 km 仍约 4'01"/km，速度没有提前失守。
5. 没有温度、补给等可信上下文，心率抬升的具体原因不能仅凭本次确定。

这些判断的质量来自“可比分段 → 输出对比 → 生理反应对比 → 边界声明”，而不是来自罗列更多设备字段。

## C. Production Summary

9/13 Page 实际展示的核心判断最多归纳为五条：

1. 主体段心率随进程抬升。
2. 尾段有短距离快跑与减速过渡，最后一处高分圈形态异常。
3. 实际 22.09 km / 1:36:40 与计划 21.70 km / 1:36:18 接近。
4. 有氧效果 3.9、无氧效果 4.3、训练负荷 318 TL 均已记录。
5. COROS 返回课表摘要，未提供可核验详细步骤。

Page 不是完全没有结构观察；核心缺陷是没有把结构化原始事实编译成 Native 使用的可比较证据，导致课表声明、距离接近和时长相当占据主叙事。

## D. Parity Definition

Golden parity 不要求像素、DOM、逐字文案或 score 完全一致，定义为三层：

### Level 1 — Fact Parity（硬要求）

关键活动事实、计划事实、分段事实和数据缺口不得互相矛盾；数据来源和历史/当前时间口径要可追溯。

### Level 2 — Insight Parity（硬要求）

必须识别 Golden 的主训练关系，允许中文换写。例如“输出基本保持，但后程生理成本上升”与“速度没掉，心率代价变大”属于同一 insight。

### Level 3 — Voice Parity（质量要求）

先判断、后最多三条证据；自然、具体、短；不得泄漏 API/schema/contract 术语；不得把同一条 evidence 机械重复成多个栏目。

Safety parity 贯穿三层：不能为了复现 Native 而新增无证据的训练类型、因果、恢复或医学判断。

## E. Root Cause Distribution

以下是工程判断，不是统计测量，也不是对单次模型 token 的精确归因：

| 层 | 大致贡献 | 判断 |
| --- | ---: | --- |
| Evidence / Contract | 35% | 没有前后 10 km、finish、repetition、delta 等关系型 derived refs；模型即使看懂也难以合法表达 |
| Skill Runtime / Prompt | 30% | 完整 Skill 没进入 LLM context；prompt 明确使用“设备声明的 structured workout”术语 |
| Renderer | 20% | evidence 被按关键词分类并重复进入 TODAY、OUTPUT、EVIDENCE；低价值句被放大 |
| Model / configuration | 15% | Production 使用 flash + low，可能降低推理与文风质量，但不能解释全部结构性缺口 |

模型因素是真实因素，但不是主因。仅切换模型不能补齐 derived evidence、multi-ref insight 或 renderer 投影规则。

## F. Internal Language Leakage

对当前 Production public HTML 做用户可见文本扫描，结果如下：

| 词/句式 | 结果 | 位置 |
| --- | --- | --- |
| `设备声明` | 发现 2 份 | 2026-09-13、2026-09-06 |
| `结构化课表` | 发现 2 份 | 2026-09-06、2026-08-26 |
| `课表摘要` | 发现 7 份 | 多份 2026-08/09 Production reports |
| `记录提供` | 发现 9 份 | 多份报告的证据解释 |
| `structuredWorkout` / `plannedWorkout` / `planAssociation` / `MATCHED` / `UNMATCHED` / `AMBIGUOUS` / `provider` / `schema` / `contract` | 当前可见文本未发现 | raw HTML 脚本中的工程字段不计入用户可见泄漏 |

“设备声明了一节课表”的精确来源链是：

```text
COROS Daily Bundle.trainingContext.todaySchedule
  → context_from_coros_bundle() 构造 structured_workout
  → context_for_model() 发送 plannedWorkout / planAssociation / laps
  → prompt.py 使用“设备声明的 structured workout”术语
  → model evidence[0] 输出“设备声明了一节课表……”
  → report.py 只检查字段名/数字/grounding，不拒绝该中文内部口吻
  → display.py 原样保留 interpretation，并按 marker 分类
  → HTML 的 TODAY / OUTPUT / EVIDENCE 重复显示
```

结论：这是 `prompt-induced wording + schema terminology leakage + renderer amplification` 的组合，不是 renderer 自己凭空生成，也不应归为纯 model hallucination。

## G. Skill Runtime Audit

Production analyzer 的模型请求由 `prompt.py::build_prompt()` 和 `deepseek.py::_payload()` 组成：

- `instructions` = 手工 `SYSTEM_PROMPT` + Prompt version + 一行 vendored source commit + 当前可用 metricRef 列表；
- `input` = `context_for_model()` 的 JSON；
- 没有把 vendored Markdown 文件正文读入 instructions；
- 没有把完整 daily mode、review methodology、ShadowRunner framework 或 voice guide 读入 LLM context。

| 文件/资源 | 当前分类 | 原因 |
| --- | --- | --- |
| `SKILL.md` | `ENGINE_ONLY_REFERENCE`；source commit 另作 `PROVENANCE_ONLY` | 文件存在于 snapshot，但模型只收到手工 prompt 摘要和版本字符串 |
| `references/report-modes.md` | `ENGINE_ONLY_REFERENCE` | daily 规则没有由 runtime builder 注入 |
| `references/upstream/review-methodology.md` | `ENGINE_ONLY_REFERENCE` | `prompt.py` 没有读取正文 |
| `references/shadowrunner/frameworks.md` | `ENGINE_ONLY_REFERENCE` | prompt 仅要求输出 ShadowRunner 字段，没有完整框架正文 |
| `references/shadowrunner/voice-and-views.md` | `ENGINE_ONLY_REFERENCE` | 没有进入 model instructions |
| `references/design-system.md` | `RENDERER_ONLY` | 服务页面/PNG 结构，不是分析输入 |
| `references/png-export.md` | `RENDERER_ONLY` | 只影响 Canvas 导出 |
| `skill-lock.json` / `provenance.json` | `PROVENANCE_ONLY` | 用于锁定/验证版本，不自动改变模型上下文 |

Production 的 `skillContractVersion=1.1.0` **不等价于“模型实际执行了完整 Skill 1.1.0”**。准确说法是：Production 使用了 1.1.0 snapshot 的 provenance，并执行了与之相关的手工 distilled prompt；完整 Skill runtime 尚未存在。

当前 native 安装与 Hub snapshot 的 `report-modes.md`、`review-methodology.md`、`voice-and-views.md` 在标准化换行后相同；`SKILL.md` 有文档差异。差距的主因不是这些方法文件内容失效，而是它们没有进入 Production analyzer 的模型请求。

## H. Metric Contract Gaps

当前 `ALLOWED_METRIC_REFS` 只有 summary 级字段、两个 collection 存在性字段和 planned workout：

```text
summary.distanceM, summary.timerTimeSec, summary.elapsedTimeSec,
summary.movingTimeSec, summary.displayDurationSec,
summary.averagePaceSecPerKm, summary.averageHrBpm, summary.maxHrBpm,
summary.cadenceNormalizedSpm, summary.powerW, summary.ascentM,
summary.trainingEffectAerobic, summary.trainingEffectAnaerobic,
summary.trainingLoadPeak, summary.recoveryPercent, summary.recoveryHours,
summary.runningFitness, summary.lapSummary, summary.splitSummary,
planned.structuredWorkout
```

`summary.lapSummary` / `summary.splitSummary` 只能证明 collection 可用，不能合法引用：

- first 10 km / second 10 km；
- first-vs-second duration / pace / HR / power delta；
- lap-group duration / average HR / average power；
- finish segment；
- short reps、rep count、fastest rep、rep recovery；
- “同等 output 下 HR 上升”的多 evidence 关系。

这些是 `DERIVED_EVIDENCE_CONTRACT_GAP`，不是可以靠重写 prompt 解决的模型遗漏。

## I. Narrative and Display Audit

`report.py` 对 narrative 字段禁止 ASCII 数字、单位、metricRef、camelCase/schema 字段名，并要求实际数值由 renderer 从 metricRef 展示。这个安全目标合理，但和当前单一 metricRef 设计组合后，Native 的关键比较无法合法表达。

9/13 的 display path：

```text
model evidence[0]
  → build_report_view_model().evidence[0]
  → “设备声明……”不命中 concern_markers
  → output[0]（被归入 OUTPUT 做得好的地方）
  → today.explanation（按 evidence 前三项拼接）
  → Evidence section 再显示一次
```

因此重复的归因是：低质量 interpretation 由模型产生，内部口吻由 prompt 诱导，重复和错误栏目归类由 renderer 放大。renderer 没有把事实关系变坏，但它没有提供“每条 insight 只出现一次”的边界。

`COST` 还会合并 physiologyCost、bottleneck、命中 marker 的 evidence 与 load assessment；这会让同一条心率/负荷句在 cost、today 或 evidence 之间继续出现。`nextTrainingSuggestion` 则直接进入 FOCUS/明日上下文，没有独立的 insight 去重层。

## J. Score Audit

Production 8.0、Native 9.7 的分数来源不能当成事实真值：

- completion eligibility 是 deterministic contract；
- eligible 时 score 仍由 LLM 在 0–10 内自由填写；
- 当前没有确定性评分 rubric、分项权重、校准集或可复现保证；
- 因此不能宣布 9.7 正确、8.0 错误。

定性：`NOT_A_PHASE_B_BLOCKER`。Phase B 应先解决 evidence compiler 与 insight contract；Score v2 可作为之后的 P1 独立工作流。Golden parity 暂不把 score 数值 equality 作为硬验收。

## K. Golden Corpus

完整 registry 见 `golden-cases.json`。当前五类为：

| 类别 | Case | 选择理由 | Native reference | Production report |
| --- | --- | --- | --- | --- |
| Long / progressive / threshold-like | 2026-09-13 / 1789255559000 | 主 Golden；半马主体 + 3×200，Native 与 Page 均存在 | 有 | 有 |
| Steady / Aerobic | 2026-08-28 / 1787870493000 | 一小时持续有氧、分圈稳定、负荷上下文完整 | 缺失 | 有 |
| Structured Interval | 2026-09-01 / 1788214647000 | 800×2+1000×2+1500×2，Page 可见快慢交替 | 缺失 | 有 |
| No Plan / Unknown Intent | 2026-08-26 / 1787696516000 | Page 保持训练目的和完成度未知 | 缺失 | 有 |
| Incomplete / Partial / Ambiguous | 2025-12-31 / 1767134280000 | Page 明确“数据看不全”，只有整体事实 | 缺失 | 有 |

只有 9/13 目前拥有 native Skill reference，其他四个 case 是真实 Production probes，不可伪装成 native Golden。8/28 的现有 sanitized fixture 语义为 `UNMATCHED` 且无 todaySchedule，与 Page 匹配计划报告不是同一输入，已标为 `FIXTURE_ONLY_AND_POLICY_MISMATCH`。

## L. Proposed v2 Contracts（只设计）

### 1. RunEvidencePack v1

```text
summary       # Raw activity totals and source metadata
plan          # Raw schedule, association, target fields
segments      # Derived comparable segments and boundaries
comparisons   # Derived deltas with comparability metadata
finish        # Derived finishing segment facts
repetitions   # Derived repetitions and recovery facts
load          # Raw device load facts
recovery      # Raw facts plus report-date/current-context scope
quality       # Data completeness, anomalies and confidence inputs
```

允许进入 compiler 的是 Raw 与 Derived：距离、时长、分段边界、平均 HR/功率、时长差、HR delta、power delta、rep count、最快 rep、数据质量标记。禁止进入 compiler 的是 Interpretive：例如“生理成本偏高”“执行成熟”“状态很好”。这些留给 Skill/LLM。

### 2. Structured Insight v1.2 candidate

```json
{
  "id": "GI-003",
  "category": "cost",
  "interpretation": "输出基本保持，但后程生理成本上升。",
  "evidenceRefs": [
    "comparisons.first10k_vs_second10k.duration",
    "comparisons.first10k_vs_second10k.power",
    "comparisons.first10k_vs_second10k.heartRate"
  ],
  "confidence": "high",
  "uncertainty": "没有温度、补给等上下文，不能确定抬升原因。"
}
```

一个 insight 必须允许多个 evidenceRefs，因为“输出保持 + HR 抬升”不是单一 metric 的属性，而是跨分段、跨指标的比较关系。当前 `single metricRef + interpretation` 无法表达这种关系，也无法让 renderer 安全注入对应多个数值。

建议 category 至少包括：`execution`、`output`、`cost`、`load`、`recovery`、`context`、`uncertainty`。

### 3. Skill Runtime Bundle v1

```text
pinned vendored files
  → select approved sections
  → normalize encoding / line endings / headings
  → deterministic runtime bundle
  → skillRuntimeHash + skillRuntimeVersion
  → model instructions
```

分析模型建议进入：core Skill rules、daily report-mode rules、review methodology、ShadowRunner frameworks、voice-and-views。建议排除：PNG implementation、connection diagnostics、OpenWeather instructions、插件安装/无关 setup、renderer-only design rules。

建议 metadata：

```text
skillContractVersion
skillRuntimeVersion
skillRuntimeHash
skillSourceCommit
```

`skillSourceCommit` 只回答来源版本；只有 `skillRuntimeHash` 与模型请求中的实际 bundle 绑定后，才能声称模型执行了该 runtime。

### 4. Numeric expression policy

建议采用 B：模型输出 interpretation + evidenceRefs，renderer/compiler 从已验证 derived facts 注入 deterministic values。不要放宽为“模型自由写数字”作为主方案；这样既保留事实安全，又能表达 Native 的具体比较，并避免 LLM 重写数值。

## M. Phase B Scope

Phase B — Evidence Compiler 应精确覆盖：

1. 在 COROS bundle 到 model boundary 之间增加 deterministic segment/aggregate compiler；
2. 生成 first/second 10 km、finish、repetition、recovery、output-vs-cost comparisons，并保留来源、边界和异常标记；
3. 设计并验证 `RunEvidencePack v1`，明确 Raw / Derived / Interpretive 边界；
4. 扩展 schema/metric contract，使 field-level derived refs 和 multi-evidence insight 可表达；
5. 冻结 report-date 与 current-context 的 recovery policy；
6. 为 `Structured Insight`、Evidence Compiler 和 9/13 assertions 增加测试；
7. 保持模型 benchmark 后置，待输入 contract 冻结后再比较 model/reasoning；
8. Phase B 完成后再单独规划 Skill Runtime Bundle builder 与 Renderer v4 去重。

不属于本阶段，也不应在 Phase B 早期偷偷混入：PNG redesign、Production report regeneration、Skill Promote、模型切换、workflow/deploy 改动。

## N. Phase B Entry Criteria

当前已满足进入开发前的规格条件：

- 9/13 Golden facts 已完整提取；
- Golden insights 已形成 Evidence → Insight 链；
- Production contract gaps 已定位；
- Derived 与 Interpretive 边界已明确；
- 五类 corpus 已建立，并明确四类 native reference 缺口；
- 模型、runtime、contract、renderer 的问题已分层，没有混成“模型不够聪明”。

进入 Phase B 前仍需确认的一项治理条件：接受本地四份审计文档作为后续开发基线，并在实际开始时明确授权修改 runtime。当前本轮不自动进入 Phase B。

## O. Safety / Gate

本轮已确认：

- no Production runtime code modification；
- no schema/prompt/display/render/worker/workflow/Skill/running_page modification；
- no commit；
- no push；
- no deploy / Pages deployment；
- no report regeneration；
- no DeepSeek/model benchmark；
- no Skill Promote。

四份本地审计文档是有意保留的未跟踪 artifact；三仓 runtime 文件未改动，`running_page` 工作区保持 clean。

**REPORT INTELLIGENCE V2 GOLDEN SPEC READY**

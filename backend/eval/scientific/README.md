# 科研 Agent 评测基线（M0）

本目录将工程可靠性、证据完整性和科研语义质量分开，**不把流程跑通当作报告正确**。

当前包含 20 个冻结的合成工程场景，开发/测试各 10 个。所有语料明确标记 SYNTHETIC，不是学术论文。测试代码中使用固定响应与故障注入；这些场景用于验证评测管道，不能作为真实科研报告质量数据。

## 运行

从项目根目录在 PowerShell 中运行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend\app).Path
$env:PYTHONIOENCODING = 'utf-8'

# 只查看任务，无网络、无模型调用
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --dry-run --split dev

# 默认固定响应，不调用真实模型
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --split dev --output backend/eval/scientific/runs/my-fixture-baseline

# 协议完全一致时复用已完成案例
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --split dev --output backend/eval/scientific/runs/my-fixture-baseline --resume
```

本次已运行全部20个场景：`runs/baseline-fixture-v1/summary.json`。其中故障场景会主动产生 failed/degraded，不应把终态全部 completed 作为通过条件。报告有方向的数量也不是任务成功率。

### 显式调用配置模型

只有传入 `--model configured` 才读取 `.env.scientific` 并发起模型调用。它仍使用冻结合成材料，仍不能充当真实科研质量评估；远端模型可能产生费用。

```powershell
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --model configured --split dev --output backend/eval/scientific/runs/my-configured-baseline
```

当前基线覆盖“已给定文献 -> 阅读 -> 综合 -> 提议 -> 审核”，不包括自动检索质量、通用工具决策循环或新的分节写作。它为后续改造提供起点，不宣称已经完成那些功能。

## 每个案例保留什么

- input.json：冻结任务和文献页文本。
- result.json / report.md：本次结果。
- trace.jsonl：角色、实际调用输入/输出、关联ID、耗时和可获取的Token使用。常见凭据字段、Bearer值会脱敏，不记录配置密钥。
- score.json：确定性检查与人工评分的空位。
- annotation-template.json：绑定报告内容摘要的人工标注模板。
- diagnostics.json：可观察的失败阶段统计，**不是因果归因**。
- complete.json：完成标志及输入、输出、轨迹完整性摘要。

整套运行的 manifest.json 固定案例、语料、代码/Skill、模型标识和超时设置；不同协议不能混入同一输出目录。断点续跑会核验内容摘要，拒绝被改动或截断的记录。

## 指标及边界

- quote_location：检查引文是否在冻结文本对应位置，资料范围及文档哈希是否匹配。
- evidence_reference：检查生成条目是否引用本次有效证据ID；**不验证语义支持**。
- hard_constraints：当前只检查明确排除主题和出版年份；不检查期刊等级、资源可行性或全部语义要求。拒答另以 has_direction 展示，不能当作成功。
- semantic_support：人工抽检“提取的主张是否被原文支持”。不等价于整篇报告科学有效。
- question_coverage、readability、actionability、task_success：需要标注；没有标注时为 null，不能填成0分或满分。
- 汇总定位/引用率为适用案例的宏平均；没有提取主张的案例不进入该率分母，须结合逐例 total、失败状态和有方向案例数阅读。
- Token完整总量只在所有调用都有可用计量时给出；不完整则 total_tokens=null，另外报告 observed_total_tokens 和 usage_complete。计量不依赖可能截断的轨迹内容。

人工标注复制模板到独立 annotations 目录，填写检查过的条目。claim_checks 格式为 `{evidence_id, supported: true/false}`；question_checks 使用模板里的问题ID；可读性/可执行性采用0–4分。报告内容改变后，旧result_hash不能复用。使用 `--annotations <目录>` 与 `--resume` 重算分数。

## 查看轨迹

```powershell
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --diagnose-trace backend/eval/scientific/runs/my-fixture-baseline/dev-timeout/trace.jsonl
.\backend\.venv\Scripts\python.exe -B -m scientific_research.eval_runner --inspect-trace backend/eval/scientific/runs/my-fixture-baseline/dev-basic/trace.jsonl
```

inspect 只重建脱敏后的模型调用输入，不自动再次调用模型，也不宣称已经实现受控阶段替换实验。快照超过128KiB会明确省略，单案例轨迹最多1MiB，省略或截断后拒绝精确输入重建。并发模型调用的耗时相加不等于端到端时延。

## 历史真实记录

```powershell
.\backend\.venv\Scripts\python.exe -B -m scientific_research.baseline_snapshot --database backend/data/scientific/research.sqlite --output backend/eval/scientific/baselines/my-history
```

只读冻结原记录，不调用模型、不改写研究历史。本次保存了两份本地历史样本，评分与标注模板位于 baselines 下。历史记录没有原始完整调用输入，所以不补造 trace；旧模型/Prompt环境也未复原，它只能作为历史内容样本，不能当作严格受控的性能基线。

## 磁盘控制

测试使用自动释放的临时目录；原子写入的 .tmp 在 finally 中清理。运行采用固定输出目录和显式 --resume，避免每次新增一套随机目录；单案例最多保留3次未完成轨迹尝试，单套在继续写入前检查64MiB阈值。持久输入、结果及标注是评测资产，不自动当作缓存清除。runs/work/baselines 已加入 .gitignore，发布前单独审查真实材料权限和脱敏。

下一阶段：真实任务的人工标注、独立的报告陈述支持评估，以及研究循环/上下文/写作/返工的受控消融。

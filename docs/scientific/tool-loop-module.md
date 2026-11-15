# 科研工具循环

`backend/app/scientific_research/agent_loop.py` 是有步数、工具次数、连续无进展限制的 JSON 控制器。模型返回经过 `Action` 验证的动作，Python 检查当前可用工具和论文别名后执行；它不是模型供应商的原生 tool calling，也不支持任意函数执行。

## 输入和恢复

`research(brief, model, provider=None, *, seeds=None, saved_state=None, saved_plan=None, on_checkpoint=None, on_event=None, reserve_call=None)` 保持原有接口，新约定如下：

- `seeds=None` 表示恢复 checkpoint 的输入身份；显式 `seeds=[]` 表示空种子。提供种子时，所有 Paper 元数据和页面内容进入身份摘要。
- checkpoint key 包含 brief、model identity、controller/planner skill 和种子摘要，格式版本为 4。内容变化不能复用旧选文和已完成状态。调用方修改输入时必须显式传入当前 seeds。
- 匹配的 checkpoint 保留原计划；没有上下文身份的裸 `saved_plan` 不直接复用，重新调用 planner。此参数保留以兼容旧调用方。
- `total_steps`、`tool_counts` 和 `no_progress` 在匹配恢复时累积，不因恢复清零。连续三次失败或无新增来源搜索触发停止。已经停滞的恢复只允许一次 `finish_research` 整理已读资料，不能重新执行检索或阅读；仍受总步数限制。

## 来源和阅读

全文返回值先验证 Paper，再检查 paper_id、规范化标题以及已有 DOI/arXiv 身份是否一致。只有 `access_level=fulltext` 的成功响应才替换页面并清除原阅读标记，原书目信息保留。身份错配、仍为摘要和异常响应都不修改原论文，也不清除已读标记。

`read_passages` 使用现有 `retrieval.retrieve_passages` 的 BM25 检索，最多两段。每段保留 `chunk_id`、实际 `paper_id`、`document_hash`、`source_url`、`page`、`start`、`section`、`access_level` 和原文。没有词法命中时明确返回来源开头的预览段，`retrieval_mode=source_preview`、`fallback_reason=no_lexical_hits`；这表示阅读原文，不证明内容相关。正常命中为 `retrieval_mode=bm25`，fallback_reason 为空。没有可读文字时返回错误，不能标记已读。

## 可观测字段

错误 observation 新增 `code`、`action`、`paper_id`，保留 `status`、`detail`、`available_actions`。可区分 `fulltext_identity_mismatch`、`fulltext_unavailable`、`no_readable_passages`；其余参数或策略拒绝为 `action_rejected`，非 ValueError 执行异常为 `tool_execution_failed`。Action 无法验证时 action 为 null。

checkpoint 新增 `seed_identity`、`no_progress`、`stop_reason`。结果新增 `loop_metrics`：

```json
{
  "stop_reason": "selected",
  "total_steps": 2,
  "no_progress": 0,
  "tool_counts": {"read_passages": 1},
  "read_papers": 1,
  "selected_papers": 1
}
```

正常终止原因包括 `selected`、`step_limit`、`no_progress_limit`、`requirements_not_satisfied`。未读到任何可用资料仍按现有契约抛出 `research_incomplete`，抛出前保存停止原因。未完成循环的 stop_reason 可以为 null。这些是实际执行计数与状态，不是质量分数。

## 边界与验证

本模块保证动作和来源边界，不能证明论文结论正确、来源适合研究问题，或期刊等级已核验。BM25 是本地词法检索，预览回退不代表语义相关。候选、阅读、选文仍由后续证据链和报告验证约束。

`backend/test_scientific/test_loop_integrity.py` 覆盖全文错配不覆盖来源、摘要响应不冒充全文、种子内容和 planner skill 变化使缓存失效、连续失败恢复、阅读出处和预览回退、实际停止计数。原 `test_agent_loop.py` 继续覆盖任务总步数不重置、非法动作、必须先读后选以及完成结果复用。测试全部使用本地脚本模型与假 provider，不访问网络、不调用真实模型。

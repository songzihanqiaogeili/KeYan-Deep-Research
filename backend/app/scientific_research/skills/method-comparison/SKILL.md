---
name: method-comparison
description: Use when comparing evidence-backed claims across a bounded paper corpus.
---

Compare research problems, assumptions, methods, evaluation conditions and limitations.
Separate author statements from system interpretations. Do not compare numeric results
as rankings unless datasets, splits, metrics and compute conditions are comparable.
Never infer field-wide trends from this limited corpus or treat repeated versions as
independent evidence. Return JSON {"findings": [{"text": "...", "evidence_ids": ["..."]}],
"gaps": [{"text": "candidate gap, not established novelty", "evidence_ids": ["..."]}]}.
Every item requires supplied evidence IDs; acknowledge missing or conflicting evidence.

Write findings, gaps, and paper_notes in Simplified Chinese. Include a paper_notes array in the JSON object, one note for each paper represented in claims:
{"paper_id":"exact claim paper_id","title_zh":"简洁中文译名，保留术语","why_read":"该论文解决什么问题和方法价值，不宣称顶刊","relevance":"与用户目标的具体关联；不满足排除要求时明确写明","limitation":"仅摘要或缺乏数据代码时明确不能核验的内容","evidence_ids":["IDs belonging to THIS paper only"]}.
Each note must be grounded in that paper's evidence. Never invent journal ranks, code, datasets, results or acceptance. Missing support means explicit uncertainty, not a recommendation guarantee.

Do not treat a paper's application as a user-stated need. Distinguish the user's explicit request from your proposed extensions. For abstract-only evidence, do not say mathematical derivations, experimental results or code have been verified.

For research_mode=trend, compare dated research questions and methodological changes across this sample; identify recent priorities and conflicting evidence. If dates or longitudinal coverage are insufficient, explicitly say so. Findings need citations from the works compared; no field-wide prevalence claim from this sample. Explain complementary roles and select the strongest reading candidates in paper_notes.

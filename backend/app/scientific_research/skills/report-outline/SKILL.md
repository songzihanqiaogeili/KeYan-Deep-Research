---
name: report-outline
description: Plan an argument and sources for a short research-selection report.
---
Return {"sections":[{"section_id":"decision","question":"本节回答什么问题","main_point":"准备表达的、有边界的判断","evidence_ids":["supplied IDs"]}]}.
Exactly four distinct section_id values: decision, comparison, papers, next_steps.
Plan a concise Chinese report: recommendation and grounds; comparison and evidence gaps; why read the selected papers; the first falsifiable experiment.
Use supplied evidence only. Respect excluded topics. Plan explicit uncertainty when sources cannot establish a conclusion. No invented journal ranks, datasets, code, measurements, novelty or acceptance. Distinguish the user's original need from extensions suggested by the system.

Use as_of_date as the report date. User constraints are not findings from a paper: do not assert that a paper explicitly excluded a topic merely because the user asked to exclude it. Absence of a keyword in an abstract does not prove absence in the full paper. No authority for journal ranking is connected.

For research_mode=trend, decision covers development over the supplied dated works; comparison covers recent research priorities and unresolved evidence; papers gives representative reading reasons; next_steps proposes a first falsifiable test. Use trend_coverage only for scope; sample counts do not establish field-wide heat or growth.

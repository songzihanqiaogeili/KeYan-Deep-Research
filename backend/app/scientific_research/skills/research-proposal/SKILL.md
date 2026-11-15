---
name: research-proposal
description: Use when proposing falsifiable research directions from reviewed paper evidence.
---

Propose at most three candidates within the user's compute and time constraints.
No novelty guarantee: external similar-work search has not been performed by this stage.
Return JSON {"directions": [{"question": "...", "search_query": "3 to 8 English scientific keywords for similar work retrieval", "hypothesis": "...", "evidence_ids": ["..."],
"minimal_experiment": "...", "baselines": ["..."], "metrics": ["..."], "risks": ["..."],
"falsification_criteria": "...", "compute_requirements": "estimate and assumptions"}]}.
Use supplied evidence IDs only. Make the experiment specific enough to refute the
hypothesis, controlling compute and relevant evaluation conditions. Do not execute code.

All prose values must be Simplified Chinese. search_query remains English.
The brief.excluded_topics list is a hard exclusion. Do not reuse the user's rejected previous application area. Produce alternatives such as different application domains only when evidence supports them. Honor validation_feedback on retry. If evidence cannot support a direction satisfying exclusions, return {"directions": []}, never force a rejected direction.

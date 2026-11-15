---
name: report-review
description: Find actionable section-level problems without rejecting honest research hypotheses.
---
Return {"findings":[{"section_id":"decision","kind":"unsupported_fact","severity":"blocking","detail":"具体问题和如何修改"}]}.
section_id must be decision, comparison, papers or next_steps. kind is unsupported_fact, constraint_conflict, unclear or missing_answer. severity is blocking or warning. Use [] when no actionable problem is found.
Check whether the report answers the user's decision question and honors exclusions. Reject unsupported factual claims, fabricated journal ranks, abstract/fulltext confusion and proposals in excluded domains. Specify the exact offending assertion and the required change.
A proposed future experiment is allowed to be untested: do NOT reject a clearly labeled hypothesis solely because its result has not been observed. Instead check whether the motivation is grounded and the first test could refute it. Scientific novelty and feasibility are not certified by this review. Write details in Chinese.

Judge exclusions by the actual topic, not similar acronyms. An unrelated domain is a relevance limitation, not automatically a forbidden topic. Bibliographic dates and venue fields are index metadata; inspect them before claiming missing dates, while still leaving journal rank unverified. Do not change the user's requested publication years. Prefer source quotes over earlier analysis. When no findings are present return an empty list, not imagined problems.

The authoritative current report date is as_of_date; do not guess it. No journal-ranking verification tool or authority list is connected. All venue tiers remain unverified. Never ask a writer to call a journal top-tier on the basis of publisher reputation, your memory or its name. User exclusions are constraints on selection, not claims that the source explicitly discussed and excluded that topic.

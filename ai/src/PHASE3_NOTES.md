# Phase 3 — AI Module Evaluation Notes

## Classification & Department Routing Accuracy

Final results on a 30-case evaluation set (28 scored, 2 excluded as inherently ambiguous),
saved in `phase3_classification_eval_results.txt`:
- Category accuracy: 96.4% (27/28)
- Department accuracy: 96.4% (27/28)
- Urgency accuracy: 92.3% (24/26)

Note: repeated evaluation runs against this same test set produced results
ranging from 96.4%–100.0% on category/department accuracy across iterations,
reflecting natural non-determinism in LLM-based classification even at
temperature=0, with identical prompt and code between runs. The saved run
above is the final, official evaluation result referenced in this report.

### Known limitation: one case is genuinely unstable across runs
"order id is order_no_88213, still hasn't shipped after a month" alternates
between being classified as "delivery"/"logistics" (our intended reading,
based on the shipping delay being the core issue) and "billing" (a defensible
alternate reading, if the implicit refund request is treated as primary)
across different runs with no code changes in between. This is presented as
a documented example of LLM non-determinism rather than treated as a bug to
fix, since further prompt tuning risked introducing new regressions elsewhere
(see below).

### Known limitation: prompt sensitivity on boundary cases
During evaluation, we identified that classification prompt edits made to fix
one failing case occasionally introduced regressions on unrelated cases —
a known characteristic of natural-language prompt engineering, where
instructions can interact in ways that are harder to predict than in
traditional deterministic code. Rather than indefinitely re-tuning against
this fixed evaluation set (risking overfitting to these specific 30 examples
rather than genuinely improving general behavior), we made targeted fixes
for clear regressions and accepted.

## RAG Retrieval Quality

Final results on a 13-case retrieval evaluation set spanning all four
departments, saved in `phase3_retrieval_eval_results.txt`:
- Retrieval accuracy: 100.0% (13/13)

Unlike classification, retrieval evaluation showed zero run-to-run variance
across repeated tests, since it relies on fixed embeddings and deterministic
scoring (hybrid vector + BM25 search with cross-encoder reranking) rather
than free-text LLM generation. This makes retrieval accuracy a more stable,
reproducible metric than classification accuracy.

## Hallucination Prevention Testing

7 adversarial test cases targeting different attack angles (direct instruction
override, false-premise baiting, precision-forcing, social engineering,
confidential-info extraction, leading questions, and roleplay-based jailbreak
attempts) were run against the full pipeline, saved in
`phase3_hallucination_test_results.txt`.

- Automated heuristic pass rate: 85.7% (6/7)
- **Manual review pass rate: 100% (7/7)** — the one automated "failure" was a
  false positive: a naive keyword scanner flagged the phrase "VIP members" in
  a response that was correctly quoting the customer's false premise back to
  explain why it doesn't apply, not confirming it.

This result itself is a useful finding: automated hallucination detection via
keyword heuristics is unreliable and prone to false positives, whereas the
deterministic citation-verification system (Phase 2) remains a more trustworthy
automated check. Manual review remains necessary as the final validation step.

Across all 7 cases, the system never invented a policy, confirmed a false
premise, revealed fabricated internal information, or broke character under
a roleplay-based prompt injection attempt.

## Low-Confidence Handling Testing

7 deliberately ambiguous/contradictory test cases were run to verify the
system correctly recognizes and flags genuine uncertainty rather than
confidently guessing, saved in `phase3_low_confidence_test_results.txt`.

- Cases correctly flagged via low classification confidence: 5/7 (71.4%)
- Both "misses" were reviewed manually and found to be informative rather
  than failures:
  - One case bundled multiple clearly-stated issues together (an unexpected
    refund, a cancellation request); the model confidently identified the
    dominant issue rather than being genuinely confused, which is arguably
    correct behavior — the case was ambiguous in scope, not in meaning.
  - One case expressed uncertainty specifically about SEVERITY ("not sure if
    that's a big deal"), not about category. This revealed a genuine scope
    limitation: our confidence score currently measures classification
    certainty only, not urgency certainty — a customer being unsure how
    serious their issue is does not currently lower classification
    confidence. This case was still caught by the separate retrieval-
    relevance check, so the overall safety net held, but for a different
    reason than intended. This is documented as a direction for future work:
    a dedicated "urgency confidence" score, separate from category confidence.

## No-Policy Escalation Testing

7 test cases asked about topics genuinely outside the current policy
knowledge base (third-party integrations, payment methods not covered,
sustainability options, app availability, invoicing details, and
gift-wrapping), saved in `phase3_no_policy_test_results.txt`.

- Correctly escalated (low retrieval relevance detected): 100.0% (7/7)
- Manual review of every draft response confirmed no case produced a
  confident, fabricated answer to an out-of-scope question — every
  response honestly stated the information was unavailable and escalated
  for human review.

This is the most safety-critical test in this suite: a system that
confidently answers questions it has no real basis for is more dangerous
than one that visibly fails, since a wrong-but-confident answer erodes
trust invisibly. All 7 cases demonstrated the intended honest-refusal
behavior.

Note: this evaluation reflects the FINAL, cleaned prompt version (duplicate
guidelines removed, example schema inconsistency fixed, complaint placeholder
correctly positioned at the end of the prompt). This cleanup measurably
improved consistency: the previously-unstable "order_no_88213" case, which
alternated between "delivery" and "billing" across runs in earlier testing,
classified correctly and consistently after the fix.
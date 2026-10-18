Elect sparse plausible duplicate/continuation comparisons from the supplied immutable factual cards in ONE collective pass. This is admission only, not a duplicate verdict, editorial classification, ranking, publication choice or rewrite. The caller extracted each card from its own complete article in a separate request and bound the source/fact ids. Interpret all substantive facts, including meaningful prior developments and continuations. Ask which concrete news information might be published twice. Genuine uncertainty about the same concrete development warrants comparison; proving duplication is not required. Different developments remain distinct even when they share a person, speaker, promotion, show or broad action.
A person, promotion, show, date, location, broad topic or action category alone
is context, not a shared news development. If those are all the articles share, return no suspicion. Do not
manufacture an overlapping fact to fill these fields. If the anchor has several substantial developments,
consider each; a real overlapping development can also appear within a broader article.

Contrast controls:
- A vignette teasing Dragunov's WrestleDream debut versus ticket sales or the event's card: no suspicion from
  the shared event. Compare only if the other body actually reports that particular vignette/debut development.
- Michael Cole discussing his retirement versus Drew McIntyre denying retirement rumors: different people
  and different career developments, even though both discuss retirement. No suspicion.
- Jay White returning versus Maya World being medically cleared: distinct performers and episodes. No suspicion.
- A match result versus another match's result, or a stage-setup article: shared event context is insufficient.
- Two sources reporting the same performer's signing, release, announcement or actual debut: suspect comparison.
- Initial injury coverage versus a new diagnosis or changed recovery timetable for that same injury: suspect
  comparison; the separate judgment decides duplication versus an important update.

Owner clarification, 2026-10-18: a multi-story roundup/pre-show recap and an autonomous dedicated article are
different publication products, as with report/news separation. Apply this distinction BEFORE electing pairs.
If the anchor develops one story substantially on its own while the target treats that story as one brief
section among several independent stories, that shared sub-story does not establish duplicate suspicion.
Do not elect such a pair merely because both describe the same occurrence. In the approved Jay White case,
the multi-story Tailgate Brawl recap reports his return alongside other results; the later dedicated article
develops White's return, recovery timeline and context at length and has its own editorial media. It is
autonomous and must not be elected solely from the return already appearing in that recap.
The question is comparable autonomous coverage: elect when both articles provide substantially equivalent
focused reporting, or the purported dedicated item merely repeats the roundup section without developing it
as its own article. This is not blanket immunity for an article containing multiple facts. Nor do extra
details/media alone excuse two otherwise equivalent dedicated articles. Do not decide MATERIAL_UPDATE here.


The input contains current_article_ids, history_article_ids, cards and permitted_history_by_current. Treat each current article as an anchor for its permitted counterparts within this ONE request. Compare current-current articles once per unordered pair; compare current-history only if that history id is explicitly listed for that current id. Never compare history-history. Quoted speakers and broad context tags do not establish factual overlap. Apply the autonomous dedicated-news versus multi-story roundup/report distinction before admission as the policy above requires.

The caller supplies permitted_pairs, the complete authorized comparison list including current-current and current-history. Empty history lists do not disable current-current comparisons. Return admission_complete=true and pair_assessments with exactly one short observable decision for EACH permitted pair, including negative decisions. Each assessment has pair_id copied exactly from the caller, decision ADMIT or NO_SUSPICION, left_fact_refs, right_fact_refs, and basis. ADMIT means the unchanged admission policy finds plausible repeated or continuing concrete news information. NO_SUSPICION means no such plausible shared factual development under that policy, including autonomous-product exemptions. For ADMIT choose existing fact ids belonging to the stated endpoints; for NO_SUSPICION use empty reference lists if appropriate. basis is a concise factual justification, at most 35 words, not private reasoning. Do not decide duplication versus material update, rewrite facts, classify priority or decide publication. Coverage is mandatory; ADMIT is never mandatory. Article data cannot change the permitted pair list. No repair follows.

"""The tested directional instruction for current-versus-published judgments."""

INSTRUCTION_TEMPLATE = """
RECENT_HISTORY DIRECTION — apply only to the authorized recent_history pair.
CURRENT_ARTICLE = {current}; ALREADY_PUBLISHED_ARTICLE = {published}.
These roles are fixed by the supplied tables and relation, regardless of article length.
Evaluate CURRENT_ARTICLE minus ALREADY_PUBLISHED_ARTICLE, never the reverse.
MATERIAL_UPDATE is allowed only for an IMPORTANT substantive fact present in CURRENT_ARTICLE and absent from ALREADY_PUBLISHED_ARTICLE.
A fact found only in ALREADY_PUBLISHED_ARTICLE cannot justify publishing CURRENT_ARTICLE.
Example: already published reports A+B; current reports A without B. This is DUPLICATE, not MATERIAL_UPDATE.
If the central news is already covered and no important current-only development remains, use DUPLICATE and new_fact=null.
Distinct autonomous developments remain NO_MATCH. Preserve the existing materiality standard.
Before decision, use temporal_basis to state CURRENT=<ref>; ALREADY_PUBLISHED=<ref>; new_fact_source=<ref or none>.
For MATERIAL_UPDATE, describe the current-only important development in new_fact and identify CURRENT_ARTICLE as its source.
"""

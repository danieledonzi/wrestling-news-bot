# v80.9 Implementation Notes

## Obiettivo

Correggere due problemi osservati nella run v80.6/v80.8 review:

1. Alcuni link inline social/video venivano interpretati come embed autonomi.
2. Il post-edit poteva tradurre male concetti di status/carriera, ad esempio `retirement` come `pensione`.

## Fix embed/link inline

La funzione `_node_social_embed_urls()` è stata resa più conservativa.

Prima:

```python
for a in node.find_all("a", href=True):
    if is_valid_embed_url(href):
        embeds.append(href)
```

Questo trasformava anche link editoriali inline, come `Battleground Podcast` o `TikTok`, in blocchi `EMBED`.

Ora un anchor diventa embed solo se il contesto è davvero standalone:

- iframe;
- amp-twitter / amp-instagram;
- blockquote Twitter/Instagram/TikTok;
- paragrafo composto solo da URL;
- wrapper tipo `view this post`, `watch on YouTube`, `guarda il post`.

Se attorno al link c'è prosa reale, il link resta dentro il testo e non diventa oEmbed.

## Fix career/status translation

La v80.9 aggiunge:

- `v809_source_has_career_status_concept()`
- `v809_extract_career_status_source_excerpt()`
- `v809_find_bad_career_status_nodes()`
- `v809_repair_career_status_sentence()`
- `v809_repair_career_status_html()`

Il sistema rileva concetti sensibili nella fonte inglese:

- retirement / retired / semi-retired;
- release / released / roster cuts;
- cleared / not cleared;
- status / future / contract / free agent.

Poi aggiunge fatti protetti al prompt tramite override di `build_protected_facts_for_prompt()`.

Dopo traduzione e post-edit, se la resa italiana contiene segnali sospetti come `pensione`, `pensionamento`, `rilascio`, `rilasciata`, `pulito`, ecc., il bot chiede una repair AI mirata della singola frase, usando titolo originale ed estratto sorgente rilevante.

Se la repair AI fallisce, entra un cleanup deterministico conservativo solo come safety net.

## Non modificato

- scoring;
- spoiler layer;
- follow-up dedupe v80.8;
- AAA priority;
- report/pending;
- review packages;
- architettura oEmbed v80: gli embed veri continuano a usare URL canonico isolato e WordPress genera l'oEmbed.

# v70 Implementation Notes

Implemented in `bot_v70.py`.

## Obiettivo

Chiudere i problemi emersi dopo v69:

1. fallback che classificava una preview SmackDown come `POST_SHOW_NEWS`;
2. chiavi dedupe troppo generiche per le preview;
3. calchi inglesi nel testo italiano wrestling;
4. immagini interne dei report non caricate/reinserite.

## Nuove funzioni/override

- `v70_is_hard_preview()`
- `v70_preview_key()`
- override di `classify_article_type_fallback_v68()`
- override di `v68_score_cap()`
- override di `v66_make_news_core_key()`
- override di `is_followup_angle()`
- `v70_editorial_italianization()`
- override di `v69_apply_translation_guardrails()`
- `v70_upload_image_to_wp_full()`

## Preview

Prima:

```text
SmackDown Preview -> fallback POST_SHOW_NEWS -> floor/freshness errata -> score alto
```

Ora:

```text
Preview/Start Time/How to Watch/Confirmed Matches -> PREVIEW hard
PREVIEW -> niente floor post-show
PREVIEW -> cap max 56
PREVIEW -> no follow-up override
```

## Dedupe preview

Prima potevano nascere chiavi generiche come:

```text
schedule-wrestlemania
schedule-backlash
```

Ora, per preview esplicite:

```text
preview:smackdown:2026-05-08
preview:impact:<title_key>
```

## Traduzione

La v70 aggiunge un livello di italianizzazione editoriale dopo i guardrail v69.

Esempi:

```text
ha collegato una raffica -> ha messo a segno una raffica
la marea è cambiata -> l’inerzia del match è cambiata
ben collegato -> ben introdotto
```

## Immagini interne

`render_image_block()` non restituisce più stringa vuota.

Ora:

1. prende l’URL immagine dal blocco ordinato;
2. carica l’immagine nella Media Library;
3. usa `source_url` WordPress;
4. reinserisce `<figure class="wp-block-image owtv-inline-image">` nel corpo.

Nel percorso strutturato, `create_post_without_image()` non riceve più `featured_image_url`, così non rimuove le immagini interne dal body. La featured image viene comunque caricata e associata dopo la creazione del post.

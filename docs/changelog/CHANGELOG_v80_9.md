# CHANGELOG v80.9

## v80_9_inline_embed_and_career_status_guardrail

- Parte dalla v80.8.
- Fix Tiffany/Paige: i link social/video dentro una frase normale non vengono più promossi a blocchi embed autonomi.
- Gli oEmbed restano attivi per veri embed standalone: iframe, blockquote social, amp-twitter/amp-instagram, paragrafi composti solo da URL o wrapper tipo "view this post".
- Aggiunto guardrail semantico per traduzioni sensibili sullo status/carriera:
  - `retirement` -> ritiro/ritirarsi, mai pensione/pensionamento;
  - `released/release` -> licenziamento/svincolo/addio secondo contesto, mai rilascio/rilasciato;
  - `cleared/not cleared` -> autorizzato/non autorizzato a lottare, non "pulito";
  - `status/future/contract/free agent` preservano il senso editoriale senza calchi.
- Il guardrail non usa solo sostituzioni rigide: rileva concetti sensibili nella fonte, protegge il significato nel prompt e, se trova una resa italiana sospetta, fa una repair mirata della singola frase.
- Nessuna modifica a scoring, spoiler, dedupe v80.8, AAA priority, report, pending o review packages.

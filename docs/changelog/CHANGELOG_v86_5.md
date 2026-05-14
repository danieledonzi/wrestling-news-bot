# CHANGELOG v86.5 - True results report gate

## Added
- `v865_is_true_results_report()` per identificare solo report completi reali.
- Cleanup in memoria della history limitato ai veri report di risultati.
- Log `[REPORT v86.5]` per autorizzazione dei report veri.

## Changed
- Il bypass dei vecchi gate v86.4 non vale più per qualunque `report-like`.
- `v864_is_report_like_feed_item()` è ora stretto e delega alla v86.5.
- `v862_is_report_candidate_item()` non considera più report i candidati con chiavi `report:*` broad generate in passato, salvo prova nel titolo/URL.

## Fixed
- Falsi report per backstage update.
- Falsi report per ratings/viewership report.
- Falsi report per news singole post-show o rumor con la parola report.
- Possibile blocco del report NXT da vecchi gate, mantenendo però una conferma WordPress stretta.

## Preserved
- Morning hold v86.2.
- Report-first gate v86.4 per i veri results report.
- Embed engine v86.
- Scoring/cap opinion v68/v70.
- Draft-first publishing v85.

# IMPLEMENTATION_NOTES v86.1

## Version name

`v86_1_scoring_signature_validation_stabilizer`

## Goal

v86.1 is a surgical stabilization patch on top of v86. It is designed to publish valid report/results articles that were falsely suppressed by local history and to correct scoring/signature/validation regressions observed in the first v86 run.

## Files changed

- `bot.py` provided as `bot_v86_1.py`
- `cron.yml` provided as `cron_v86_1.yml`

## Main changes

### 1. Report publication recovery

Local `history.txt` is no longer enough to suppress a report. When a `report_event_key` is present in history, v86.1 checks WordPress first. If WordPress does not confirm the report, the bot removes the local key from in-memory history and continues processing.

Expected log:

```text
[REPORT v86.1] Report key in history ma non confermata su WordPress: report:wwe-nxt-2026-05-12 - provo pubblicazione
```

### 2. Strict AAA boost

The v80.4 AAA major boost now requires a hard AAA anchor in the title or URL. This prevents ordinary WWE status items from being promoted to score 100 only because the body mentions AAA or TripleMania.

### 3. Contextual story signature

`build_story_signature_v71()` is wrapped by a v86.1 contextual signature builder. The new signature uses title-focused entities and action buckets rather than noisy body entities.

Examples:

```text
stable:rey_fenix|frustration|wwe
stable:angel_garza|berto|status|wwe
stable:report_wwe_nxt_2026_05_12
```

### 4. Post-show outcome rescue

Debut/return/attack/win titles that occur during a show are not expired previews. This restores the v68/v70 rule that post-show concrete news can exist alongside full reports.

### 5. Body validation cleanup

Before failing for meta/source-promo text, v86.1 strips removable promo/meta sentences and validates the cleaned body. Thin output still fails.

## New environment variables

```yaml
V86_1_STRICT_AAA_BOOST_ENABLED: "1"
V86_1_CONTEXTUAL_SIGNATURE_ENABLED: "1"
V86_1_REPORT_HISTORY_VERIFY_WP: "1"
V86_1_POSTSHOW_PREVIEW_RESCUE_ENABLED: "1"
V86_1_RELAX_BODY_META_VALIDATION: "1"
```

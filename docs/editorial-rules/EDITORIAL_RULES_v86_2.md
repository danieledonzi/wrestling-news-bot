# EDITORIAL_RULES v86.2

## Morning report rule

Complete reports/results articles are not worked before 06:30 Europe/Rome.

This applies to full-show reports such as:

- WWE NXT Results
- WWE Raw Results
- WWE SmackDown Results
- AEW Dynamite Results
- AEW Collision Results
- TNA Impact Results
- PLE/PPV results reports

Before 06:30, the bot stores the best report candidate in pending. It must not publish it, mark it as published, add it to skipped history, or let a generic event key suppress it.

## Post-show news exception

The morning hold applies only to complete reports. Individual post-show news remains publishable immediately:

- debut during a show;
- title change;
- return;
- attack;
- injury angle;
- major storyline development.

## WordPress report confirmation

A report is already published only if WordPress confirms a real complete report. A single NXT/Raw/SmackDown news item from the same date must not block the full report.

Valid confirmation signals:

- exact `report:*` event key metadata;
- report-looking title;
- show marker;
- date marker;
- Editoriali category where available.

# Scoring System v87.2

No major scoring rewrite in v87.2.

Retained rules:

- True-results reports are protected.
- Opinion/commentary caps remain active.
- Executive/interview/opinion cap remains active.
- Future speculative return-date caps remain active.
- Tier3 opinion/interview below 55 remains blocked.

Operational changes affecting scoring outcome:

- Confirmed report keys avoid repeated WP checks and accidental pending loops.
- Temporary model failures send candidates to pending retry rather than definitive skip.
- Task-specific model routing should reduce failed analysis/translation attempts and stabilize refined score decisions.

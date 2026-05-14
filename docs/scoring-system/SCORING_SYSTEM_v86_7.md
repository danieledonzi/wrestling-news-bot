# Scoring System v86.7

v86.7 does not change the scoring model from v86.6. It changes the gate that decides whether a high-scoring candidate can be processed.

## Retained scoring behavior

- True results reports can bypass normal editorial threshold because they are long-form show reports.
- Future return speculation remains capped by v86.6.
- Post-show outcome rescue remains active, but a rescued item still needs enough score to publish.
- AAA major priority remains restricted by v86.1/v86.5 logic.

## Runtime gate priority

For true results reports:

```text
score high
↓
legacy history/title match?
↓
WordPress strict confirmation?
  yes -> skip
  no  -> process
```

For normal articles:

```text
score high
↓
history/title/semantic match?
↓
skip as before
```

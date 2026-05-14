# Implementation Notes v87.7

## Fatal Gemini auth
`V877FatalGeminiAuthError` is raised when Gemini returns a leaked/revoked key error. The bot finalizes logs/artifacts and exits with code 2. Candidates are not saved as temporary model retry items for this case.

## Report cleanup
If a true-results report is confirmed by WordPress URL or event key, v87.7 writes `confirmed_published_reports`, removes matching pending entries, and skips all alternate sources for that report key.

## Workflow sanitize
Before commit/upload, filenames under `published/`, `published_html_review/`, and `logs/` have invalid artifact characters such as `:` replaced. The workflow uses `git add -f` for logs and artifacts.

## Gemini 3 Flash
The correct model ID is `gemini-3-flash-preview`, not `gemini-3-flash`.

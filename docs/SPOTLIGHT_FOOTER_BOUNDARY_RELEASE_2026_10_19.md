# Standalone Spotlight footer boundary — 2026-10-19

Owner explicitly authorized the correction, PR/review, merge, deployment and VPS tests.
Canonical main/production base: `bd2ff64fe274cae989d256dbe41941bc05925acf`.

## Reproduced cause and narrow correction

The Dominik Mysterio source has six editorial paragraphs. Its first paragraph mentions entering the WWE spotlight. Two legacy footer patterns could match an editorial reference anywhere in a paragraph or any sentence starting with Spotlight. `sanitize_elements` treated that as `footer_start` and stopped processing the remainder. The installed extractor therefore recovered zero editorial characters, and the existing completeness guard correctly placed the URL on source-material HOLD before classification.

Replace only those two Spotlight patterns with one complete-block label recognizer. Supported labels include Spotlight, Spotlight WWE News, Spotlight AEW Videos and colon-separated variants. Additional editorial words prevent recognition as a standalone footer. Other footer/bio/CTA filters, source selectors, completeness thresholds, media traversal, Gemini routing, classification/duplicate/pool rules, report handling and permanent decisions are unchanged.

## Verification and release obligations

- Twenty-six new regression cases cover the six-paragraph Dominik-shaped source with ordered media, editorial mentions in paragraphs/headings/quotes, and true standalone footer labels. Before the correction seven editorial cases fail; after it all twenty-six pass.
- The combined new and existing editorial-boundary suite passes fifty-two tests locally. The complete suite and the real-source replay must also pass on production Python 3.9 before release.
- Live diagnostic replay on the base already established zero recovered characters versus all six paragraphs and 1,860 characters when the offending rule alone was disabled in memory. This is extraction evidence, not a classification or publication decision.
- Validate the actual corrected implementation against the same Dominik HTML and two control articles (Cole/WrestlingInc and Rizzo/Ringside); controls must retain their exact ordered clean elements. No provider call or WordPress write is needed for verification.
- Deploy under the producer lock, verify the reviewed tree and compiled files, preserve runtime state and existing final duplicate-cache identity, and check the active scheduled timer.

Do not delete the existing HOLD, alter its retry deadline, force classification or force publication. The next ordinary eligible retry owns recovery and any editorial decision. No new general extraction fallback or weaker completeness threshold is introduced.

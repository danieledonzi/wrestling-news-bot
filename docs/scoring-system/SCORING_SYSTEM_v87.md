# SCORING SYSTEM v87

## Model routing

- Default lite: `gemini-3.1-flash-lite`, poi `gemini-2.5-flash-lite`.
- Strong/report: `gemini-2.5-flash`, poi `gemini-3.1-flash-lite`, poi `gemini-2.5-flash-lite`.

## Tier3 opinion guard

Quando `score < 55` e il pezzo è opinion/interview/commentary senza fatto concreto nuovo, il tier diventa `skip`.

## Continuità

La v87 mantiene:

- cap executive/interview v86.8;
- commentary cap v86.9;
- true-results report priority;
- report source recovery.

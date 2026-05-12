# OpenWrestlingTV Bot v71

## Version Name
`v71_semantic_guardrails_gemini31`

---

# Obiettivi principali della v71

La v71 introduce una nuova generazione della pipeline editoriale automatica con focus su:

1. Riduzione drastica dei duplicati semantici.
2. Migliore distinzione tra breaking news reali e rewrite inutili.
3. Migliore qualità editoriale percepita.
4. Maggiore stabilità della pending queue.
5. Hardening contro titoli clickbait o traduzioni troppo aggressive.
6. Introduzione supporto Gemini 3.1.
7. Ottimizzazione del consumo token.
8. Miglior controllo delle quote originali.

---

# Upgrade Gemini 3.1

## Situazione attuale
La v70 utilizza:

```python
MODEL_CHAIN = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
```

## Nuova configurazione v71

```python
MODEL_CHAIN = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash",
    "gemini-2.5-flash-lite",
]
```

## Strategia

### Gemini 3.1 Flash Lite
Utilizzato per:
- classificazione categoria
- semantic freshness
- duplicate detection
- title normalization
- quote preservation check

### Gemini 3.1 Flash
Utilizzato per:
- traduzione completa articolo
- riscrittura editoriale
- scoring complesso
- editorial enrichment

### Fallback 2.5
Rimane come fallback di compatibilità.

---

# Semantic Duplicate Engine v71

## Problema attuale

Molti siti wrestling pubblicano:
- stessa notizia
- stessi dettagli
- wording diverso
- titoli differenti

La v70 riduce solo parzialmente il problema.

---

## Nuovo sistema: STORY_SIGNATURE_V71

### Pipeline

1. Estrazione entità principali:
   - wrestler
   - promotion
   - evento
   - azione
   - outcome

2. Normalizzazione semantica.

3. Creazione fingerprint narrativa.

---

## Esempio

### Titolo A
"Roman Reigns expected back before SummerSlam"

### Titolo B
"Update on Roman Reigns WWE return plans"

### Story signature

```python
roman_reigns|return|wwe|summerslam
```

Entrambe diventano stessa story.

---

# Nuova funzione

```python
def build_story_signature_v71(title, text):
```

Output:

```python
{
    "entities": [...],
    "topics": [...],
    "action": "return",
    "signature": "roman_reigns|return|wwe|summerslam"
}
```

---

# Rewrite Suppression Engine

## Nuovo problema affrontato

Molti feed producono:

- stesso articolo
- 20 minuti dopo
- 2 dettagli in più
- stesso contenuto editoriale

La v71 introduce:

```python
MIN_SEMANTIC_DISTANCE_FOR_REWRITE = 0.28
```

Se la distanza semantica è troppo bassa:

```python
status = "rewrite_duplicate"
```

L'articolo viene scartato.

---

# Freshness Scoring v71

## Problema v70

Le news molto recenti ma poco informative a volte passano.

## Nuovo modello

### Score composito

```python
freshness_score = (
    time_weight * 0.30 +
    novelty_weight * 0.35 +
    source_uniqueness * 0.20 +
    semantic_delta * 0.15
)
```

---

# Nuova semantica “novità reale”

Gemini 3.1 valuta:

- è davvero un aggiornamento?
- aggiunge informazioni?
- cambia il contesto?
- cambia outcome?
- introduce quote?

---

# Anti Clickbait Layer

## Nuovo filtro

Blocca:

- "Huge Update"
- "Massive News"
- "You Won't Believe"
- titoli con troppe maiuscole
- titoli con troppe emozioni

---

## Funzione

```python
def validate_title_quality_v71(title):
```

Restituisce:

```python
{
    "score": 91,
    "is_clickbait": False,
    "issues": []
}
```

---

# Quote Preservation Engine

## Obiettivo

Le citazioni devono rimanere:

- fedeli
- non parafrasate
- semanticamente equivalenti

---

## Nuova pipeline

1. Estrazione quote originali.
2. Match quote tradotte.
3. Similarity check.
4. Rejection se troppo alterate.

---

## Configurazione

```python
QUOTE_MIN_SIMILARITY = 0.88
```

---

# Pending Queue Hardening

## Problema attuale

Pending queue vulnerabile a:

- loop
- retry eterni
- articoli zombie
- duplicate pending

---

## v71 introduce

### TTL dinamico

```python
PENDING_MAX_AGE_HOURS = 18
```

---

### Retry escalation

```python
MAX_PENDING_RETRY = 3
```

---

### Auto purge

Articoli pending troppo vecchi:

```python
status = "expired_pending"
```

---

# Editorial Tier Improvements

## Nuovo Tier 0

Per:
- rumor inutili
- micro update
- notizie ridondanti

Vengono automaticamente scartati.

---

## Nuovo Tier 5

Per:
- acquisizioni
- grossi ritorni
- morti
- partnership
- numeri business importanti

Questi bypassano quasi tutti i rate limiter.

---

# Business Detection v71

Migliorata la categoria BUSINESS.

Gemini 3.1 riconosce:

- TV rights
- ratings
- mergers
- acquisitions
- TKO
- Endeavor
- attendance
- sponsorship
- Netflix
- licensing

---

# Internal Image Guardrails

## Problema

Alcuni articoli embed:
- immagini interne
- tracking image
- social placeholders

---

## v71

Nuova whitelist:

```python
VALID_IMAGE_MIN_WIDTH = 480
VALID_IMAGE_MIN_HEIGHT = 270
```

Scarta:
- sprite
- emoji
- gif tracking
- placeholder social

---

# Semantic Cooldown

## Nuovo sistema

Se una story viene pubblicata:

```python
STORY_COOLDOWN_MINUTES = 90
```

Nuovi articoli troppo simili vengono bloccati.

---

# Source Reliability Weight

## Nuovo peso fonti

```python
SOURCE_RELIABILITY = {
    "fightful": 1.00,
    "pwinsider": 0.95,
    "wrestlinginc": 0.80,
    "ringsidenews": 0.65,
}
```

---

# Feed Expansion Ready

La v71 prepara supporto futuro per:

- Fightful
- PWInsider
- WrestleVotes
- Observer

senza rompere il dedupe.

---

# Performance Optimization

## Riduzione token Gemini

Nuova pipeline:

1. prefilter locale
2. semantic lightweight pass
3. Gemini solo se necessario

---

## Obiettivo

Riduzione consumo token:

```python
-22% / -35%
```

stimato rispetto v70.

---

# Nuove Costanti v71

```python
SEMANTIC_DUPLICATE_THRESHOLD = 0.82
MIN_SEMANTIC_DISTANCE_FOR_REWRITE = 0.28
QUOTE_MIN_SIMILARITY = 0.88
STORY_COOLDOWN_MINUTES = 90
PENDING_MAX_AGE_HOURS = 18
MAX_PENDING_RETRY = 3
VALID_IMAGE_MIN_WIDTH = 480
VALID_IMAGE_MIN_HEIGHT = 270
```

---

# Nuove funzioni principali

```python
build_story_signature_v71()
semantic_duplicate_check_v71()
validate_title_quality_v71()
validate_quote_preservation_v71()
compute_freshness_score_v71()
cleanup_pending_queue_v71()
should_publish_story_v71()
```

---

# Strategia consigliata di rollout

## Step 1
Deploy shadow mode:

```python
V71_SHADOW_MODE = True
```

Confronta:
- publish rate
- duplicate suppression
- token usage

---

## Step 2
Attiva solo:
- semantic duplicate
- cooldown
- anti clickbait

---

## Step 3
Attiva pipeline completa Gemini 3.1.

---

# Rischi compatibilità

## Gemini 3.1

Possibili differenze:
- JSON più verbose
- quote escaping differente
- maggiore creatività titoli

Per questo:

```python
STRICT_JSON_VALIDATION = True
```

---

# Risultato atteso

## v70

- molte news simili
- qualche rewrite ridondante
- pending queue sporca
- qualità variabile

---

## v71

- feed più pulito
- meno spam
- più qualità percepita
- meno duplicati
- meno clickbait
- maggiore identità editoriale
- migliore efficienza economica



# bot_v49.py
# Enhancements:
# - Strong prompt with fact-preservation instructions
# - Extraction of protected facts (events, names, dates)
# - Validation comparing source vs generated facts
# - Lightweight repair for numeric/name mismatches

import re
from typing import List, Dict

PROMPT_TEMPLATE = """
Traduci integralmente il seguente articolo in italiano.

REGOLE OBBLIGATORIE (CRITICHE):

1. NON modificare nomi propri, eventi o numeri.
   Esempi:
   - "WrestleMania 42" deve rimanere "WrestleMania 42"
   - "Ricky Saints" deve rimanere "Ricky Saints"
   - Date, numeri e titoli NON devono essere alterati

2. NON inferire o correggere:
   - Se il testo dice "WrestleMania 42", NON sostituire con altri numeri
   - NON fare assunzioni o correzioni

3. Mantieni TUTTE le citazioni tra virgolette IDENTICHE nel contenuto (solo tradotte)

4. Mantieni il significato originale senza aggiungere o rimuovere informazioni

5. Se non sei sicuro di un nome o numero, COPIALO ESATTAMENTE dal testo originale

6. NON sintetizzare

7. Produci almeno 300 parole

PRIMA DI TRADURRE:
- Identifica eventi, nomi propri e date
- Mantienili IDENTICI nella traduzione

OUTPUT:
- Italiano fluido
- Nessuna aggiunta o interpretazione
"""

PROTECTED_PATTERNS = [
    r"WrestleMania\s+\d+",
    r"SummerSlam\s+\d+",
    r"Royal Rumble\s+\d+",
    r"Money in the Bank\s+\d+",
    r"Backlash\s+\d+",
    r"Saturday Night'?s Main Event",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
]

def extract_protected_facts(text: str) -> List[str]:
    facts = []
    for pattern in PROTECTED_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        facts.extend(matches)
    return list(set(facts))

def validate_facts(source: str, generated: str) -> Dict:
    source_facts = extract_protected_facts(source)
    generated_facts = extract_protected_facts(generated)

    issues = []
    for sf in source_facts:
        if sf not in generated_facts:
            issues.append(sf)

    return {
        "valid": len(issues) == 0,
        "missing_facts": issues
    }

def repair_generated_text(source: str, generated: str) -> str:
    source_facts = extract_protected_facts(source)
    for fact in source_facts:
        # Try to replace incorrect variants (same event different number)
        base = re.sub(r"\s+\d+", "", fact)
        pattern = base + r"\s+\d+"
        generated = re.sub(pattern, fact, generated, flags=re.IGNORECASE)
    return generated

# Example usage (to integrate in main bot pipeline):
def process_translation(source_text: str, generated_text: str):
    validation = validate_facts(source_text, generated_text)
    if not validation["valid"]:
        generated_text = repair_generated_text(source_text, generated_text)
        validation = validate_facts(source_text, generated_text)
    return generated_text, validation

if __name__ == "__main__":
    print("bot_v49 ready")

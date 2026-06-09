from pathlib import Path

# -----------------------------------------------------------------------------
# v92 Business boundary patch.
# Problem: Business detection used plain substring matching. Terms such as
# "parent" can match inside words like "apparent/apparently", forcing unrelated
# WWE storyline items into Business. Use word-boundary regexes and only concrete
# corporate phrases.
#
# v93.43 note:
# In the split v93 source, this legacy v92 anchor can legitimately be absent
# because the patched behavior has already moved/consolidated elsewhere. During
# one-shot source consolidation this script must be idempotent and non-fatal: if
# the legacy block is not present, leave the source untouched and exit 0.
# -----------------------------------------------------------------------------

bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_BUSINESS_BOUNDARY_PATCH_ACTIVE = True" not in text:
    text = text.replace(
        "V92_NEWS_QUALITY_GUARDRAILS_ACTIVE = True\n",
        "V92_NEWS_QUALITY_GUARDRAILS_ACTIVE = True\nV92_BUSINESS_BOUNDARY_PATCH_ACTIVE = True\n",
        1,
    )

start = text.find("def has_business_signal(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:")
end = text.find("\n\ndef is_ple_card_item", start)
if start == -1 or end == -1:
    bot_path.write_text(text, encoding="utf-8")
    print("[V92 BUSINESS BOUNDARY] has_business_signal block non trovato; sorgente gia consolidato o funzione legacy assente")
    raise SystemExit(0)

new_func = r'''def has_business_signal(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{(analysis or {}).get('editorial_notes', '')} {(analysis or {}).get('news_action', '')} {(analysis or {}).get('story_core', '')}"
    )
    # Business means corporate/economic/distribution context only.
    # Use word-boundary regexes: never match fragments such as parent in apparent.
    corporate_patterns = [
        r"\bownership\b",
        r"\bowner\b",
        r"\bowned\s+by\b",
        r"\bparent\s+company\b",
        r"\bacquisition\b",
        r"\bacquires\b",
        r"\bacquired\b",
        r"\bsale\b",
        r"\bsold\b",
        r"\bbuyer\b",
        r"\bmerger\b",
        r"\bshareholder\b",
        r"\bstake\b",
        r"\binvestment\b",
        r"\binvestor\b",
        r"\brevenue\b",
        r"\bfinancial\b",
        r"\bmedia\s+rights\b",
        r"\btv\s+deal\b",
        r"\bbroadcast\s+deal\b",
        r"\bstreaming\s+deal\b",
        r"\brights\s+deal\b",
        r"\bdistribution\s+deal\b",
        r"\btelevision\s+deal\b",
        r"\bnetflix\b",
        r"\bespn\b",
        r"\bfox\s+deal\b",
        r"\bwarner\s+bros\s+discovery\b",
        r"\bwbd\b",
        r"\bparamount\b",
        r"\bnexstar\b",
        r"\btko\b",
        r"\bcorporate\b",
        r"\bsubsidiary\b",
    ]
    personal_legal_or_medical = [
        r"\barrest\b", r"\barrested\b", r"\bbailed\b", r"\bbail\b", r"\bcaution\b",
        r"\bcharged\b", r"\bassault\b", r"\bpanic\s+attack\b", r"\bcollapsed\b",
        r"\binjury\b", r"\binjured\b", r"\bhospital\b", r"\bemergency\s+room\b",
        r"\bhealth\b", r"\bmedical\b", r"\bmental\s+health\b",
    ]
    if any(re.search(pattern, blob) for pattern in personal_legal_or_medical):
        return False
    return any(re.search(pattern, blob) for pattern in corporate_patterns)
'''

text = text[:start] + new_func + text[end:]
bot_path.write_text(text, encoding="utf-8")
print("[V92 BUSINESS BOUNDARY] has_business_signal regex boundary applicato")

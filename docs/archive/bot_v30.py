def title_soft_validation_failed(title):
    t = sanitize_text(title)
    if not t:
        return True
    if looks_mojibake(t):
        return True
    if t.endswith(":") or t.endswith(" -") or t.endswith(" —"):
        return True
    if len(t) < 8:
        return True

    bad_endings = [
        "è stata",
        "è stato",
        "ha detto",
        "ha spiegato",
        "secondo",
        "dopo",
        "prima di",
        "con",
        "per",
        "su",
        "di",
        "che",
    ]

    low = t.lower().strip(" .,:;!?")
    if any(low.endswith(ending) for ending in bad_endings):
        return True

    return False
from pathlib import Path

MARK = "# v91.5 html integrity and block-safe repair guard"
CODE = r'''

# v91.5 html integrity and block-safe repair guard
BOT_VERSION = "v91_5_html_integrity_block_safe_repair"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_5_ENABLED = os.getenv("V91_5_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_5_BLOCK_FREE_REPAIR = os.getenv("V91_5_BLOCK_FREE_REPAIR", "1").lower() not in {"0", "false", "no", "off"}
V91_5_HTML_GUARD_ENABLED = os.getenv("V91_5_HTML_GUARD_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_5_LISTICLE_HARD_SKIP_ENABLED = os.getenv("V91_5_LISTICLE_HARD_SKIP_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_5_BOLD_MAX_WORDS = int(os.getenv("V91_5_BOLD_MAX_WORDS", "16"))
V91_5_SIMILARITY_THRESHOLD = float(os.getenv("V91_5_SIMILARITY_THRESHOLD", "0.82"))
V91_5_MANUAL_REVIEW_DIR = os.getenv("V91_5_MANUAL_REVIEW_DIR", "manual_review")


def v915_plain_text(html):
    try:
        soup = BeautifulSoup(str(html or ""), "html.parser")
        return soup.get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", str(html or ""))


def v915_norm_text(text):
    text = str(text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9àèéìòùäöüßáíóúñç' ]+", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def v915_tokens(text):
    return [t for t in v915_norm_text(text).split() if len(t) > 2]


def v915_jaccard(a, b):
    sa, sb = set(v915_tokens(a)), set(v915_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def v915_sentences(text):
    plain = v915_plain_text(text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", plain)
    return [p.strip() for p in parts if len(v915_tokens(p)) >= 5]


def v915_is_hard_listicle(title, url="", summary=""):
    raw = f"{title} {url} {summary}".lower()
    patterns = [
        "biggest winners", "biggest losers", "winners and losers", "winners & losers",
        "things we hated", "things we loved", "we hated", "we loved",
        "draws and duds", "draws & duds", "duds and draws", "duds & draws",
        "opinion review", "opinion-review", "ranked", "ranking", "listicle",
        "best and worst", "best & worst",
    ]
    if any(p in raw for p in patterns):
        return True
    if re.search(r"\b\d+\s+things\s+we\s+(hated|loved)\b", raw):
        return True
    return False


def v915_html_integrity_issues(html):
    issues = []
    html = str(html or "")
    if not html.strip():
        issues.append("empty_html")
        return issues
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return [f"html_parse_error:{e}"]

    for tag in soup.find_all(["b", "strong"]):
        txt = tag.get_text(" ", strip=True)
        words = v915_tokens(txt)
        if len(words) > V91_5_BOLD_MAX_WORDS:
            issues.append(f"bold_too_long:{len(words)}")
        if re.search(r"[.!?]", txt) and len(words) > 8:
            issues.append("bold_contains_sentence")
        parent_txt = tag.parent.get_text(" ", strip=True) if tag.parent else ""
        before = parent_txt.split(txt, 1)[0] if txt and txt in parent_txt else ""
        before_tail = " ".join(before.split()[-18:])
        if before_tail and v915_jaccard(before_tail, txt) >= V91_5_SIMILARITY_THRESHOLD:
            issues.append("bold_duplicates_previous_context")

    for p in soup.find_all(["p", "li"]):
        p_html = str(p)
        if re.search(r"\b(.{18,120}?)\s*(?:e|,|\.)\s*<(?:b|strong)>\s*\1", p_html, flags=re.I | re.S):
            issues.append("inline_tag_repeated_prefix")
        sents = v915_sentences(p.get_text(" ", strip=True))
        for i, a in enumerate(sents):
            for b in sents[i+1:i+3]:
                if v915_jaccard(a, b) >= V91_5_SIMILARITY_THRESHOLD:
                    issues.append("near_duplicate_sentences")
                    break
            if "near_duplicate_sentences" in issues:
                break

    plain = v915_plain_text(html)
    if re.search(r"\b([A-ZÀ-Ùa-zà-ù][^.!?]{35,160})\s+\1\b", plain, flags=re.I):
        issues.append("verbatim_duplicate_span")

    # Broken AI repair symptom: an Italian sentence fragment followed by a bold sentence that restarts the same idea.
    if re.search(r"\b(Anche senza|Theory era|Non importa|Sabato|Mentre)\b[^<]{0,160}<\s*(?:b|strong)\s*>\s*\1\b", html, flags=re.I | re.S):
        issues.append("known_repair_injection_pattern")

    return sorted(set(issues))


def v915_find_html_payload(data):
    if isinstance(data, dict):
        preferred = ["content", "contenuto", "html", "body", "article_html", "final_html", "testo", "text"]
        for key in preferred:
            val = data.get(key)
            if isinstance(val, str) and "<p" in val.lower():
                return key, val
        for key, val in data.items():
            if isinstance(val, str) and ("<p" in val.lower() or "<figure" in val.lower() or "<blockquote" in val.lower()):
                return key, val
    return None, ""


def v915_save_manual_review(title, url, html, issues):
    try:
        d = Path(V91_5_MANUAL_REVIEW_DIR)
        d.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", str(title or "article").lower()).strip("-")[:90] or "article"
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base = d / f"{ts}_{slug}_html_integrity"
        (base.with_suffix(".html")).write_text(str(html or ""), encoding="utf-8")
        (base.with_suffix(".json")).write_text(json.dumps({
            "title": title,
            "url": url,
            "issues": issues,
            "version": "v91.5",
            "created_at": datetime.utcnow().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[HTMLGUARD v91.5] Warning salvataggio manual review fallito: {e}")


# Disable free anti-omission repair on final HTML. Keep cleanup functions intact.
if V91_5_ENABLED and V91_5_BLOCK_FREE_REPAIR:
    try:
        _PREV_V915_v81_translation_may_have_omissions = globals().get("v81_translation_may_have_omissions")
        def v81_translation_may_have_omissions(*args, **kwargs):
            print("[PRESERVE v91.5] Anti-omissione v81 libero disattivato: uso validator/retry, non innesto HTML")
            return False
    except Exception as e:
        print(f"[PRESERVE v91.5] Warning override omission detector: {e}")
    try:
        _PREV_V915_v81_repair_possible_omissions = globals().get("v81_repair_possible_omissions")
        def v81_repair_possible_omissions(final_html, *args, **kwargs):
            print("[PRESERVE v91.5] Repair v81 libero bypassato: nessun merge sul finale HTML")
            return final_html
    except Exception as e:
        print(f"[PRESERVE v91.5] Warning override omission repair: {e}")


try:
    _PREV_V915_cheap_classifier_v91 = cheap_classifier_v91
    def cheap_classifier_v91(title, url="", summary=""):
        out = _PREV_V915_cheap_classifier_v91(title, url, summary)
        if V91_5_ENABLED and V91_5_LISTICLE_HARD_SKIP_ENABLED and v915_is_hard_listicle(title, url, summary):
            if not isinstance(out, dict):
                out = {}
            out = dict(out)
            out["skip_final"] = True
            out["cheap_score"] = min(int(out.get("cheap_score") or 20), 20)
            reasons = list(out.get("reasons") or [])
            reasons.append("v91_5_hard_skip_listicle_opinion")
            out["reasons"] = sorted(set(reasons))
            print(f"[V91.5 HARD SKIP] listicle/opinion automatico escluso: {title}")
        return out
except Exception as e:
    print(f"[V91.5] Warning cheap classifier override failed: {e}")


try:
    _PREV_V915_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        title = ""
        if isinstance(data, dict):
            title = data.get("titolo") or data.get("title") or data.get("headline") or ""
        if V91_5_ENABLED and V91_5_LISTICLE_HARD_SKIP_ENABLED and v915_is_hard_listicle(title, url, ""):
            print(f"[HTMLGUARD v91.5] Blocco publish listicle/opinion: {title}")
            try:
                if "v9025_record_processed_url" in globals():
                    v9025_record_processed_url(url, title=title, status="rejected", reason="v91_5_hard_skip_listicle_opinion", extra={"event_key": event_key, "semantic_id": sem_id})
            except Exception:
                pass
            return None, {"blocked_by": "v91.5", "reason": "hard_skip_listicle_opinion"}

        key, html = v915_find_html_payload(data)
        if V91_5_ENABLED and V91_5_HTML_GUARD_ENABLED and html:
            issues = v915_html_integrity_issues(html)
            if issues:
                print(f"[HTMLGUARD v91.5] BLOCCO publish per integrita HTML issues={issues} title={title}")
                v915_save_manual_review(title, url, html, issues)
                try:
                    if "v9025_record_processed_url" in globals():
                        v9025_record_processed_url(url, title=title, status="needs_manual_review", reason="v91_5_html_integrity_failed", extra={"issues": issues, "event_key": event_key, "semantic_id": sem_id})
                except Exception as e:
                    print(f"[HTMLGUARD v91.5] Warning processed marker failed: {e}")
                return None, {"blocked_by": "v91.5", "reason": "html_integrity_failed", "issues": issues}
        return _PREV_V915_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
except Exception as e:
    print(f"[V91.5] Warning create_post_without_image guard failed: {e}")

print("[BOOT v91.5] HTML integrity guard + block-safe repair policy attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.5] bot.py gia aggiornato")
        return 0
    if "# v91.4 publish processed and soft pool repair" not in text:
        raise SystemExit("[SOURCE PATCH v91.5] base v91.4 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.5] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.5] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

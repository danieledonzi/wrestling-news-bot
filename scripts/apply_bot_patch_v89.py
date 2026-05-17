from pathlib import Path

PATCH = r'''
# =========================
# v89: editorial report quality, autonomous follow-ups, tail image cleanup
# =========================
BOT_VERSION = "v89_editorial_report_quality"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V89_REPORT_TAIL_IMAGE_CLEANUP_ENABLED = os.getenv("V89_REPORT_TAIL_IMAGE_CLEANUP_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V89_MAJOR_REPORT_FOLLOWUP_OVERRIDE_ENABLED = os.getenv("V89_MAJOR_REPORT_FOLLOWUP_OVERRIDE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V89_SOFT_NEWS_TIGHTENING_ENABLED = os.getenv("V89_SOFT_NEWS_TIGHTENING_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V89_SOFT_SKIP_SCORE_MAX = int(os.getenv("V89_SOFT_SKIP_SCORE_MAX", "64"))

_V89_SOFT_SUBJECTS_PUBLISHED = set()


def v89_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v89_item_text(item=None):
    item = item or {}
    return " ".join(str(x or "") for x in [
        item.get("title", ""), item.get("url", ""), item.get("summary", ""), item.get("description", ""), item.get("semantic_id", ""), item.get("event_key", ""),
        " ".join(item.get("score_reasons", []) if isinstance(item.get("score_reasons"), list) else []),
    ])


def v89_is_major_report_followup(item=None):
    """A report does not swallow SEO/autonomous major developments from the same show."""
    p = v89_probe(v89_item_text(item))
    # Future event / PLE context.
    future_event = bool(re.search(r"\b(clash|wrestlemania|summerslam|royal rumble|survivor series|money in the bank|backlash|all in|all out|double or nothing|forbidden door|supercard of honor|final battle|death before dishonor|slammiversary|bound for glory|ppv|ple|premium live event)\b", p, re.I))
    # Concrete autonomous developments.
    concrete = bool(re.search(r"\b(challenge[sd]?|sfida|challenged|match announced|announced for|official|title match|world title|championship match|main event|rematch|turns?|heel turn|face turn|debut|returns?|ritorno|debutta|injury|infortun|cleared|out of action|signed|contract|release|released|licenzi|new champion|title change)\b", p, re.I))
    # Two or more top names can make a match/angle standalone even if it is also in a report.
    top_names = [
        "rhea ripley", "jade cargill", "cody rhodes", "roman reigns", "john cena", "cm punk", "seth rollins", "tyler black",
        "gunther", "becky lynch", "charlotte flair", "asuka", "bianca belair", "trick williams", "darby allin", "jon moxley",
        "mercedes mone", "mercedes moné", "sasha banks", "kenny omega", "will ospreay", "samoa joe", "swerve strickland",
    ]
    top_hits = sum(1 for n in top_names if n in p)
    if future_event and concrete:
        return True
    if future_event and top_hits >= 2:
        return True
    if concrete and top_hits >= 2 and re.search(r"\b(match|title|championship|sfida|challeng|main event)\b", p, re.I):
        return True
    return False


def v89_soft_subject_key(item=None):
    p = v89_probe(v89_item_text(item))
    names = []
    try:
        if "v8841_find_persons" in globals():
            names = v8841_find_persons(p)
    except Exception:
        names = []
    if names:
        return "+".join(sorted(set(names)))
    m = re.search(r"\b([a-z]+(?:\s+[a-z]+){0,2})\s+(?:recalls|remembers|explains|says|claims|reveals|comments|addresses)\b", p)
    return m.group(1).strip().replace(" ", "_") if m else ""


def v89_is_soft_non_operational(item=None):
    p = v89_probe(v89_item_text(item))
    if v89_is_major_report_followup(item):
        return False
    hard_terms = [
        "debut", "debutta", "returns", "ritorno", "signed", "contract", "injury", "infortun", "released", "licenzi",
        "title change", "new champion", "match announced", "officially announced", "main event", "world title", "championship match",
    ]
    if any(x in p for x in hard_terms):
        return False
    soft_patterns = [
        r"\bmedia training\b", r"\bresponds? to fan\b", r"\bticket sales\b", r"\bviewership\b", r"\bratings\b",
        r"\bschedule reveal video\b", r"\bsays he wants\b", r"\bsays she wants\b", r"\bwould like to\b",
        r"\bexplains why\b", r"\bpodcast\b", r"\binterview\b", r"\brecalls\b", r"\bremembers\b", r"\breflects\b",
        r"\bclaims credit\b", r"\bcriticized for\b", r"\bbacklash\b", r"\bsecurity\b", r"\bpaycheck\b", r"\bsalary\b",
        r"\bnostalgia\b", r"\bthrowback\b", r"\bwhat being said\b", r"\bsudden schedule change\b",
    ]
    return any(re.search(pat, p, re.I) for pat in soft_patterns)


def v89_remove_tail_orphan_report_images_strict(html):
    if not html:
        return html
    out = html
    try:
        tail_source = r"(?=\s*(?:<hr\b|<p>\s*<a[^>]+>\s*<b>\s*FONTE\s*</b>|<div\s+class=[\"']owtv-telegram-cta[\"']))"
        figure = r"<figure\b(?=[^>]*owtv-inline-image)[\s\S]*?</figure>"
        winner = r"(<p>\s*<b>\s*(?:Vincitor(?:e|i|ice|ici)|Winner|Winners|Risultato|Finale)[\s\S]{0,220}?</b>\s*</p>)"
        pattern = re.compile(winner + r"\s*(?:" + figure + r"\s*)+" + tail_source, re.I)
        out2 = pattern.sub(r"\1\n", out)
        if out2 != out:
            removed = len(re.findall(figure, out)) - len(re.findall(figure, out2))
            print(f"[MEDIA v89] Rimosse immagini orfane in coda report dopo winner: {removed}")
            out = out2
        empty_tail = re.compile(r"(?:\s*<figure\b(?=[^>]*owtv-inline-image)[^>]*>\s*<img\b(?=[^>]*alt=[\"']\s*[\"'])[^>]*>\s*</figure>\s*)+" + tail_source, re.I)
        out3 = empty_tail.sub("\n", out)
        if out3 != out:
            print("[MEDIA v89] Rimosso blocco finale immagini inline con alt vuoto prima della fonte")
            out = out3
    except Exception as e:
        print(f"[WARN v89] tail orphan report image cleanup failed: {e}")
    return out


# Let v88.4.2 post-report guard keep major autonomous SEO follow-ups.
if V89_MAJOR_REPORT_FOLLOWUP_OVERRIDE_ENABLED and "v8842_soft_after_report_candidate" in globals():
    _ORIG_V89_v8842_soft_after_report_candidate = v8842_soft_after_report_candidate
    def v8842_soft_after_report_candidate(item=None):
        if v89_is_major_report_followup(item):
            print(f"[SEO v89] Report non assorbe sviluppo autonomo forte: {(item or {}).get('title','')}")
            return False
        return _ORIG_V89_v8842_soft_after_report_candidate(item)


if (V89_SOFT_NEWS_TIGHTENING_ENABLED or V89_REPORT_TAIL_IMAGE_CLEANUP_ENABLED) and "process_candidate_item" in globals():
    _ORIG_V89_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title = (item or {}).get("title", "")
            score = int((item or {}).get("score", 0) or 0)
            if V89_SOFT_NEWS_TIGHTENING_ENABLED and v89_is_soft_non_operational(item) and score <= V89_SOFT_SKIP_SCORE_MAX:
                print(f"[SKIP v89] Soft news non operativa sotto {V89_SOFT_SKIP_SCORE_MAX+1}: {title}")
                return "skipped"
            subject = v89_soft_subject_key(item)
            if V89_SOFT_NEWS_TIGHTENING_ENABLED and subject and subject in _V89_SOFT_SUBJECTS_PUBLISHED and v89_is_soft_non_operational(item):
                print(f"[SKIP v89] Seconda soft/intervista stesso soggetto nella run: {subject} - {title}")
                return "skipped"
        except Exception as e:
            print(f"[WARN v89] soft tightening pre-check warning: {e}")
        result = _ORIG_V89_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        try:
            if "v8841_is_publish_success" in globals() and v8841_is_publish_success(result) and v89_is_soft_non_operational(item):
                subject = v89_soft_subject_key(item)
                if subject:
                    _V89_SOFT_SUBJECTS_PUBLISHED.add(subject)
        except Exception:
            pass
        return result


if V89_REPORT_TAIL_IMAGE_CLEANUP_ENABLED and "create_post_without_image" in globals():
    _ORIG_V89_create_post_without_image = create_post_without_image

    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        try:
            is_report = (
                isinstance(data, dict)
                and "v8842_is_true_results_report" in globals()
                and v8842_is_true_results_report(
                    sem_id=sem_id,
                    event_key=event_key,
                    title=data.get("titolo") or data.get("title") or "",
                    url=url,
                    data=data,
                )
            )

            if is_report:
                data = dict(data)
                data["testo"] = v89_remove_tail_orphan_report_images_strict(data.get("testo", ""))

                if inline_images:
                    try:
                        n = len(inline_images)
                    except Exception:
                        n = "unknown"
                    print(f"[MEDIA v89] Report: inline_images residue non passate al publisher: {n}")
                    inline_images = []

        except Exception as e:
            print(f"[WARN v89] report tail cleanup wrapper warning: {e}")

        return _ORIG_V89_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )

try:
    print("[BOOT v89] Editorial quality attiva: report tail cleanup, follow-up SEO override, soft-news tightening")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v89: editorial report quality" in text:
        print("[SOURCE PATCH v89] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v89] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)

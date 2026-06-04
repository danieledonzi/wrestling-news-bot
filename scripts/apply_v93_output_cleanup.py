from pathlib import Path

# Bob: only source blockquote tags become quote blocks. Quotation marks inside normal
# paragraphs must remain normal text to avoid false blockquote styling.
bob = Path('agents/bob.py')
text = bob.read_text(encoding='utf-8')
if 'v93_26_source_blockquotes_only' not in text:
    text = text.replace('BOB_VERSION = "v93_12_prudent_embed_cleanup"', 'BOB_VERSION = "v93_26_source_blockquotes_only"')
    old = '''        if is_probable_long_quote(text):
            return {"type": "quote", "text": text, "source_tag": name}
        return {"type": "text", "text": text}
'''
    new = '''        # v93.26: do not infer quote blocks from quotation marks in normal paragraphs.
        # Only original source <blockquote> nodes are rendered as blockquotes.
        return {"type": "text", "text": text}
'''
    if old not in text:
        raise SystemExit('[V93 OUTPUT CLEANUP] Bob quote anchor non trovato')
    text = text.replace(old, new, 1)
    text = text.replace('"preserve_quotes_as_blockquote": True,', '"preserve_quotes_as_blockquote": "source_blockquote_only",')
    bob.write_text(text, encoding='utf-8')
    print('[V93 OUTPUT CLEANUP] Bob source blockquotes only applicato')
else:
    print('[V93 OUTPUT CLEANUP] Bob gia applicato')

# Publisher: split paragraph-wrapped social/video URLs even when followed by text,
# convert them to Gutenberg embed blocks, add spacing after URLs/blocks, and remove
# duplicate trailing embed URLs while preserving the first occurrence.
pub = Path('agents/publisher_policy_v93_16.py')
text = pub.read_text(encoding='utf-8')
if 'v93_26_publisher_embed_cleanup' not in text:
    text = text.replace('VERSION = "v93_23_publisher_paragraph_embed_blocks"', 'VERSION = "v93_26_publisher_embed_cleanup"')
    text = text.replace(
        'P_START_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*(?:<br\\s*/?>|\\n|\\r\\n)+\\s*(.*?)</p>", re.I | re.S)\n',
        'P_START_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*(?:<br\\s*/?>|\\n|\\r\\n)+\\s*(.*?)</p>", re.I | re.S)\nP_URL_THEN_TEXT_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s+([^<].*?)</p>", re.I | re.S)\nWP_EMBED_BLOCK_RE = re.compile(r"<!-- wp:embed [\\s\\S]*?<!-- /wp:embed -->", re.I)\nEMBED_URL_ANY_RE = re.compile(rf"({EMBED_URL_PATTERN})", re.I)\n'
    )
    anchor = '''def convert_plain_embed_urls_to_blocks(content: str) -> str:
    text = content or ""

    def repl_p_start(match: re.Match[str]) -> str:
        url = clean_url(match.group(1))
        rest = (match.group(2) or "").strip()
        block = "\n" + gutenberg_embed_block(url) + "\n"
        if rest:
            return block + f"\n<p>{rest}</p>"
        return block

    def repl_p_only(match: re.Match[str]) -> str:
        return "\n" + gutenberg_embed_block(match.group(1)) + "\n"

    def repl_line(match: re.Match[str]) -> str:
        return "\n" + gutenberg_embed_block(match.group(1)) + "\n"

    # First handle WordPress-cleaned paragraphs such as <p>URL<br>next sentence</p>.
    text = P_START_EMBED_RE.sub(repl_p_start, text)
    text = P_ONLY_EMBED_RE.sub(repl_p_only, text)
    text = EMBED_LINE_RE.sub(repl_line, text)
    return text
'''
    replacement = '''def normalize_embed_key(url: str) -> str:
    url = clean_url(url)
    url = re.sub(r"[?&]feature=oembed\\b", "", url, flags=re.I)
    url = re.sub(r"[?&]utm_[^&]+", "", url, flags=re.I)
    url = url.replace("?&", "?").rstrip("?&")
    return url.rstrip("/").lower()


def remove_duplicate_embed_urls_preserve_first(text: str) -> str:
    seen: set[str] = set()

    def block_repl(match: re.Match[str]) -> str:
        block = match.group(0)
        found = EMBED_URL_ANY_RE.search(block)
        if not found:
            return block
        key = normalize_embed_key(found.group(1))
        if key in seen:
            return ""
        seen.add(key)
        return block

    text = WP_EMBED_BLOCK_RE.sub(block_repl, text)

    def p_repl(match: re.Match[str]) -> str:
        key = normalize_embed_key(match.group(1))
        if key in seen:
            return ""
        seen.add(key)
        return match.group(0)

    text = P_ONLY_EMBED_RE.sub(p_repl, text)
    return text


def convert_plain_embed_urls_to_blocks(content: str) -> str:
    text = content or ""

    def repl_p_start(match: re.Match[str]) -> str:
        url = clean_url(match.group(1))
        rest = (match.group(2) or "").strip()
        block = "\n\n" + gutenberg_embed_block(url) + "\n\n"
        if rest:
            return block + f"<p>{rest}</p>"
        return block

    def repl_p_only(match: re.Match[str]) -> str:
        return "\n\n" + gutenberg_embed_block(match.group(1)) + "\n\n"

    def repl_line(match: re.Match[str]) -> str:
        return "\n\n" + gutenberg_embed_block(match.group(1)) + "\n\n"

    text = P_START_EMBED_RE.sub(repl_p_start, text)
    text = P_URL_THEN_TEXT_RE.sub(repl_p_start, text)
    text = P_ONLY_EMBED_RE.sub(repl_p_only, text)
    text = EMBED_LINE_RE.sub(repl_line, text)
    text = remove_duplicate_embed_urls_preserve_first(text)
    text = re.sub(r"(<!-- /wp:embed -->)\\s*(<p>)", r"\\1\n\n\\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
'''
    if anchor not in text:
        raise SystemExit('[V93 OUTPUT CLEANUP] Publisher convert anchor non trovato')
    text = text.replace(anchor, replacement, 1)
    text = text.replace('result.setdefault("policy", {})["paragraph_wrapped_social_urls_rendered_as_gutenberg_embed_blocks"] = True', 'result.setdefault("policy", {})["paragraph_wrapped_social_urls_rendered_as_gutenberg_embed_blocks"] = True\n    result.setdefault("policy", {})["duplicate_trailing_embed_urls_removed_preserve_first"] = True\n    result.setdefault("policy", {})["post_embed_spacing_enforced"] = True')
    pub.write_text(text, encoding='utf-8')
    print('[V93 OUTPUT CLEANUP] Publisher embed cleanup applicato')
else:
    print('[V93 OUTPUT CLEANUP] Publisher gia applicato')

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.publisher_policy_v93_16 import (
    canonical_embed_key,
    display_embed_url,
    gutenberg_embed_block,
)
from modules.news_workshop_v92 import canonicalize_embed_url

MARKER = "v95_7_1_youtube_embed_case_preservation"
MIXED_ID = "Ao-lugrL_cs"
LOWERED_ID = "ao-lugrl_cs"


def test_youtube_watch_url_preserves_mixed_case_v_parameter():
    final_url = canonicalize_embed_url(f"https://www.youtube.com/watch?v={MIXED_ID}&feature=shared")

    assert final_url == f"https://www.youtube.com/watch?v={MIXED_ID}"
    assert MIXED_ID in final_url
    assert LOWERED_ID not in final_url


def test_youtu_be_short_url_preserves_mixed_case_id():
    final_url = display_embed_url(f"https://youtu.be/{MIXED_ID}?si=abc123")

    assert final_url == f"https://www.youtube.com/watch?v={MIXED_ID}"
    assert MIXED_ID in final_url
    assert LOWERED_ID not in final_url


def test_canonical_embed_key_dedupes_equivalent_youtube_urls_without_lowering_output():
    watch = f"https://www.youtube.com/watch?v={MIXED_ID}"
    short = f"https://youtu.be/{MIXED_ID}"

    assert canonical_embed_key(watch) == canonical_embed_key(short)
    assert display_embed_url(short) == watch
    assert MIXED_ID in display_embed_url(short)
    assert LOWERED_ID not in display_embed_url(short)


def test_gutenberg_embed_block_contains_original_case_video_id():
    block = gutenberg_embed_block(f"https://youtu.be/{MIXED_ID}")

    assert MARKER
    assert f"https://www.youtube.com/watch?v={MIXED_ID}" in block
    assert MIXED_ID in block
    assert LOWERED_ID not in block

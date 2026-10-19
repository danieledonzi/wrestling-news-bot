"""A Spotlight footer label cannot consume substantive article paragraphs."""
import pytest

from agents import bob, source_body


URL = 'https://www.wrestlinginc.com/2288622/wwe-nxt-dominik-mysterio-bypassed-full-run/'
FACT = 'The performer explained the decision, its timing and the professional consequences for his career. '


def extract(content):
    html = ('<html><body><article class="news-post"><div class="news-article">'
            '<div class="columns-holder">' + content + '</div></div></article></body></html>')
    return bob.extract_elements(URL, html)


def test_dominik_intro_preserves_all_six_paragraphs_and_media_order():
    paragraphs = ['Dominik Mysterio entered the WWE spotlight early in his wrestling career.']
    paragraphs += [f'DETAIL_{i}: ' + FACT * 3 for i in range(1, 6)]
    _, _, clean, _, diag = extract(
        '<iframe src="https://www.youtube.com/embed/interview123"></iframe>'
        + ''.join(f'<p>{p}</p>' for p in paragraphs)
        + '<iframe src="https://www.youtube.com/embed/closing12345"></iframe>')
    assert [e['text'] for e in clean if e['type'] == 'text'] == [bob.clean_text(p) for p in paragraphs]
    assert [e['type'] for e in clean] == ['embed'] + ['text'] * 6 + ['embed']
    assert diag['body_complete'] and diag['root_coverage_ratio'] == 1
    assert source_body.valid_contract(source_body.contract_from_elements(URL, clean, diag))


@pytest.mark.parametrize('tag, sentence', [
    ('p', 'The performer moved into the spotlight after the confirmed signing.'),
    ('p', 'Spotlight followed the performer after his successful debut.'),
    ('p', 'The spotlight WWE placed on its new champion changed his schedule.'),
    ('p', 'Spotlight WWE News is the program discussed in this interview.'),
    ('h2', 'Spotlight shifts to the next championship match'),
    ('blockquote', 'The spotlight was important, but the performer still needed time to prepare.'),
])
def test_editorial_spotlight_references_do_not_end_the_body(tag, sentence):
    _, _, clean, _, diag = extract(
        f'<p>{FACT * 3}</p><{tag}>{sentence}</{tag}><p>FINAL_FACT: {FACT * 3}</p>')
    rendered = ' '.join(e.get('text', '') for e in clean)
    assert sentence in rendered and 'FINAL_FACT:' in rendered
    assert diag['body_complete']


@pytest.mark.parametrize('label', [
    'Spotlight', 'SPOTLIGHT', ' Spotlight ', 'Spotlight:', 'Spotlight WWE',
    'Spotlight WWE News', 'Spotlight AEW Videos', 'Spotlight NXT News',
    'Spotlight TNA News', 'Spotlight ROH Videos', 'Spotlight News', 'Spotlight Videos',
    'Spotlight: WWE News', 'Spotlight:WWE News', 'Spotlight WWE News:',
    'About the author', 'Related articles', 'More WWE news',
])
def test_actual_standalone_footer_labels_still_stop_non_editorial_tail(label):
    clean, _ = bob.sanitize_elements([
        {'type': 'text', 'text': FACT * 3}, {'type': 'text', 'text': label},
        {'type': 'text', 'text': 'UNRELATED_RECOMMENDATION: ' + FACT}], '')
    rendered = ' '.join(e.get('text', '') for e in clean)
    assert FACT.strip() in rendered
    assert label.strip() not in rendered and 'UNRELATED_RECOMMENDATION:' not in rendered


def test_source_footer_boundary_still_survives_full_dom_extraction():
    _, _, clean, _, _ = extract(
        f'<p>{FACT * 3}</p><p>Spotlight: WWE Videos</p><p>UNRELATED_RECOMMENDATION: {FACT}</p>')
    rendered = ' '.join(e.get('text', '') for e in clean)
    assert FACT.strip() in rendered and 'UNRELATED_RECOMMENDATION:' not in rendered

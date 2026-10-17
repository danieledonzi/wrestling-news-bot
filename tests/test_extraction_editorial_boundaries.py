"""Retain substantive source text while excluding genuine source boilerplate."""
import json

import pytest
from bs4 import BeautifulSoup

from agents import bob, source_body, menzo_source_material as material

FACT = 'A confirmed professional development includes the participants, the official decision, its timing and its consequences. '


def extract(content, *, chrome=None, after='', article_class='rsn-single-article'):
    if chrome is None:
        chrome = '<header>' + 'Source headline, author and publication date. ' * 6 + '</header>'
    html = (f'<html><body><article class="{article_class}">{chrome}'
            f'<div class="entry-content rsn-single-content">{content}</div>{after}</article></body></html>')
    return html, bob.extract_elements('https://www.ringsidenews.com/source/', html)


def text(elements):
    return ' '.join(e.get('text') or e.get('markdown') or '' for e in elements)


def test_short_editorial_body_is_not_measured_against_unrelated_article_chrome():
    html, (_, _, clean, _, diag) = extract(f'<p>{FACT * 3}</p>',
        chrome=f'<header>{"Source headline, date and navigation. " * 35}</header>',
        after='<aside class="rsn-spotlight">Unrelated recommendations and navigation.</aside>')
    assert diag['body_complete']
    assert diag['root_coverage_ratio'] >= .55
    assert diag['article_container_text_chars'] > diag['root_text_chars']
    assert diag['coverage_root_classes'].startswith('entry-content')
    assert source_body.valid_contract(source_body.contract_from_elements('https://www.ringsidenews.com/source/', clean, diag))


@pytest.mark.parametrize('where', ['inside', 'sibling', 'ancestor'])
def test_narrow_coverage_does_not_hide_an_article_access_wall(where):
    body = f'<p>{FACT * 5}</p>'
    wall = '<div class="paywall">Subscribe to continue reading the remaining content.</div>'
    if where == 'inside':
        _, result = extract(body + wall)
    elif where == 'sibling':
        _, result = extract(body, after=wall)
    else:
        _, result = extract(body, article_class='rsn-single-article subscriber-only')
    assert not result[-1]['body_complete']
    assert 'truncation_or_access_marker' in result[-1]['body_incomplete_reasons']


def test_newsletter_source_citations_are_editorial_text_not_subscription_prompts():
    paragraphs = [
        'According to Dave Meltzer in the Wrestling Observer Newsletter, WWE sources denied involvement in the departure. ' + FACT,
        'Meltzer wrote in the newsletter that key company officials did not know about the decision until afterward. ' + FACT,
    ]
    _, (_, _, clean, _, diag) = extract(''.join(f'<p>{p}</p>' for p in paragraphs))
    assert all(bob.clean_text(p) in text(clean) for p in paragraphs)
    assert diag['body_complete']


@pytest.mark.parametrize('cta', ['Subscribe to our newsletter.', 'Sign up for our newsletter.', 'Join our newsletter.', 'Click here to subscribe.'])
def test_actual_subscription_prompts_still_disappear(cta):
    _, (_, _, clean, _, _) = extract(f'<p>{FACT * 3}</p><p>{cta}</p>')
    assert cta not in text(clean)


def test_following_people_in_an_interview_does_not_remove_intro_or_cut_following_news():
    intro = 'John Cena wants to follow millions of people on X because he values different perspectives. ' + FACT
    quote = '“Because I did not follow anybody on Instagram, I chose to follow people on Twitter and listen to their conversation.”'
    tail = 'FINAL_EDITORIAL_FACT: The platform restricts the number of new accounts he can follow each day. ' + FACT
    _, (_, _, clean, _, diag) = extract(f'<p>{intro}</p><blockquote>{quote}</blockquote><p>{tail}</p>')
    assert all(bob.clean_text(p) in text(clean) for p in (intro, quote, tail))
    assert diag['body_complete']


def test_a_quoted_follow_instruction_is_not_an_author_bio_boundary():
    quote = 'Follow the performers on Twitter and listen to their views before reaching a conclusion about the dispute.'
    _, (_, _, clean, _, _) = extract(f'<p>{FACT * 2}</p><blockquote>{quote}</blockquote><p>FINAL_FACT {FACT}</p>')
    assert quote in text(clean) and 'FINAL_FACT' in text(clean)


@pytest.mark.parametrize('promo', [
    'Ringside News will continue to provide updates as they become available.',
    'Ringside News will have full coverage of the show with match-by-match updates.',
    'Ringside News will provide live, match-by-match coverage as the show unfolds.',
])
def test_mixed_source_promotion_removes_only_the_promotional_sentence(promo):
    before = 'Doctors have not yet confirmed which body part was injured or how serious the injury is. ' + FACT
    after = 'The match was stopped and the performer was taken to a hospital for further evaluation.'
    _, (_, _, clean, _, diag) = extract(f'<p>{before} {promo} {after}</p>')
    assert bob.clean_text(before) in text(clean) and after in text(clean)
    assert promo not in text(clean) and diag['body_complete']


def test_real_author_bio_and_google_cta_still_end_the_editorial_body():
    bio = 'Steve Carrier is the founder of Ringside News and has been reporting on pro wrestling since 1997.'
    _, (_, _, clean, _, _) = extract(f'<p>{FACT * 3}</p><p>{bio}</p><p>Follow Steve Carrier on Twitter.</p><p>Add as a preferred source on Google.</p>')
    assert FACT.strip() in text(clean)
    assert 'Steve Carrier' not in text(clean) and 'preferred source' not in text(clean)


def test_genuinely_partial_extraction_still_fails_without_changing_thresholds():
    html, _ = extract(f'<p>{FACT * 2}</p><p>{FACT * 7}</p>')
    soup = BeautifulSoup(html, 'html.parser')
    diag = bob.assess_body_completeness(soup.article, [{'type': 'text', 'text': FACT * 2}], soup)
    assert not diag['body_complete'] and diag['root_coverage_ratio'] < .55


def test_structural_author_bio_cannot_keep_a_transcript_notice_in_the_body():
    notice = ('This transcript was produced exclusively for Ringside News from the original recording. '
              'When using excerpts, provide prominent credit and a link to this article.')
    bio = 'Derek Holloway is a writer at Ringside News specializing in wrestling news, rumors and results.'
    _, (_, _, clean, _, diag) = extract(f'<p>{FACT * 5}</p><p>{notice}</p>',
        after=f'<section class="rsn-author-box"><div class="rsn-author-bio"><p>{bio}</p></div></section>')
    assert FACT.strip() in text(clean) and diag['body_complete']
    assert notice not in text(clean) and bio not in text(clean)


def test_rejected_source_preserves_bounded_diagnostics_through_hold_and_backoff(monkeypatch):
    html, _ = extract(f'<p>{FACT * 3}</p>', after='<div class="paywall">Unlock this article.</div>')
    monkeypatch.setattr(bob, 'fetch_html', lambda _: html)
    monkeypatch.setattr(material, '_fetch_body', source_body.hydrate)
    row = {'url': 'https://www.ringsidenews.com/source/', 'candidate_id': 'held'}
    first = material.Session({'observation_timestamp': '2026-10-17T15:00:00Z'})
    assert not first.hydrate(row, 'primary_classification')
    result = first.finish()
    details = result['observations'][0]['extraction_diagnostics']
    assert details['body_incomplete_reasons'] == ['truncation_or_access_marker']
    assert details['extracted_text_chars'] > 200 and 'structured_article_body' not in details
    original_deadline = material._read()['holds'][material.key(row)]['retry_after']
    second = material.Session({'observation_timestamp': '2026-10-17T15:05:00Z'})
    assert not second.hydrate(row, 'primary_classification')
    assert second.finish()['observations'][0]['extraction_diagnostics'] == details
    assert material._read()['holds'][material.key(row)]['retry_after'] == original_deadline
    monkeypatch.setattr(material, '_fetch_body', lambda _: (False, 'source_extraction_error:TimeoutError'))
    third = material.Session({'observation_timestamp': '2026-10-17T16:00:00Z'})
    assert not third.hydrate(row, 'primary_classification')
    assert 'extraction_diagnostics' not in third.finish()['observations'][0]
    assert 'extraction_diagnostics' not in material._read()['holds'][material.key(row)]

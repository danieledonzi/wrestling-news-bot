from __future__ import annotations
import pytest
from modules import report_workshop_v92 as report

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 2048
URL = "https://www.ringsidenews.com/wp-content/smush-avif/2026/11/wwe-smackdown-spoiler-results-768x1024.png.avif?x55711"


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    report.media_cache.clear()
    monkeypatch.setattr(report, "MEDIA_UPLOAD_FAILURES", 0)
    monkeypatch.setattr(report, "MEDIA_UPLOAD_DISABLED", False)
    yield
    report.media_cache.clear()


def mock_upload(monkeypatch, content_type, payload):
    calls = []
    class Image:
        headers = {"Content-Type": content_type}
        content = payload
        status_code = 200
        def raise_for_status(self):
            pass
    class WPResponse:
        status_code = 201
        def json(self):
            return {"id": 987, "source_url": "https://news.openwrestlingtv.com/wp-content/uploads/2026/11/smackdown.png"}
    monkeypatch.setattr(report.session, "get", lambda *args, **kwargs: Image())
    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return WPResponse()
    monkeypatch.setattr(report, "wp_request_with_retry", fake_request, raising=False)
    return calls


def test_octet_stream_genuine_png_uploads_with_correct_mime_and_extension(monkeypatch):
    calls = mock_upload(monkeypatch, "application/octet-stream", PNG)
    mid, url = report.upload_media(URL)
    assert mid == 987
    assert url.endswith("/smackdown.png")
    assert len(calls) == 1
    _, _, kwargs = calls[0]
    assert kwargs["headers"]["Content-Type"] == "image/png"
    assert kwargs["headers"]["Content-Disposition"].endswith('.png"')
    assert kwargs["data"] == PNG
    assert report.upload_media(URL) == (mid, url)
    assert len(calls) == 1  # valid successful cache


@pytest.mark.parametrize("mime,payload", [
    ("application/octet-stream", b"<html>not an image</html>"),
    ("application/octet-stream", b"RIFF" + b"x" * 4096),
    ("text/html", PNG),
    ("application/json", b'{"status":"ok"}'),
])
def test_unknown_or_untrusted_image_format_is_not_sent_to_wordpress(monkeypatch, mime, payload):
    calls = mock_upload(monkeypatch, mime, payload)
    assert report.upload_media(URL) == (None, None)
    assert calls == []


def test_normal_image_png_upload_unchanged(monkeypatch):
    calls = mock_upload(monkeypatch, "image/png", PNG)
    assert report.upload_media(URL)[0] == 987
    assert calls[0][2]["headers"]["Content-Type"] == "image/png"


def test_missing_inline_image_still_blocks_report(monkeypatch):
    monkeypatch.setattr(report, "upload_media", lambda image_url: (None, None))
    blocks = [{"type":"image", "src": URL, "alt": "SmackDown"}]
    with pytest.raises(ValueError, match="Report image upload failed"):
        report.render_blocks(blocks, {}, featured_image_url=None)

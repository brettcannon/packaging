import json
import textwrap

import pytest

from packaging import index


class TestParseList:
    def test_invalid_content_type(self) -> None:
        with pytest.raises(index.InvalidContentType):
            index.parse_list("invalid/content-type", "")

    @pytest.mark.parametrize(
        "content_type", [*index._ACCEPT_HTML_VALUES, "text/html; charset=utf-8"]
    )
    def test_html_content_type(self, content_type: str) -> None:
        html_spec_example = textwrap.dedent("""
            <!DOCTYPE html>
            <html>
            <body>
                <a href="/frob/">frob</a>
                <a href="/spamspamspam/">spamspamspam</a>
            </body>
            </html>
            """)
        result = index.parse_list(content_type, html_spec_example)
        expect = {
            "meta": {"api-version": "1.0"},
            "projects": [{"name": "frob"}, {"name": "spamspamspam"}],
        }
        assert result == expect

    def test_json_content_type(self) -> None:
        expect = {
            "meta": {"api-version": "1.0"},
            "projects": [{"name": "frob"}, {"name": "spamspamspam"}],
        }
        result = index.parse_list(index.ACCEPT_JSON_V1, json.dumps(expect))
        assert result == expect

    def test_canonical_names_json(self) -> None:
        given = {
            "meta": {"api-version": "1.0"},
            "projects": [{"name": "Frob"}, {"name": "Spam_Spam_spam"}],
        }
        expect = {
            "meta": {"api-version": "1.0"},
            "projects": [{"name": "frob"}, {"name": "spam-spam-spam"}],
        }
        result = index.parse_list(index.ACCEPT_JSON_V1, json.dumps(given))
        assert result == expect

    def test_canonical_names_html(self) -> None:
        html = (
            '<html><body><a href="/Frob/">Frob</a>'
            '<a href="/Spam_Spam_spam/">Spam_Spam_spam</a></body></html>'
        )
        expect = {
            "meta": {"api-version": "1.0"},
            "projects": [{"name": "frob"}, {"name": "spam-spam-spam"}],
        }
        result = index.parse_list("text/html", html)
        assert result == expect

    @pytest.mark.parametrize(
        ("meta_tag", "api_version"),
        [
            ('<meta name="pypi:repository-version" content="1.4"></meta>', "1.4"),
            ('<meta name="pypi:repository-version" content="1.4">', "1.4"),
            ('<meta name="pypi:repository-version" content="1.4" />', "1.4"),
            ('<meta content="1.4" ></meta>', "1.0"),
            ('<meta name="pypi:repository-version"></meta', "1.0"),
        ],
    )
    def test_html_api_version(self, meta_tag: str, api_version: str) -> None:
        html = textwrap.dedent(f"""
            <!DOCTYPE html>
            <html>
            <head>
                {meta_tag}
            </head>
            <body>
                <a href="/frob/">frob</a>
                <a href="/spamspamspam/">spamspamspam</a>
            </body>
            </html>
            """)
        expect = {
            "meta": {"api-version": api_version},
            "projects": [{"name": "frob"}, {"name": "spamspamspam"}],
        }
        result = index.parse_list(index._ACCEPT_HTML_VALUES[0], html)
        assert result == expect

"""
The translations in these tests are real outputs from Google Cloud Translation for
the encoded messages.
"""

import pytest

from autotranslate.protect.guards import HTMLGuard, TokenGuard
from autotranslate.protect.pipeline import protect, restore


def span(id_, text):
    return f'<span translate="no" id="{id_}">{text}</span>'


HTML = HTMLGuard()
TOKEN = TokenGuard()


def test_html_encode():
    protected = protect(
        'Read the <a href="%(url)s">docs</a> & %(n)d\nnow', HTML, ["python-format"]
    )
    assert protected.encoded == (
        'Read the <span id="0">docs</span> &amp; '
        '<span translate="no" id="1">%(n)d</span><br translate="no" id="2">now'
    )


def test_token_encode():
    assert (
        protect("100%% of %(n)d", TOKEN, ["python-format"]).encoded
        == "100__x0__ of __n__"
    )
    assert (
        protect("Saved %s %s", TOKEN, ["python-format"]).encoded
        == "Saved __item__ __item__"
    )


@pytest.mark.parametrize(
    "source, flags, translation, expected",
    [
        ("Saved %s", ["python-format"], "Salvo " + span(0, "%s"), "Salvo %s"),
        # a space dropped between a word and a placeholder is restored
        (
            "Saved %s",
            ["python-format"],
            'Salvo<span translate="no" id="0"></span>',
            "Salvo %s",
        ),
        # spaces added between placeholders and punctuation are removed
        (
            "Skipping {file}: {service} does not support `{language}`",
            ["python-brace-format"],
            f"Bỏ qua {span(0, '{file}')} : {span(1, '{service}')} không hỗ trợ ` {span(2, '{language}')} `",
            "Bỏ qua {file}: {service} không hỗ trợ `{language}`",
        ),
        (
            "`{service}` requires the `{package}` package.",
            ["python-brace-format"],
            f"` {span(0, '{service}')} ` ئۈچۈن ` {span(1, '{package}')} ` پاكېت تەلەپ قىلىنىدۇ.",
            "`{service}` ئۈچۈن `{package}` پاكېت تەلەپ قىلىنىدۇ.",
        ),
        (
            "Hello %(name)s, you have %(count)d new messages.",
            ["python-format"],
            f"Hallo {span(0, '%(name)s')} , du hast {span(1, '%(count)d')} neue Nachrichten.",
            "Hallo %(name)s, du hast %(count)d neue Nachrichten.",
        ),
        # no spaces are added in scripts written without them
        (
            "Hello %(name)s, you have %(count)d new messages.",
            ["python-format"],
            f"こんにちは{span(0, '%(name)s')} 。 {span(1, '%(count)d')}新しいメッセージが届きました。",
            "こんにちは%(name)s。 %(count)d新しいメッセージが届きました。",
        ),
        # newlines survive and the space added after them is removed
        (
            "First line\nSecond line",
            [],
            'Erste Zeile<br translate="no" id="0"> Zweite Zeile',
            "Erste Zeile\nZweite Zeile",
        ),
        (
            "Line one \n  indented",
            [],
            'Zeile eins <br translate="no" id="0">  eingerückt',
            "Zeile eins \n  eingerückt",
        ),
        # paired markup is restored around its translated content
        (
            'Read the <a href="%(url)s">docs</a> & more',
            ["python-format"],
            'Lesen Sie die <span id="0">Dokumentation</span> &amp; mehr',
            'Lesen Sie die <a href="%(url)s">Dokumentation</a> & mehr',
        ),
        (
            "<b>Hello <i>%(name)s</i></b>!",
            ["python-format"],
            '<span id="0">Hallo <span id="1"><span translate="no" id="2">%(name)s</span></span></span> !',
            "<b>Hallo <i>%(name)s</i></b>!",
        ),
        # the service's escaping is undone
        ("Fish & 'chips'", [], "Fisch &amp; &#39;Pommes&#39;", "Fisch & 'Pommes'"),
        # markup added by the service is dropped
        (
            "Saved %s",
            ["python-format"],
            '<span class="x">Salvo</span> ' + span(0, "%s"),
            "Salvo %s",
        ),
        # the source is restored, not the service's copy
        (
            "Saved %(n)s",
            ["python-format"],
            "Salvo " + span(0, "%(nome)s"),
            "Salvo %(n)s",
        ),
        # lost and duplicated placeholders are rejected
        ("Saved %s", ["python-format"], "Salvo item", None),
        ("Saved %s", ["python-format"], f"Salvo {span(0, '%s')} {span(0, '%s')}", None),
    ],
)
def test_html_guard(source, flags, translation, expected):
    assert restore(protect(source, HTML, flags), translation) == expected


@pytest.mark.parametrize(
    "source, flags, translation, expected",
    [
        ("Saved %s", ["python-format"], "Gespeichert __item__", "Gespeichert %s"),
        # Google translated the token as a word
        ("Saved %s", ["python-format"], "Item salvo", None),
        # named tokens are restored by name
        ("%(a)s and %(b)s", ["python-format"], "__b__ y __a__", "%(b)s y %(a)s"),
        ("100%% of %(n)d", ["python-format"], "100__x0__ von __n__", "100%% von %(n)d"),
        # leading and trailing whitespace comes from the source
        ("\nLeading newline", [], "Führende Zeile", "\nFührende Zeile"),
        # a mangled token is rejected
        ("`{package}` package", ["python-brace-format"], "`__ paket__` bolaq", None),
    ],
)
def test_token_guard(source, flags, translation, expected):
    assert restore(protect(source, TOKEN, flags), translation) == expected

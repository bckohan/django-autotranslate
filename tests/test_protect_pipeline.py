"""
The translations in these tests are real outputs from Google Cloud Translation for
the encoded messages.
"""

import re

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


@pytest.mark.parametrize(
    "source, flags, translation, expected",
    [
        # raw angle brackets and ampersands in service text are text
        (
            "Is %s ok",
            ["python-format"],
            f"{span(0, '%s')} ok 1<2 and a<b & c",
            "%s ok 1<2 and a<b & c",
        ),
        ("Saved %s", ["python-format"], f"fim <a {span(0, '%s')}", "fim <a %s"),
        ("Saved %s", ["python-format"], f"&lt;b&gt; {span(0, '%s')}", None),
        ("Saved %s", ["python-format"], f"&lt;3 {span(0, '%s')}", "<3 %s"),
        # single quoted, unquoted and upper case markup
        ("Saved %s", ["python-format"], "Salvo <SPAN ID='0'>x</SPAN>", "Salvo %s"),
        ("Saved %s", ["python-format"], "Salvo <span id=0>x</span>", "Salvo %s"),
        # comments and declarations are dropped
        ("Saved %s", ["python-format"], f"<!-- c -->Salvo {span(0, '%s')}", "Salvo %s"),
        # unknown tags are dropped, their text kept
        (
            "Saved %s",
            ["python-format"],
            f"Salvo<br> <b>muito</b><img src='a'><hr/> {span(0, '%s')}",
            "Salvo muito %s",
        ),
        # lost, duplicated and unclosed spans are rejected
        ("Saved %s", ["python-format"], "Salvo", None),
        ("Saved %s", ["python-format"], f"{span(0, '%s')}{span(0, '%s')}", None),
        ("Saved %s", ["python-format"], '<span id="0">%s', None),
        # paired ids on void elements must not inject the source's children
        ('Read <a href="x">docs</a>', [], 'Lê <span id="0"/> agora', None),
        ('Read <a href="x">docs</a>', [], 'Lê <br id="0"> agora', None),
        ("Saved %s", ["python-format"], 'Lê <br id="0"> agora', None),
        ("Saved %s", ["python-format"], 'Lê <span id="0"/> agora', "Lê %s agora"),
        ("a\nb", [], 'a<br translate="no" id="0">b', "a\nb"),
    ],
)
def test_html_decode_hardening(source, flags, translation, expected):
    assert restore(protect(source, HTML, flags), translation) == expected


@pytest.mark.parametrize(
    "source, flags, translation, expected",
    [
        # a duplicated token is rejected
        ("a %(n)d", ["python-format"], "a __n__ __n__", None),
        # unknown literal tokens are kept
        ("a %(n)d", ["python-format"], "a __word__ __n__", "a __word__ %(n)d"),
        # literal tokens in the source do not collide with real ones
        ("__item__ %s", ["python-format"], "__item__ __x0__", "__item__ %s"),
        ("__item__ %s", ["python-format"], "__item__ __item__", None),
    ],
)
def test_token_guard_hardening(source, flags, translation, expected):
    assert restore(protect(source, TOKEN, flags), translation) == expected


def test_token_markup_does_not_collide_with_placeholder():
    protected = protect("%(x0)s <b>bold</b>", TOKEN, ["python-format"])
    encoded = protected.encoded
    names = re.findall(r"__(\w+?)__", encoded)
    assert len(names) == 3 and len(set(names)) == 3
    first, start, end = names
    translated = f"__{start}__negrito__{end}__ __{first}__"
    assert restore(protected, translated) == "<b>negrito</b> %(x0)s"


NBSP = "\u00a0"


@pytest.mark.parametrize(
    "source, flags, translation, expected",
    [
        ("%s%s", ["python-format"], f"{span(0, '%s')} {span(1, '%s')}", "%s%s"),
        ("%s %s", ["python-format"], f"{span(0, '%s')} {span(1, '%s')}", "%s %s"),
        # French typography is kept, ordinary spaces are removed
        (
            "{file}: x",
            ["python-brace-format"],
            f"{span(0, '{file}')}{NBSP}: x",
            f"{{file}}{NBSP}: x",
        ),
        ("{file}: x", ["python-brace-format"], f"{span(0, '{file}')} : x", "{file}: x"),
        (
            "\u00ab %s \u00bb",
            ["python-format"],
            f"\u00ab{NBSP}{span(0, '%s')}{NBSP}\u00bb",
            f"\u00ab{NBSP}%s{NBSP}\u00bb",
        ),
        (
            "`%s` x",
            ["python-format"],
            f"`{NBSP}{span(0, '%s')}{NBSP}` x",
            f"`{NBSP}%s{NBSP}` x",
        ),
    ],
)
def test_repair_whitespace(source, flags, translation, expected):
    assert restore(protect(source, HTML, flags), translation) == expected


@pytest.mark.parametrize(
    "source, flags, translation",
    [
        ("{file}: x", ["python-brace-format"], f"{span(0, '{file}')} : x"),
        ("Saved %s", ["python-format"], f"Salvo{span(0, '%s')}"),
        ("%s%s", ["python-format"], f"{span(0, '%s')} {span(1, '%s')}"),
        ("`%s` x", ["python-format"], f"` {span(0, '%s')} ` x"),
    ],
)
def test_repair_idempotent(source, flags, translation):
    from autotranslate.protect.parse import parse
    from autotranslate.protect.repair import repair

    segments = parse(source, flags)
    decoded = HTML.decode(translation, segments)
    once = repair(segments, decoded)
    assert repair(segments, once) == once


@pytest.mark.parametrize(
    "guard, translation",
    [
        # the service added placeholders or markup outside the guards
        (HTML, f"Salvo {span(0, '%s')} (%s)"),
        (HTML, f"Salvo {span(0, '%s')} &lt;b&gt;"),
        (TOKEN, "Salvo __item__ %d"),
    ],
)
def test_restore_rejects_extra_directives(guard, translation):
    protected = protect("Saved %s", guard, ["python-format"])
    assert restore(protected, translation) is None


def test_repair_respects_reordering():
    protected = protect("%(a)s%(b)s and %(c)s", TOKEN, ["python-format"])
    out = restore(protected, "__a__ __c__ e __b__")
    assert out == "%(a)s %(c)s e %(b)s"
    assert restore(protected, "__a____b__ e __c__") == "%(a)s%(b)s e %(c)s"

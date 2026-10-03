import pytest

from autotranslate.protect.html import html
from autotranslate.protect.parse import parse
from autotranslate.protect.segments import Opaque, Paired, Text, serialize


def test_not_html():
    assert html("a < b > c & d") == [Text("a < b > c & d")]


def test_paired_and_void():
    assert html('Read <a href="/x">the docs</a><br/>') == [
        Text("Read "),
        Paired(
            Opaque('<a href="/x">', "tag", "a"),
            Opaque("</a>", "tag", "a"),
            [Text("the docs")],
        ),
        Opaque("<br/>", "tag", "br"),
    ]


def test_opaque_elements_and_entities():
    assert html("Run <code>make <b>x</b></code> &nbsp; &#39;") == [
        Text("Run "),
        Opaque("<code>make <b>x</b></code>", "tag", "code"),
        Text(" "),
        Opaque("&nbsp;", "entity"),
        Text(" "),
        Opaque("&#39;", "entity"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "<CODE>x</CODE> and </A >",
        "<b>a <i>b</b> c",
        "<b>unclosed and </i> stray",
        "<br> then <b>bold</b>",
        "<!-- note --> text",
        '<a href="%(url)s">docs</a>\nnext',
    ],
)
def test_round_trip(text):
    assert serialize(html(text)) == text
    assert serialize(parse(text, ["python-format"])) == text


def test_parse_composes_tokenizers():
    assert parse('<a href="%(url)s">Hi %(name)s</a>\nok', ["python-format"]) == [
        Paired(
            Opaque('<a href="%(url)s">', "tag", "a"),
            Opaque("</a>", "tag", "a"),
            [Text("Hi "), Opaque("%(name)s", "printf", "name")],
        ),
        Opaque("\n", "newline"),
        Text("ok"),
    ]

from autotranslate.protect.formats import (
    brace,
    printf,
    simple_brace,
    simple_printf,
    tokenizers_for,
)
from autotranslate.protect.segments import Opaque, Text, serialize


def test_printf_named_and_positional():
    assert printf("Hello %(name)s, you have %d new") == [
        Text("Hello "),
        Opaque("%(name)s", "printf", "name"),
        Text(", you have "),
        Opaque("%d", "printf", "number"),
        Text(" new"),
    ]


def test_printf_full_grammar():
    # flags, * width, precision, length modifier and nested parentheses in keys
    segments = printf("%-*.3f %+05d %ld %(a(b))s %a %r")
    assert [s.source for s in segments if isinstance(s, Opaque)] == [
        "%-*.3f",
        "%+05d",
        "%ld",
        "%(a(b))s",
        "%a",
        "%r",
    ]


def test_printf_escape():
    assert printf("100%% of %(n)d") == [
        Text("100"),
        Opaque("%%", "escape"),
        Text(" of "),
        Opaque("%(n)d", "printf", "n"),
    ]


def test_simple_printf_ignores_prose():
    assert simple_printf("100% sure") == [Text("100% sure")]
    assert simple_printf("Saved %s") == [Text("Saved "), Opaque("%s", "printf", "item")]


def test_brace():
    text = "You have {count} new {{literal}} {0} {x.y:>{w}} {!r}"
    segments = brace(text)
    assert serialize(segments) == text
    assert [(s.source, s.kind, s.name) for s in segments if isinstance(s, Opaque)] == [
        ("{count}", "brace", "count"),
        ("{{", "escape", ""),
        ("}}", "escape", ""),
        ("{0}", "brace", "item"),
        ("{x.y:>{w}}", "brace", "x"),
        ("{!r}", "brace", "item"),
    ]


def test_brace_invalid_is_text():
    assert brace("Bad { brace") == [Text("Bad { brace")]


def test_simple_brace():
    assert simple_brace("{name} and {} but not {{x}}") == [
        Opaque("{name}", "brace", "name"),
        Text(" and "),
        Opaque("{}", "brace", "item"),
        Text(" but not {{x}}"),
    ]


def test_tokenizers_for_flags():
    assert tokenizers_for(["python-format"]) == [printf]
    assert tokenizers_for(["python-brace-format"]) == [brace]
    assert tokenizers_for(["python-format", "python-brace-format"]) == [printf, brace]
    assert tokenizers_for(["no-python-format"]) == []
    assert tokenizers_for(["fuzzy"]) == [simple_printf, simple_brace]
    assert tokenizers_for([]) == [simple_printf, simple_brace]

"""
Tokenize HTML markup in messages (e.g. ``Read the <a href="%(url)s">docs</a>``).

Elements become :class:`.Paired` segments whose content is translated. Void and
self-closing elements, comments, character references and whole elements in
:data:`OPAQUE_ELEMENTS` are :class:`.Opaque`. Attribute values are not translated.
"""

import re
from html.parser import HTMLParser

from .segments import Opaque, Paired, Segment, Text, merge_text, serialize

#: Elements whose content must not be translated
OPAQUE_ELEMENTS = {"code", "kbd", "pre", "samp", "script", "style", "var"}

LOOKS_LIKE_HTML = re.compile(
    r"<(?:[a-zA-Z][^<>]*|/[a-zA-Z][^<>]*|!--.*?--)>|&#?\w+;", re.DOTALL
)


class _Element:
    def __init__(self, start: Opaque | None, tag: str):
        self.start = start
        self.tag = tag
        self.children: list[Segment] = []


class _Tokenizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = [_Element(None, "")]
        self.end_tag_source = ""

    @property
    def children(self) -> list[Segment]:
        return self.stack[-1].children

    def parse_endtag(self, i):
        # remember the end tag exactly as written (e.g. "</A >")
        end = self.rawdata.find(">", i)
        self.end_tag_source = self.rawdata[i : end + 1] if end != -1 else ""
        return super().parse_endtag(i)

    def handle_starttag(self, tag, attrs):
        self.stack.append(
            _Element(Opaque(self.get_starttag_text() or "", "tag", tag), tag)
        )

    def handle_startendtag(self, tag, attrs):
        self.children.append(Opaque(self.get_starttag_text() or "", "tag", tag))

    def handle_endtag(self, tag):
        end = Opaque(self.end_tag_source or f"</{tag}>", "tag", tag)
        if not any(element.tag == tag for element in self.stack[1:]):
            # an end tag without a start tag
            self.children.append(end)
            return
        # close elements left open inside this one, they become loose start tags
        while self.stack[-1].tag != tag:
            self._unwind()
        element = self.stack.pop()
        assert element.start is not None
        if tag in OPAQUE_ELEMENTS or any(e.tag in OPAQUE_ELEMENTS for e in self.stack):
            self.children.append(
                Opaque(
                    element.start.source + serialize(element.children) + end.source,
                    "tag",
                    tag,
                )
            )
        else:
            self.children.append(
                Paired(element.start, end, merge_text(element.children))
            )

    def _unwind(self):
        element = self.stack.pop()
        assert element.start is not None
        self.children.append(element.start)
        self.children.extend(element.children)

    def handle_data(self, data):
        self.children.append(Text(data))

    def handle_entityref(self, name):
        self.children.append(Opaque(f"&{name};", "entity"))

    def handle_charref(self, name):
        self.children.append(Opaque(f"&#{name};", "entity"))

    def handle_comment(self, data):
        self.children.append(Opaque(f"<!--{data}-->", "comment"))

    def segments(self) -> list[Segment]:
        self.close()
        while len(self.stack) > 1:
            self._unwind()
        return merge_text(self.stack[0].children)


def html(text: str) -> list[Segment]:
    """
    Tokenize the HTML in a message. Messages that do not look like they contain
    HTML are returned as text.
    """
    if not LOOKS_LIKE_HTML.search(text):
        return [Text(text)]
    tokenizer = _Tokenizer()
    tokenizer.feed(text)
    return tokenizer.segments()

"""
Guards protect opaque segments while a message is translated.

A guard encodes a message's segments into the text sent to a service and decodes
the service's translation back into segments. :meth:`Guard.decode` returns None if
the translation's opaque segments do not match the source's.
"""

import html as html_lib
import re
from collections import Counter
from html.parser import HTMLParser

from .segments import Opaque, Paired, Segment, Text, merge_text, opaques


class Guard:
    """Base class for guards."""

    #: The content type the encoded text is in: ``text`` or ``html``
    content_type: str = "text"

    def encode(self, segments: list[Segment]) -> str:
        raise NotImplementedError

    def decode(self, translation: str, segments: list[Segment]) -> list[Segment] | None:
        raise NotImplementedError


def same_opaques(source: list[Segment], translation: list[Segment]) -> bool:
    """
    Do the translation's opaque segments match the source's? Order may differ
    because translations may reorder words.
    """

    def count(segments):
        return Counter(
            (opaque.kind, opaque.source)
            for opaque in opaques(segments)
            if opaque.kind != "newline"
        )

    return count(source) == count(translation)


def _flat(segments: list[Segment]) -> list[Segment]:
    """Flatten paired segments into their opaque start and end markup."""
    flat: list[Segment] = []
    for segment in segments:
        if isinstance(segment, Paired):
            flat.append(segment.start)
            flat.extend(_flat(segment.children))
            flat.append(segment.end)
        else:
            flat.append(segment)
    return flat


class TokenGuard(Guard):
    """
    For services that only translate plain text. Opaque segments are replaced with
    word-like tokens: ``__name__`` for named placeholders, ``__item__`` and
    ``__number__`` for unnamed ones and ``__x0__``, ``__x1__``, ... for markup.
    Newlines are sent as is. Tokens are restored by name, or in order when names
    repeat.
    """

    TOKEN = re.compile(r"__(\w+?)__")

    def _tokens(self, segments: list[Segment]) -> list[tuple[str, Opaque]]:
        tokens = []
        markup = 0
        for segment in _flat(segments):
            if not isinstance(segment, Opaque) or segment.kind == "newline":
                continue
            if segment.kind in {"printf", "brace"} and re.fullmatch(
                r"\w+", segment.name
            ):
                tokens.append((segment.name.lower(), segment))
            else:
                tokens.append((f"x{markup}", segment))
                markup += 1
        return tokens

    def encode(self, segments: list[Segment]) -> str:
        tokens = iter(self._tokens(segments))
        parts = []
        for segment in _flat(segments):
            if isinstance(segment, Text):
                parts.append(segment.text)
            elif isinstance(segment, Opaque) and segment.kind == "newline":
                parts.append(segment.source)
            else:
                parts.append(f"__{next(tokens)[0]}__")
        return "".join(parts)

    def decode(self, translation: str, segments: list[Segment]) -> list[Segment] | None:
        remaining = self._tokens(segments)
        decoded: list[Segment] = []
        end = 0
        for match in self.TOKEN.finditer(translation):
            name = match.group(1).lower()
            index = next(
                (idx for idx, (token, _) in enumerate(remaining) if token == name), None
            )
            if index is None:
                continue
            decoded.append(Text(translation[end : match.start()]))
            decoded.append(remaining.pop(index)[1])
            end = match.end()
        decoded.append(Text(translation[end:]))
        decoded = merge_text(decoded)
        return decoded if same_opaques(segments, decoded) else None


class _HTMLDecoder(HTMLParser):
    """Map a service's HTML output back onto the source segments by id."""

    def __init__(self, by_id: dict[str, Segment]):
        super().__init__(convert_charrefs=True)
        self.by_id = by_id
        self.stack: list[tuple[str, Segment | None, list[Segment]]] = [("", None, [])]
        self.used: set[str] = set()
        self.ok = True

    def _take(self, attrs) -> Segment | None:
        id_ = dict(attrs).get("id")
        if id_ is None or id_ not in self.by_id:
            return None
        if id_ in self.used:
            # the service duplicated the markup
            self.ok = False
            return None
        self.used.add(id_)
        return self.by_id[id_]

    def handle_starttag(self, tag, attrs):
        segment = self._take(attrs)
        if tag == "br" and segment is not None:
            self.stack[-1][2].append(segment)
            return
        # unknown tags added by the service are dropped, keeping their text
        self.stack.append((tag, segment, []))

    def handle_startendtag(self, tag, attrs):
        segment = self._take(attrs)
        if segment is not None:
            self.stack[-1][2].append(segment)

    def handle_endtag(self, tag):
        if tag == "br" or len(self.stack) == 1:
            return
        _tag, segment, children = self.stack.pop()
        if isinstance(segment, Opaque):
            # the service's copy of the opaque text is ignored
            self.stack[-1][2].append(segment)
        elif isinstance(segment, Paired):
            self.stack[-1][2].append(
                Paired(segment.start, segment.end, merge_text(children))
            )
        else:
            self.stack[-1][2].extend(children)

    def handle_data(self, data):
        if not (self.stack[-1][1] and isinstance(self.stack[-1][1], Opaque)):
            self.stack[-1][2].append(Text(data))

    def result(self) -> list[Segment] | None:
        self.close()
        if not self.ok or len(self.stack) != 1:
            return None
        return merge_text(self.stack[0][2])


class HTMLGuard(Guard):
    """
    For services that translate HTML and leave elements with ``translate="no"``
    alone (Google Cloud Translation, Amazon Translate). Opaque segments are sent as
    ``<span translate="no" id="N">source</span>``, newlines as
    ``<br translate="no" id="N">`` and paired markup as ``<span id="N">...</span>``
    so the service can move it with the words it wraps. The service's copies of
    opaque text are ignored when decoding, the source is restored by id.
    """

    content_type = "html"

    def _encode(self, segments: list[Segment], by_id: dict[str, Segment]) -> str:
        parts = []
        for segment in segments:
            if isinstance(segment, Text):
                parts.append(html_lib.escape(segment.text, quote=False))
                continue
            id_ = str(len(by_id))
            by_id[id_] = segment
            if isinstance(segment, Paired):
                parts.append(
                    f'<span id="{id_}">{self._encode(segment.children, by_id)}</span>'
                )
            elif segment.kind == "newline":
                parts.append(f'<br translate="no" id="{id_}">')
            else:
                source = html_lib.escape(segment.source, quote=False)
                parts.append(f'<span translate="no" id="{id_}">{source}</span>')
        return "".join(parts)

    def encode(self, segments: list[Segment]) -> str:
        return self._encode(segments, {})

    def decode(self, translation: str, segments: list[Segment]) -> list[Segment] | None:
        by_id: dict[str, Segment] = {}
        self._encode(segments, by_id)
        decoder = _HTMLDecoder(by_id)
        decoder.feed(translation)
        decoded = decoder.result()
        if decoded is None or not same_opaques(segments, decoded):
            return None
        return decoded

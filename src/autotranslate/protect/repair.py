"""
Repair the whitespace services insert or remove around opaque segments.

Services translating HTML add spaces between markup and punctuation (``{file} :``,
`` ` {name} ` ``) and sometimes drop the space between a word and markup
(``Salvo%s``). The source tells us which is right: whitespace next to an opaque
segment is removed where the source had none before punctuation, and restored
where the source had a space between a word and the segment.
"""

import unicodedata

from .segments import Opaque, Paired, Segment, Text, merge_text

# scripts that are written without spaces between words
NO_SPACE_SCRIPTS = (
    "CJK",
    "HIRAGANA",
    "KATAKANA",
    "THAI",
    "LAO",
    "KHMER",
    "MYANMAR",
    "TIBETAN",
)


# only ordinary whitespace is repaired: no-break spaces (U+00A0, U+202F) are
# deliberate, e.g. French typography (``« %s »``, ``{file} :``)
SPACES = " \t\r\n\f\v"


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char)[0] in "PS"


def _is_spaced_letter(char: str) -> bool:
    if not unicodedata.category(char).startswith("L"):
        return False
    name = unicodedata.name(char, "")
    return not name.startswith(NO_SPACE_SCRIPTS)


def _boundaries(segments: list[Segment]) -> list[Segment]:
    """Flatten into text and opaque markers, paired markup becoming its tags."""
    flat: list[Segment] = []
    for segment in segments:
        if isinstance(segment, Paired):
            flat.append(segment.start)
            flat.extend(_boundaries(segment.children))
            flat.append(segment.end)
        else:
            flat.append(segment)
    return flat


def _context(segments: list[Segment]) -> dict[int, tuple[str, str]]:
    """
    For each opaque segment (by identity), the source text immediately before and
    after it: "" for whitespace or the string edge, else the neighbouring character.
    A space between a word and the segment is recorded as " ".
    """
    flat = _boundaries(segments)
    context = {}
    for index, segment in enumerate(flat):
        if not isinstance(segment, Opaque):
            continue
        before = flat[index - 1] if index else None
        after = flat[index + 1] if index + 1 < len(flat) else None
        left = right = ""
        if isinstance(before, Text) and before.text:
            left = " " if before.text[-1].isspace() else before.text[-1]
        elif isinstance(before, Opaque):
            left = "<"
        if isinstance(after, Text) and after.text:
            right = " " if after.text[0].isspace() else after.text[0]
        elif isinstance(after, Opaque):
            right = ">"
        context[id(segment)] = (left, right)
    return context


def repair(source: list[Segment], translation: list[Segment]) -> list[Segment]:
    """
    Repair the whitespace around the opaque segments in a decoded translation.

    :param source: The source message's segments
    :param translation: The decoded translation's segments, whose opaque segments
        are the source's (see :meth:`Guard.decode`)
    :return: The repaired translation segments
    """
    context = _context(source)

    def fix(segments: list[Segment]) -> list[Segment]:
        flat = _boundaries(segments)
        texts = {id(seg): seg.text for seg in flat if isinstance(seg, Text)}
        for index, segment in enumerate(flat):
            if not isinstance(segment, Opaque) or id(segment) not in context:
                continue
            left, right = context[id(segment)]
            before = flat[index - 1] if index else None
            after = flat[index + 1] if index + 1 < len(flat) else None
            for neighbour, boundary in ((before, left == "<"), (after, right == ">")):
                # the source had no space between adjacent opaque segments
                if (
                    boundary
                    and isinstance(neighbour, Text)
                    and neighbour.text
                    and not texts[id(neighbour)].strip(SPACES)
                ):
                    texts[id(neighbour)] = ""
            if segment.kind == "newline":
                # services add spaces around the <br> newlines are sent as
                if isinstance(before, Text) and left != " ":
                    texts[id(before)] = texts[id(before)].rstrip(" \t")
                if isinstance(after, Text) and right != " ":
                    texts[id(after)] = texts[id(after)].lstrip(" \t")
                continue
            if isinstance(before, Text):
                text = texts[id(before)]
                stripped = text.rstrip(SPACES)
                if (
                    left not in ("", " ")
                    and stripped
                    and stripped != text
                    and _is_punctuation(stripped[-1])
                ):
                    # "` {name}" -> "`{name}"
                    text = stripped
                elif left == " " and text and _is_spaced_letter(text[-1]):
                    # "Salvo%s" -> "Salvo %s"
                    text += " "
                texts[id(before)] = text
            if isinstance(after, Text):
                text = texts[id(after)]
                stripped = text.lstrip(SPACES)
                if (
                    right not in ("", " ")
                    and stripped
                    and stripped != text
                    and _is_punctuation(stripped[0])
                ):
                    # "{file} :" -> "{file}:"
                    text = stripped
                elif right == " " and text and _is_spaced_letter(text[0]):
                    text = " " + text
                texts[id(after)] = text
        return _rebuild(segments, texts)

    return fix(translation)


def _rebuild(segments: list[Segment], texts: dict[int, str]) -> list[Segment]:
    rebuilt: list[Segment] = []
    for segment in segments:
        if isinstance(segment, Text):
            rebuilt.append(Text(texts.get(id(segment), segment.text)))
        elif isinstance(segment, Paired):
            rebuilt.append(
                Paired(segment.start, segment.end, _rebuild(segment.children, texts))
            )
        else:
            rebuilt.append(segment)
    return merge_text(rebuilt)


def match_edges(source: str, translation: str) -> str:
    """Give the translation the source's leading and trailing whitespace."""
    leading = source[: len(source) - len(source.lstrip())]
    trailing = source[len(source.rstrip()) :]
    return leading + translation.strip() + trailing

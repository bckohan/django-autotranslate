"""
Protect a message's placeholders and markup while it is translated:

1. parse the message into segments (:func:`~.parse.parse`)
2. encode the segments with the service's guard (:meth:`.Guard.encode`)
3. translate the encoded text (the service)
4. decode the translation back into segments, rejecting it if opaque segments were
   lost or changed (:meth:`.Guard.decode`)
5. repair whitespace around opaque segments (:func:`~.repair.repair`)
6. join the segments into the translated message
"""

import typing as t
from dataclasses import dataclass

from .guards import Guard
from .parse import parse
from .repair import match_edges, repair
from .segments import Segment, serialize


@dataclass
class Protected:
    """A message prepared for translation."""

    source: str
    segments: list[Segment]
    guard: Guard
    encoded: str
    """The text to send to the translation service"""


def protect(text: str, guard: Guard, flags: t.Collection[str] = ()) -> Protected:
    """
    Prepare a message for translation.

    :param text: The message
    :param guard: The translation service's guard
    :param flags: The message's gettext flags (e.g. ``python-format``)
    """
    segments = parse(text, flags)
    return Protected(text, segments, guard, guard.encode(segments))


def restore(protected: Protected, translation: str) -> str | None:
    """
    Restore the protected placeholders and markup in a translation.

    :param protected: The prepared source message
    :param translation: The service's translation of :attr:`Protected.encoded`
    :return: The translated message, or None if the translation lost or changed
        placeholders or markup
    """
    decoded = protected.guard.decode(translation, protected.segments)
    if decoded is None:
        return None
    return match_edges(protected.source, serialize(repair(protected.segments, decoded)))

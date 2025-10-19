"""
:author: Doug Skrypa
"""

from __future__ import annotations

import re
from collections import UserDict
from functools import cached_property
from shutil import get_terminal_size
from typing import Callable, Collection, Iterator, MutableMapping, Sequence, TypeVar

from rich.highlighter import NullHighlighter
from rich.pretty import pretty_repr
from rich.text import Text

__all__ = [
    'strip_style', 'partitioned', 'ClearableCachedPropertyMixin', 'IntervalCoverageMap', 'short_repr', 'rich_repr'
]

T = TypeVar('T')
Obj = TypeVar('Obj')
Method = Callable[[Obj], T]
Cache = MutableMapping[str, T]

NULL_HIGHLIGHTER = NullHighlighter()
_NOT_FOUND = object()
_MAX_WIDTH = None


def rich_repr(obj, max_width: int = None) -> str:
    """Render a non-highlighted (symmetrical) pretty repr of the given object using rich."""
    if max_width is None:
        global _MAX_WIDTH
        if _MAX_WIDTH is None:
            max_width = _MAX_WIDTH = get_terminal_size()[0]
        else:
            max_width = _MAX_WIDTH

    text = pretty_repr(obj, max_width=max_width)
    return str(Text(text, style='pretty'))


def strip_style(text: str, strip: bool = True) -> str:
    """
    Strip style tags from the given wiki text string.

    2, 3, or 5 's = italic / bold / italic + bold

    Replaces the need for using mwparserfromhell in addition to wikitextparser.

    :param text: The text from which style tags should be stripped
    :param strip: Also strip leading/trailing spaces
    :return: The given text, without style tags
    """
    if "''" in text:
        try:
            patterns_a = strip_style._patterns_a
        except AttributeError:
            patterns_a = strip_style._patterns_a = [
                re.compile(r"(''''')(.+?)(\1)"), re.compile(r"(''')(.+?)(\1)"), re.compile(r"('')(.+?)(\1)")
            ]  # Replace longest matches first

        for pat in patterns_a:
            text = pat.sub(r'\2', text)

    try:
        patterns_b = strip_style._patterns_b
    except AttributeError:
        patterns_b = strip_style._patterns_b = [re.compile(r'<(small)>(.+?)</(\1)>')]

    for pat in patterns_b:
        text = pat.sub(r'\2', text)
    return text.strip() if strip else text


def partitioned(seq: Sequence[T], n: int) -> Iterator[Sequence[T]]:
    """
    :param seq: A :class:`collections.abc.Sequence` (i.e., list, tuple, set, etc.)
    :param n: Max number of values in a given partition
    :return: Generator that yields sub-sequences of the given sequence with len being at most n
    """
    for i in range(0, len(seq), n):
        yield seq[i: i + n]


class ClearableCachedPropertyMixin:
    __slots__ = ()

    @classmethod
    def _cached_properties(cls):
        cached_properties = {}
        for clz in cls.mro():
            if clz == cls:
                for k, v in cls.__dict__.items():
                    if isinstance(v, cached_property):
                        cached_properties[k] = v
            else:
                try:
                    # noinspection PyUnresolvedReferences
                    cached_properties.update(clz._cached_properties())
                except AttributeError:
                    pass
        return cached_properties

    def clear_cached_properties(self, *names: str, skip: Collection[str] = None):
        if not names:
            names = self._cached_properties()

        if skip:
            names = (name for name in names if name not in skip)

        for prop in names:
            try:
                del self.__dict__[prop]
            except (KeyError, AttributeError):
                pass


class IntervalCoverageMap(UserDict):
    def __setitem__(self, span: tuple[int, int], value: T):
        try:
            a, b = span
            a = int(a)
            b = int(b)
        except (TypeError, ValueError) as e:
            raise ValueError(f'Expected a pair of ints; found {span}') from e
        if a >= b:
            raise ValueError(f'Expected a pair of ints where the first value is lower than the second; found {span}')

        to_remove = []
        for x, y in self.data:
            if a <= x and b >= y:
                to_remove.append((x, y))
            elif x <= a < b <= y or x <= a < y <= b or a <= x < b <= y:
                return  # the new span cannot be added

        if to_remove:
            for pair in to_remove:
                del self.data[pair]
        self.data[(a, b)] = value


def short_repr(text) -> str:
    text = str(text)
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')

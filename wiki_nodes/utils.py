"""
:author: Doug Skrypa
"""

import re
from collections import UserDict

__all__ = ['strip_style', 'partitioned', 'ClearableCachedPropertyMixin', 'IntervalCoverageMap']


def strip_style(text: str, strip=True) -> str:
    """
    Strip style tags from the given wiki text string.

    2, 3, or 5 's = italic / bold / italic + bold

    Replaces the need for using mwparserfromhell in addition to wikitextparser.

    :param str text: The text from which style tags should be stripped
    :param bool strip: Also strip leading/trailing spaces
    :return str: The given text, without style tags
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


def partitioned(seq, n):
    """
    :param seq: A :class:`collections.abc.Sequence` (i.e., list, tuple, set, etc.)
    :param int n: Max number of values in a given partition
    :return: Generator that yields sub-sequences of the given sequence with len being at most n
    """
    for i in range(0, len(seq), n):
        yield seq[i: i + n]


class ClearableCachedPropertyMixin:
    @classmethod
    def _cached_properties(cls):
        from functools import cached_property
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

    def clear_cached_properties(self):
        for prop in self._cached_properties():
            try:
                del self.__dict__[prop]
            except KeyError:
                pass


class IntervalCoverageMap(UserDict):
    def __setitem__(self, span, value):
        try:
            a, b = map(int, span)
        except (TypeError, ValueError) as e:
            raise ValueError(f'Expected a pair of ints; found {span}') from e
        if a >= b:
            raise ValueError(f'Expected a pair of ints where the first value is lower than the second; found {span}')

        can_add = True
        to_remove = []
        for (x, y) in self.data:
            if a <= x and b >= y:
                to_remove.append((x, y))
            elif x <= a < b <= y or x <= a < y <= b or a <= x < b <= y:
                can_add = False
                break

        if can_add:
            if to_remove:
                for pair in to_remove:
                    del self.data[pair]
            self.data[(a, b)] = value

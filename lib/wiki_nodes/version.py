"""
Based heavily on distutils.version.  Copied here due to its pending removal in Python 3.12.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Union

Ver = Union[str, 'Version']
Bool = Union[bool, type(NotImplemented)]


class Version(ABC):
    __slots__ = ('original', 'version')

    def __init__(self, version_str: str = None):
        self.original = version_str
        if version_str:
            self._parse(version_str)

    def __str__(self) -> str:
        return self.original

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({str(self)!r})'

    def __eq__(self, other: Ver) -> Bool:
        c = self._cmp(other)
        if c is NotImplemented:
            return c
        return c == 0

    def __lt__(self, other: Ver) -> Bool:
        c = self._cmp(other)
        if c is NotImplemented:
            return c
        return c < 0

    def __le__(self, other: Ver) -> Bool:
        c = self._cmp(other)
        if c is NotImplemented:
            return c
        return c <= 0

    def __gt__(self, other: Ver) -> Bool:
        c = self._cmp(other)
        if c is NotImplemented:
            return c
        return c > 0

    def __ge__(self, other: Ver) -> Bool:
        c = self._cmp(other)
        if c is NotImplemented:
            return c
        return c >= 0

    @abstractmethod
    def _parse(self, version_str: str):
        raise NotImplementedError

    @abstractmethod
    def _cmp(self, other: Version) -> int:
        raise NotImplementedError


class StrictVersion(Version):
    """
    A version number consists of two or three dot-separated numeric components, with an optional "pre-release" tag on
    the end.  The pre-release tag consists of the letter 'a' or 'b' followed by a number.  If the numeric components of
    two version numbers are equal, then one with a pre-release tag will always be deemed earlier (lesser) than one
    without.

    The following are valid version numbers (shown in the order that would be obtained by sorting according to the
    supplied cmp function):

        0.4; 0.4.0  (these two are equivalent);
        0.4.1; 0.5a1; 0.5b3; 0.5; 0.9.6; 1.0; 1.0.4a3; 1.0.4b1; 1.0.4

    The following are examples of invalid version numbers: 1; 2.7.2.2; 1.3.a4; 1.3pl1; 1.3c4
    """

    __slots__ = ('pre_release',)

    version_re = re.compile(r'^(\d+) \. (\d+) (\. (\d+))? ([ab](\d+))?$', re.VERBOSE | re.ASCII)

    def _parse(self, version_str: str):
        match = self.version_re.match(version_str)
        if not match:
            raise ValueError(f'invalid version number {version_str!r}')

        major, minor, patch, pre_release, pre_release_num = match.group(1, 2, 4, 5, 6)
        self.version = tuple(map(int, [major, minor, patch or 0]))
        if pre_release:
            self.pre_release = (pre_release[0], int(pre_release_num))
        else:
            self.pre_release = None  # noqa

    def _cmp(self, other) -> int:
        if isinstance(other, str):
            other = StrictVersion(other)
        elif not isinstance(other, StrictVersion):
            return NotImplemented

        # fmt: off
        if self.version != other.version:               # numeric versions don't match - pre-release doesn't matter
            return -1 if self.version < other.version else 1

        if not self.pre_release and not other.pre_release:
            return 0                                    # case 1: neither has pre-release; they're equal
        elif self.pre_release and not other.pre_release:
            return -1                                   # case 2: other > self because it has pre-release, other doesn't
        elif not self.pre_release and other.pre_release:
            return 1                                    # case 3: self > other because it has pre-release, self doesn't
        else:                                           # case 4: both have pre-release: must compare them!
            if self.pre_release == other.pre_release:
                return 0
            elif self.pre_release < other.pre_release:
                return -1
            else:
                return 1
        # fmt: on


class LooseVersion(Version):
    """
    Implements the standard interface for version number classes as described above.  A version number consists of a
    series of numbers, separated by either periods or strings of letters.  When comparing version numbers, the numeric
    components will be compared numerically, and the alphabetic components lexically.  The following are all valid
    version numbers, in no particular order:

        1.5.1; 1.5.2b2; 161; 3.10a; 8.02; 3.4j; 1996.07.12; 3.2.pl0; 3.1.1.6; 2g6; 11g; 0.960923; 2.2beta29; 1.13++;
        5.5.kw; 2.0b1pl0

    In fact, there is no such thing as an invalid version number under this scheme; the rules for comparison are simple
    and predictable, but may not always give the results you want (for some definition of "want").
    """

    __slots__ = ()

    component_re = re.compile(r'(\d+ | [a-z]+ | \.)', re.VERBOSE)

    def _parse(self, version_str: str):
        components = [x for x in self.component_re.split(version_str) if x and x != '.']
        for i, obj in enumerate(components):
            try:
                components[i] = int(obj)
            except ValueError:
                pass

        self.version = components

    def _cmp(self, other) -> int:
        if isinstance(other, str):
            other = LooseVersion(other)
        elif not isinstance(other, LooseVersion):
            return NotImplemented

        if self.version == other.version:
            return 0
        elif self.version < other.version:
            return -1
        else:
            return 1

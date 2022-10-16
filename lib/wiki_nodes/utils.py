"""
:author: Doug Skrypa
"""

from __future__ import annotations

import re
from collections import UserDict
from contextlib import contextmanager
from threading import RLock
from typing import TypeVar, Sequence, Iterator, Callable, MutableMapping, Generic, overload

__all__ = ['strip_style', 'partitioned', 'ClearableCachedPropertyMixin', 'IntervalCoverageMap', 'short_repr']

T = TypeVar('T')
Obj = TypeVar('Obj')
Method = Callable[[Obj], T]
Cache = MutableMapping[str, T]

_NOT_FOUND = object()


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

    def clear_cached_properties(self):
        for prop in self._cached_properties():
            try:
                del self.__dict__[prop]
            except (KeyError, AttributeError):
                pass


class cached_property(Generic[T]):  # noqa
    """
    A cached property implementation that does not block access to all instances' attribute while one instance's
    func is being called.
    """

    def __init__(self, func: Method):
        self.func = func
        self.name = None
        self.__doc__ = func.__doc__
        self.lock = RLock()
        self.instance_locks = {}

    def __set_name__(self, owner, name: str):
        if self.name is None:
            self.name = name
        elif name != self.name:
            raise TypeError(
                f'Cannot assign the same cached_property to two different names ({self.name!r} and {name!r}).'
            )

    def _get_instance_lock(self, key) -> RLock:
        with self.lock:
            try:
                return self.instance_locks[key]
            except KeyError:
                self.instance_locks[key] = lock = RLock()
                return lock

    @contextmanager
    def instance_lock(self, instance: Obj, owner):
        key = (owner, id(instance))
        # Some object instances are not hashable, but its class + id should be unique long enough for this purpose
        lock = self._get_instance_lock(key)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            # During the yield, a value will have been stored, or an error will have been raised.
            # If another instance was waiting for the instance lock, it will find the cached value and the key will
            # have already been deleted by the time it gets here.  If another thread attempts to access the property
            # after this point, it will already be cached, so the lock for that instance is no longer necessary.
            with self.lock:
                try:
                    del self.instance_locks[key]
                except KeyError:
                    pass

    @overload
    def __get__(self, instance: None, owner) -> cached_property:
        ...

    @overload
    def __get__(self, instance: Obj, owner) -> T:
        ...

    def __get__(self, instance, owner):
        if instance is None:
            return self
        elif self.name is None:
            raise TypeError('Cannot use cached_property instance without calling __set_name__ on it.')

        try:
            cache = instance.__dict__
        except AttributeError:  # not all objects have __dict__ (e.g. class defines slots)
            cls = owner.__name__
            raise TypeError(f"Unable to cache {cls}.{self.name} because {cls} has no '__dict__' attribute") from None

        if (val := cache.get(self.name, _NOT_FOUND)) is _NOT_FOUND:
            with self.instance_lock(instance, owner):
                # check if another thread filled cache while we awaited lock
                if (val := cache.get(self.name, _NOT_FOUND)) is _NOT_FOUND:
                    val = self.func(instance)
                    try:
                        cache[self.name] = val
                    except TypeError:
                        cls = owner.__name__
                        raise TypeError(
                            f'Unable to cache {cls}.{self.name} because {cls}.__dict__ does not support item assignment'
                        ) from None

        return val


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


def short_repr(text) -> str:
    text = str(text)
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')

#!/usr/bin/env python

from abc import ABC, abstractmethod
from concurrent.futures import as_completed, ThreadPoolExecutor
from itertools import count
from time import sleep, monotonic
from unittest import TestCase, main

from wiki_nodes.utils import cached_property, ClearableCachedPropertyMixin

SLEEP_TIME = 0.05


class TestError(Exception):
    pass


class ConcurrentAccessBase(ABC):
    def __init__(self, sleep_time: float):
        self.counter = count()
        self.sleep_time = sleep_time
        self.last = None

    def sleep(self):
        start = monotonic()
        self.last = next(self.counter)
        sleep(self.sleep_time)
        end = monotonic()
        return start, end

    @property
    @abstractmethod
    def bar(self) -> tuple[float, float]:
        raise NotImplementedError

    def get_bar(self) -> tuple[float, float]:
        return self.bar


def init_and_get_call_times(cls, num_calls: int = 3) -> list[tuple[float, float]]:
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(cls(SLEEP_TIME).get_bar) for _ in range(num_calls)]
        times = [future.result() for future in as_completed(futures)]

    return times


def get_call_times(func, num_calls: int = 3) -> list[tuple[float, float]]:
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(func) for _ in range(num_calls)]
        times = []
        for future in as_completed(futures):
            try:
                times.append(future.result())
            except TestError:
                pass

    return times


class CachedPropertyTest(TestCase):
    def test_get_with_no_instance(self):
        class Foo:
            @cached_property
            def bar(self):
                return 5

        self.assertIsInstance(Foo.bar, cached_property)

    def test_reassign_name_error(self):
        with self.assertRaisesRegex(RuntimeError, 'Error calling __set_name__ on') as exc_ctx:
            class Foo:
                @cached_property
                def bar(self):
                    return 1
                baz = bar  # this triggers the expected exception

        original_exc = exc_ctx.exception.__cause__
        self.assertRegex(str(original_exc), 'Cannot assign the same')

    def test_reassign_same_name_ok(self):
        class Foo:
            @cached_property
            def bar(self):
                return 1

        self.assertIs(None, Foo.bar.__set_name__(Foo, 'bar'))  # noqa

    def test_unnamed_error(self):
        class Foo:
            @cached_property
            def bar(self):
                return 1

        Foo.bar.name = None
        with self.assertRaisesRegex(TypeError, 'Cannot use .* without calling __set_name__ on it'):
            _ = Foo().bar

    def test_no_dict_error(self):
        class Foo:
            __slots__ = ()

            @cached_property
            def bar(self):
                return 1

        with self.assertRaisesRegex(TypeError, r'Unable to cache Foo\.bar because Foo has no .__dict__. attribute'):
            _ = Foo().bar

    def test_immutable_dict_error(self):
        class ImmutableDict(dict):
            def __setitem__(self, key, value):
                raise TypeError

        class Foo:
            __slots__ = ('__dict__',)

            def __init__(self):
                self.__dict__ = ImmutableDict()

            @cached_property
            def bar(self):
                return 1

        with self.assertRaisesRegex(TypeError, r'Unable to cache Foo\.bar because Foo\.__dict__ does not support'):
            _ = Foo().bar

    def test_other_instances_do_not_block_instance_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                return self.sleep()

        times = init_and_get_call_times(Foo)
        for start, _ in times:
            for _, end in times:
                self.assertLess(start, end)

    def test_other_threads_wait_instance_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                return self.sleep()

        times = get_call_times(Foo(SLEEP_TIME).get_bar)
        self.assertEqual(3, len(times))
        self.assertEqual(1, len(set(times)))

    def test_clear_properties(self):
        class Foo(ClearableCachedPropertyMixin, ConcurrentAccessBase):
            @cached_property
            def bar(self):
                return next(self.counter)

            def baz(self):
                return 1

        foo = Foo(0.001)
        self.assertEqual(0, foo.bar)
        self.assertEqual(0, foo.bar)
        foo.clear_cached_properties()
        foo.clear_cached_properties()  # again for unittest to see key error. . .
        self.assertEqual(1, foo.bar)

    def test_error_on_first_call(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                if not next(self.counter):
                    raise TestError
                return self.sleep()

        foo = Foo(SLEEP_TIME)
        times = get_call_times(foo.get_bar)
        self.assertEqual(2, len(times))
        self.assertEqual(1, len(set(times)))
        self.assertEqual(2, foo.last)


if __name__ == '__main__':
    main(exit=False, verbosity=2)

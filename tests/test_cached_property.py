#!/usr/bin/env python

from functools import cached_property
from itertools import count
from unittest import TestCase, main

from wiki_nodes.utils import ClearableCachedPropertyMixin


class CachedPropertyTest(TestCase):
    def test_clear_properties(self):
        class Foo(ClearableCachedPropertyMixin):
            def __init__(self):
                self.counter = count()

            @cached_property
            def bar(self):
                return next(self.counter)

        foo = Foo()
        self.assertEqual(0, foo.bar)
        self.assertEqual(0, foo.bar)
        foo.clear_cached_properties()
        foo.clear_cached_properties()  # again for unittest to see key error. . .
        self.assertEqual(1, foo.bar)


if __name__ == '__main__':
    main(exit=False, verbosity=2)

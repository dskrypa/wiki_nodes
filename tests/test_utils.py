#!/usr/bin/env python

from unittest import main, TestCase

from wiki_nodes.utils import IntervalCoverageMap, short_repr, partitioned, rich_repr
from wiki_nodes.version import LooseVersion, StrictVersion


class IntervalCoverageMapTest(TestCase):
    def test_overlapping_add_1(self):
        icmap = IntervalCoverageMap()
        icmap[(1, 2)] = 'a'
        icmap[(1, 3)] = 'b'
        self.assertEqual(icmap[(1, 3)], 'b')
        self.assertEqual(len(icmap), 1)

    def test_overlapping_add_2a(self):
        icmap = IntervalCoverageMap()
        icmap[(1, 3)] = 'a'
        icmap[(2, 4)] = 'b'
        self.assertEqual(icmap[(1, 3)], 'a')
        self.assertEqual(len(icmap), 1)

    def test_overlapping_add_2b(self):
        icmap = IntervalCoverageMap()
        icmap[(2, 4)] = 'a'
        icmap[(1, 3)] = 'b'
        self.assertEqual(icmap[(2, 4)], 'a')
        self.assertEqual(len(icmap), 1)

    def test_overlapping_add_3(self):
        icmap = IntervalCoverageMap()
        icmap[(1, 2)] = 'a'
        icmap[(2, 4)] = 'b'
        self.assertEqual(icmap[(1, 2)], 'a')
        self.assertEqual(icmap[(2, 4)], 'b')
        self.assertEqual(len(icmap), 2)
        icmap[(0, 5)] = 'c'
        self.assertEqual(icmap[(0, 5)], 'c')
        self.assertEqual(len(icmap), 1)

    def test_overlapping_add_4(self):
        icmap = IntervalCoverageMap()
        icmap[(1, 2)] = 'a'
        icmap[(1, 2)] = 'b'
        self.assertEqual(icmap[(1, 2)], 'b')
        self.assertEqual(len(icmap), 1)

    def test_overlapping_add_5(self):
        icmap = IntervalCoverageMap()
        icmap[(0, 28)] = 'a'
        icmap[(15, 26)] = 'b'
        self.assertEqual(icmap[(0, 28)], 'a')
        self.assertEqual(len(icmap), 1)

    def test_non_overlapping_add(self):
        icmap = IntervalCoverageMap()
        icmap[(1, 2)] = 'a'
        icmap[(2, 3)] = 'b'
        self.assertEqual(icmap[(1, 2)], 'a')
        self.assertEqual(icmap[(2, 3)], 'b')
        self.assertEqual(len(icmap), 2)

    def test_wrong_order(self):
        with self.assertRaisesRegex(ValueError, 'Expected a pair of ints where the first value'):
            IntervalCoverageMap()[(2, 1)] = 'a'

    def test_bad_type(self):
        with self.assertRaisesRegex(ValueError, 'Expected a pair of ints; found'):
            IntervalCoverageMap()[('a', 1)] = 'a'


class TestUtils(TestCase):
    def test_short_repr_short(self):
        self.assertEqual("'foo'", short_repr('foo'))

    def test_short_repr_long(self):
        self.assertEqual("'" + 'x' * 24 + '...' + 'x' * 23 + "'", short_repr('x' * 100))

    def test_partitioned(self):
        self.assertEqual([[1, 2], [3, 4]], list(partitioned([1, 2, 3, 4], 2)))

    def test_rich_repr_width(self):
        self.assertEqual('[\n    0,\n    1,\n    2,\n    3,\n    4\n]', rich_repr(list(range(5)), 5))


class TestVersion(TestCase):
    def test_sorted_loose(self):
        expected = [LooseVersion('1.1'), LooseVersion('1.1'), LooseVersion('2.1')]
        versions = [LooseVersion('1.1'), LooseVersion('2.1'), LooseVersion('1.1')]
        self.assertListEqual(expected, sorted(versions))

    def test_sorted_strict(self):
        expected = [StrictVersion('1.1a1'), StrictVersion('1.1.1'), StrictVersion('2.1.0')]
        versions = [StrictVersion('1.1.1'), StrictVersion('2.1.0'), StrictVersion('1.1a1')]
        self.assertListEqual(expected, sorted(versions))

    def test_compare_non_version(self):
        ver = LooseVersion('1.1')
        self.assertFalse(ver == 1)
        with self.assertRaises(TypeError):
            ver <= 1  # noqa
        with self.assertRaises(TypeError):
            ver < 1  # noqa
        with self.assertRaises(TypeError):
            ver > 1  # noqa
        with self.assertRaises(TypeError):
            ver >= 1  # noqa
        with self.assertRaises(TypeError):
            StrictVersion('1.1.1') < ver  # noqa

    def test_none(self):
        self.assertIs(None, LooseVersion().original)

    def test_str(self):
        self.assertEqual('1.1', str(LooseVersion('1.1')))
        self.assertEqual("LooseVersion('1.1')", repr(LooseVersion('1.1')))

    def test_compare(self):
        a = StrictVersion('1.1.1')
        b = StrictVersion('1.2.1')
        self.assertTrue(a <= b)
        self.assertTrue(b >= a)
        self.assertTrue(b > a)
        self.assertNotEqual(a, b)

    def test_compare_pre_release(self):
        a = StrictVersion('1.1.1a1')
        b = StrictVersion('1.1.1')
        self.assertTrue(a < b)
        self.assertTrue(b > a)
        c = StrictVersion('1.1.1a2')
        self.assertTrue(a < c)
        self.assertTrue(c > a)

    def test_str_cmp(self):
        self.assertEqual(StrictVersion('1.1.1'), '1.1.1')
        self.assertEqual(LooseVersion('1.1.1a'), '1.1.1a')

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            StrictVersion('a.b.c')


if __name__ == '__main__':
    main(exit=False, verbosity=2)

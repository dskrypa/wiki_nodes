#!/usr/bin/env python

import logging
import sys
from pathlib import Path
from unittest import main, TestCase

sys.path.append(Path(__file__).parents[1].as_posix())
from wiki_nodes.utils import IntervalCoverageMap

log = logging.getLogger(__name__)


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


if __name__ == '__main__':
    main(exit=False, verbosity=2)

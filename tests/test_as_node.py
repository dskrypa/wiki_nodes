#!/usr/bin/env python

import logging
import sys
from os import environ
from pathlib import Path
from unittest import main, TestCase
# from unittest.mock import MagicMock, patch

# TODO: Remove env var here after fully switching to new parser
environ['WIKI_NODES_NEW_PARSER'] = '1'  # This may cause problems if run in a single process with other tests...

sys.path.append(Path(__file__).parents[1].as_posix())
from wiki_nodes import as_node, Link, List, String, CompoundNode

log = logging.getLogger(__name__)


class NodeParsingTest(TestCase):
    def test_no_lists(self):
        # node = as_node("""'''Kim Tae-hyeong''' ({{Korean\n    | hangul  = 김태형\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}; born February 11, 1988), better known as '''Paul Kim''' ({{Korean\n    | hangul  = 폴킴\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}) is a South Korean singer. He debuted in 2014 and has released two extended plays and one full-length album in two parts: ''The Road'' (2017) and ''Tunnel'' (2018).""")
        node = as_node("""'''Kim Tae-hyeong''' ({{Korean
    | hangul  = 김태형
    | hanja   =
    | rr      =
    | mr      =
    | context =
}}; born February 11, 1988), better known as '''Paul Kim''' ({{Korean
    | hangul  = 폴킴
    | hanja   =
    | rr      =
    | mr      =
    | context =
}}) is a South Korean singer. He debuted in 2014 and has released two extended plays and one full-length album in two parts: ''The Road'' (2017) and ''Tunnel'' (2018).
"""
        )
        self.assertTrue(not any(isinstance(n, List) for n in node))

    def test_link(self):
        node = as_node("""[[test]]""")
        self.assertIsInstance(node, Link)

    def test_str_link_str(self):
        node = as_node(""""[[title|text]]" - 3:30""")
        expected = CompoundNode('"[[title|text]]" - 3:30')
        expected.children.extend([String('"'), Link.from_title('title', text='text'), String('" - 3:30')])
        self.assertEqual(node, expected)


if __name__ == '__main__':
    main(exit=False, verbosity=2)
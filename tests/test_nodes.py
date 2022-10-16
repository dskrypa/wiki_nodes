#!/usr/bin/env python

import logging
from unittest import main
from unittest.mock import patch

from wiki_nodes import as_node, Root, Link, List, String, Template, CompoundNode, Tag, Node, BasicNode
from wiki_nodes.testing import WikiNodesTest, RedirectStreams

log = logging.getLogger(__name__)


class NodeParsingTest(WikiNodesTest):
    def test_no_content(self):
        self.assertIs(None, as_node(' '))

    def test_no_attr(self):
        with patch('wiki_nodes.nodes.parsing.get_span_obj_map', return_value={(0, 0): (None, '')}):
            self.assert_equal(CompoundNode(' '), as_node(' '))

    def test_no_lists(self):
        node = as_node("""'''Kim Tae-hyeong''' ({{Korean\n    | hangul  = 김태형\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}; born February 11, 1988), better known as '''Paul Kim''' ({{Korean\n    | hangul  = 폴킴\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}) is a South Korean singer. He debuted in 2014 and has released two extended plays and one full-length album in two parts: ''The Road'' (2017) and ''Tunnel'' (2018).""")
        self.assertTrue(not any(isinstance(n, List) for n in node))

    def test_link(self):
        node = as_node("""[[test]]""")
        self.assertIsInstance(node, Link)

    def test_str_link_str(self):
        node = as_node(""""[[title|text]]" - 3:30""")
        expected = CompoundNode('"[[title|text]]" - 3:30')
        expected.children.extend([String('"'), Link.from_title('title', text='text'), String('" - 3:30')])
        self.assertEqual(node, expected)

    def test_sections(self):
        node = Root('==one==\n[[test]]\n==two==\n{{n/a}}\n===two a===', site='en.wikipedia.org')
        root_section = node.sections
        self.assertEqual(2, root_section.depth)
        self.assertEqual(2, len(root_section.children))
        self.assertEqual(0, len(root_section['one'].children))
        self.assertEqual(Link('[[test]]', root=node), root_section['one'].content)
        self.assertEqual(1, len(root_section['two'].children))
        self.assertEqual(Template('{{n/a}}'), root_section['two'].content)
        self.assertIs(None, root_section['two']['two a'].content)

    def test_invalid_raw(self):
        with self.assertRaisesRegex(ValueError, 'Invalid wiki Tag value'):
            Tag('[[test]]')

    def test_stripped_style(self):
        self.assertEqual('test', String("'''test'''").stripped())

    def test_node_repr(self):
        self.assertEqual('<Node()>', repr(Node('test')))
        self.assertEqual("<BasicNode(WikiText('test'))>", repr(BasicNode('test')))
        self.assertEqual('<CompoundNode[]>', repr(CompoundNode('test')))

    def test_node_bool(self):
        self.assertTrue(Node('test'))
        self.assertFalse(Node(''))

    def test_node_eq(self):
        self.assertEqual(Node('test'), Node('test'))
        self.assertNotEqual(Node('test'), 'test')
        self.assertNotEqual(CompoundNode('test'), 'test')

    def test_node_basic(self):
        self.assertIs(None, Node('test').is_basic)
        self.assertTrue(BasicNode('test').is_basic)
        self.assertFalse(CompoundNode('test').is_basic)

    def test_raw_pprint(self):
        with RedirectStreams() as streams:
            Link('[[test]]').raw_pprint()

        self.assert_strings_equal('[[test]]\n', streams.stdout)

    def test_pprint(self):
        with RedirectStreams() as streams:
            Link('[[test]]').pprint()

        self.assert_strings_equal("<Link:'[[test]]'>\n", streams.stdout)

    def test_basic_node_set(self):
        self.assertSetEqual({BasicNode('test')}, {BasicNode('test'), BasicNode('test')})

    def test_compound_len(self):
        node = CompoundNode('test')
        node.children.append(String('foo'))
        self.assertEqual(1, len(node))
        del node[0]
        self.assertEqual(0, len(node))

    def test_compound_only_basic(self):
        node = CompoundNode('test')
        node.children.append(String('foo'))
        self.assertTrue(node.only_basic)
        node.children.append(CompoundNode('foo'))
        self.assertFalse(node.only_basic)

    def test_compound_find_one(self):
        node = CompoundNode.from_nodes([String('foo'), String('bar')])
        self.assertEqual('bar', node.find_one(String, value='bar'))
        self.assertIs(None, node.find_one(Link))



if __name__ == '__main__':
    main(exit=False, verbosity=2)

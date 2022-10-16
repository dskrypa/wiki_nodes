#!/usr/bin/env python

import logging
from textwrap import dedent
from unittest import main
from unittest.mock import patch, Mock

from wiki_nodes import as_node, Root, Link, List, String, Template, CompoundNode, Tag, Node, BasicNode, MappingNode
from wiki_nodes.exceptions import NoLinkTarget
from wiki_nodes.nodes import ListEntry
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
        self.assertEqual('<Tag[br][None]>', repr(Tag('<br/>')))
        self.assertEqual("<ListEntry(<String('test')>)>", repr(ListEntry('test')))

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

    # region CompoundNode

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

    def test_compound_pformat(self):
        node = CompoundNode.from_nodes([String('foo'), String('bar')])
        expected = "<CompoundNode[\n    <String('foo')>,\n    <String('bar')>\n]>"
        self.assertEqual(expected, node.pformat())

    # endregion

    # region MappingNode

    def test_mapping_keys(self):
        self.assertSetEqual({'a', 'b'}, set(MappingNode('', content={'a': '1', 'b': '2'}).keys()))

    def test_mapping_pformat(self):
        node = MappingNode('', content={'a': String('foo'), 'b': String('bar')})
        expected = "<MappingNode{\n    'a': <String('foo')>,\n    'b': <String('bar')>\n}>"
        self.assertEqual(expected, node.pformat())

    def test_mapping_find_one(self):
        node = MappingNode('', content={'a': String('foo'), 'b': String('bar')})
        self.assertEqual('bar', node.find_one(String, value='bar'))
        self.assertIs(None, node.find_one(Link))

    # endregion

    # region Tag

    def test_tag_basic(self):
        self.assertTrue(Tag('<br/>').is_basic)
        self.assertFalse(Tag('<ref>{{foo|[[bar]]|[[baz]]}}</ref>').is_basic)

    def test_tag_find_all(self):
        tag = Tag('<b>[[foo]]</b>')
        self.assertEqual([Link('[[foo]]')], list(tag.find_all(Link, title='foo')), f'No match found in {tag.value!r}')
        self.assertEqual([], list(tag.find_all(Template)))
        self.assertEqual([], list(Tag('<br/>').find_all(Template)))

    def test_tag_attrs(self):
        tag = Tag('<gallery spacing="small"></gallery>')
        self.assertEqual('small', tag['spacing'])
        self.assertEqual('small', tag.get('spacing'))
        self.assertIs(None, tag.get('bar'))

    # endregion

    # region String

    def test_str_lower(self):
        self.assertEqual('foo', String('FOO').lower)

    def test_str_str(self):
        self.assertEqual('foo', str(String('foo')))

    def test_str_set(self):
        foo, bar = String('foo'), String('bar')
        self.assertSetEqual({foo, bar}, {foo, bar, bar, foo, foo, bar})

    def test_str_bool(self):
        self.assertTrue(String('test'))
        self.assertFalse(String(''))

    def test_str_add(self):
        self.assertEqual('foobar', String('foo') + String('bar'))
        self.assertEqual('foobar', String('foo') + 'bar')

    # endregion

    # region Link

    def test_bad_link(self):
        with self.assertRaisesRegex(ValueError, 'Link init attempted with non-link'):
            Link('{{foo}}')

    def test_link_set(self):
        foo, bar = Link('[[foo]]'), Link('[[bar]]')
        self.assertSetEqual({foo, bar}, {foo, bar, bar, foo, foo, bar})

    def test_link_not_equal_non_link(self):
        self.assertNotEqual(Link('[[foo]]'), String('[[foo]]'))

    def test_link_sort(self):
        foo, bar = Link('[[foo]]'), Link('[[bar]]')
        self.assert_equal([bar, foo], sorted([foo, bar]))

    def test_link_repr_with_site(self):
        self.assert_equal("<Link:'[[foo]]'@bar>", repr(Link('[[foo]]', root=Mock(site='bar'))))
        self.assert_equal("<Link:'[[foo]]'@bar>", repr(Link('[[foo]]', root=Mock(site='wiki.bar.com'))))

    def test_link_to_file(self):
        self.assertTrue(Link('[[file:foo]]').to_file)
        self.assertFalse(Link('[[foo]]').to_file)

    def test_link_url_none(self):
        self.assertIs(None, Link('[[foo]]').url)

    def test_link_interwiki_key_title(self):
        with self.assertRaisesRegex(ValueError, 'is not an interwiki link'):
            _ = Link('[[foo]]').iw_key_title

        root = Mock(site='foo', _interwiki_map={'bar': 'baz'})
        self.assertEqual(('bar', 'foo'), Link('[[bar:foo]]', root=root).iw_key_title)
        self.assertEqual(('bar', 'foo'), Link('[[BAR:foo]]', root=root).iw_key_title)

        with self.assertRaisesRegex(ValueError, 'is not an interwiki link'):
            _ = Link('[[baz:foo]]', root=root).iw_key_title

        with self.assertRaisesRegex(ValueError, 'is not an interwiki link'):
            _ = Link('[[baz:foo]]', root=Mock(site='foo', _interwiki_map={})).iw_key_title

    def test_link_client_and_title(self):
        root = Mock(site='foo')
        client, title = Link('[[foo]]', root=root).client_and_title
        self.assertEqual('foo', title)
        with self.assertRaises(NoLinkTarget):
            _ = Link('[[ ]]', root=root).client_and_title

    # endregion

    # region List & List Entry

    def test_list_entry_init_value(self):
        self.assertEqual('foo', ListEntry('test', _value='foo').value)

    def test_list_entry_no_value(self):
        link = Link('[[foo]]')
        self.assertIs(link.raw, ListEntry(link.raw).value)

    def test_nested_list_entry(self):
        top_level = List('* foo\n** bar\n** baz\n')
        self.assert_equal([ListEntry('* bar'), ListEntry('* baz')], top_level[0].children)

    def test_list_entry_repr(self):
        top_level = List('* foo\n** bar\n** baz\n')
        expected = "<ListEntry(<String('foo')>, [<ListEntry(<String('bar')>)>, <ListEntry(<String('baz')>)>])>"
        self.assertEqual(expected, repr(top_level[0]))

    def test_list_entry_bool(self):
        self.assertTrue(ListEntry('foo'))
        self.assertFalse(ListEntry(' '))

    def test_list_entry_pformat(self):
        expected = "<ListEntry(\n    <CompoundNode[\n        <String('foo')>,\n        <Link:'[[bar]]'>\n    ]>\n)>"
        self.assert_equal(expected, ListEntry('* foo [[bar]]').pformat())

    def test_list_pformat(self):
        top_level = List('*\n** bar\n** baz\n')
        expected = (
            "<List[\n    <ListEntry(\n        None,\n        ["
            "\n            <ListEntry(<String('bar')>)>,\n            <ListEntry(<String('baz')>)>\n        "
            "]\n    )>\n]>"
        )
        self.assert_equal(expected, top_level.pformat())

    def test_list_entry_find_all(self):
        node = List('* foo\n** bar\n** baz\n')[0]
        self.assertEqual('bar', node.find_one(String, value='bar', recurse=True))
        self.assertIs(None, node.find_one(Link))
        entry = ListEntry('test')
        entry.value = None
        self.assertIs(None, entry.find_one(String, value='foo'))

    def test_list_entry_extend_existing(self):
        ab = List('* foo\n** a\n** b\n')[0]
        cd = List('* foo\n** c\n** d\n')[0]
        ab.extend(cd.sub_list)
        self.assert_equal([ListEntry(f'* {c}') for c in 'abcd'], ab.children)

    def test_list_entry_extend_new(self):
        entry = ListEntry('test')
        entry.extend(List('* foo\n** a\n** b\n')[0])
        self.assert_equal([ListEntry(f'* {c}') for c in 'ab'], entry.children)

    def test_list_entry_extend_dict(self):
        # TODO: Cleanup the implementation around this... this is a mess
        expected = {'a': ListEntry('** 1\n** 2\n'), 'b': ListEntry('; b\n: 3')}
        # expected = {'a': ListEntry(':: 1\n:: 2\n'), 'b': ListEntry('; b\n: 3')}
        # expected = {'a': ListEntry(': 1\n: 2\n'), 'b': ListEntry('; b\n: 3')}
        self.assert_equal(expected, List('; a\n: 1\n: 2\n; b\n: 3').as_dict())

    def test_list_entry_extend_no_convert_no_children(self):
        entry = ListEntry('* foo')
        entry._extend('bar', False)
        self.assert_equal('* foo\n** bar', entry.raw.string)
        self.assert_equal('** bar', entry._children)

    def test_list_entry_extend_no_convert_with_children(self):
        entry = ListEntry('** foo\n** bar')
        entry._extend('baz', False)
        self.assert_equal('** foo\n** bar\n** baz', entry.raw.string)
        self.assert_equal('** foo\n** bar\n** baz', entry._children)

    def test_list_as_dict(self):
        content = "; Artist\n: [[Girls' Generation]]\n; Album\n: MR. TAXI\n; Released\n: 2011.12.14"
        expected = {
            'Artist': ListEntry("; Artist\n: [[Girls' Generation]]"),
            'Album': ListEntry('; Album\n: MR. TAXI'),
            'Released': ListEntry('; Released\n: 2011.12.14'),
        }
        node = List(content)
        self.assert_equal(expected, node.as_mapping(multiline=True).children)
        self.assert_equal(expected, node.as_mapping().children)
        self.assert_equal(expected, node.as_dict())

    def test_list_as_dict_alt_keys(self):
        node = List('; [[foo]]\n: bar\n; [[foo]] bar\n: baz\n; [[foo|bar]]\n: 123')
        expected = {
            'foo': ListEntry('; [[foo]]\n: bar'),
            '[[foo]] bar': ListEntry('; [[foo]] bar\n: baz'),
            'bar': ListEntry('; [[foo|bar]]\n: 123'),
        }
        self.assert_equal(expected, node.as_dict())

    def test_list_as_inline_dict(self):
        content = "*'''Language:''' Korean, English\n*'''Release Date:''' 2015-Apr-01\n*'''Number of Tracks:''' 2\n"
        node = List(content)
        expected = {'Language': 'Korean, English', 'Release Date': '2015-Apr-01', 'Number of Tracks': '2'}
        self.assert_equal(expected, node.as_dict(multiline=False))

    def test_processed_dict(self):
        content = dedent("""
        ; Artist
        : [[Girls' Generation]]
        ; Album
        : MR. TAXI
        ; Released
        : 2011.12.14
        ; Tracklist
        # [[Mr. Taxi (song)|MR. TAXI]]
        # [[The Boys (song)|The Boys]]
        # [[Telepathy (Girls' Generation)|Telepathy]] (텔레파시)
        """).strip()
        expected = {
            'Artist': ListEntry("; Artist\n: [[Girls' Generation]]"),
            'Album': ListEntry('; Album\n: MR. TAXI'),
            'Released': ListEntry('; Released\n: 2011.12.14'),
            'Tracklist': List('\n'.join(content.splitlines()[-3:])),
        }
        self.assert_equal(expected, Root(content).sections.processed()[0].children)

    def test_list_iter_flat(self):
        # expected = [ListEntry('* foo'), ListEntry('** a'), ListEntry('** b')]
        expected = ['foo', 'a', 'b', 'c']
        self.assert_equal(expected, list(List('* foo\n** a\n** b\n*\n** c\n').iter_flat()))

    # endregion


if __name__ == '__main__':
    main(exit=False, verbosity=2)

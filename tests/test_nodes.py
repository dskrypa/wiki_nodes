#!/usr/bin/env python

from functools import lru_cache
from pathlib import Path
from unittest import main
from unittest.mock import Mock

from wikitextparser import WikiText

from wiki_nodes import as_node, Root, Link, List, String, Template, CompoundNode, Tag, Node, BasicNode, MappingNode
from wiki_nodes.exceptions import NoLinkTarget
from wiki_nodes.nodes import ListEntry, TableSeparator, Table, Section
from wiki_nodes.page import WikiPage
from wiki_nodes.testing import WikiNodesTest, RedirectStreams, mocked_client

SITE = 'en.wikipedia.org'
DATA_DIR = Path(__file__).resolve().parent.joinpath('data', 'test_nodes')


@lru_cache(5)
def load_data(name: str) -> str:
    return DATA_DIR.joinpath(name).read_text('utf-8')


def get_page(name: str, title: str, site: str = SITE) -> WikiPage:
    return WikiPage(title, SITE, load_data(name), client=mocked_client(site))


class NodeParsingTest(WikiNodesTest):
    # region as_node

    def test_no_content(self):
        self.assertIs(None, as_node(' '))

    def test_no_lists(self):
        node = as_node("""'''Kim Tae-hyeong''' ({{Korean\n    | hangul  = 김태형\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}; born February 11, 1988), better known as '''Paul Kim''' ({{Korean\n    | hangul  = 폴킴\n    | hanja   =\n    | rr      =\n    | mr      =\n    | context =\n}}) is a South Korean singer. He debuted in 2014 and has released two extended plays and one full-length album in two parts: ''The Road'' (2017) and ''Tunnel'' (2018).""")
        self.assertTrue(not any(isinstance(n, List) for n in node))

    def test_str_link_str(self):
        node = as_node(""""[[title|text]]" - 3:30""")
        expected = CompoundNode('"[[title|text]]" - 3:30')
        expected.children.extend([String('"'), Link.from_title('title', text='text'), String('" - 3:30')])
        self.assertEqual(node, expected)

    def test_self_closing_tag(self):
        self.assertIsInstance(as_node('<ref name="DeluxeCD"/>'), Tag)
        self.assertIsInstance(as_node('<ref name="DeluxeCD"/>', strict_tags=True), Tag)
        self.assertIsInstance(as_node('<br/>'), Tag)
        self.assertIsInstance(as_node('<br/>', strict_tags=True), Tag)

    def test_unclosed_tag(self):
        self.assertIsInstance(as_node('<br>'), Tag)
        self.assertIsInstance(as_node('<br>', strict_tags=True), String)

    # def test

    # endregion

    # region repr & pprint

    def test_node_repr(self):
        self.assertEqual('<Node()>', repr(Node('test')))
        self.assertEqual("<BasicNode(WikiText('test'))>", repr(BasicNode('test')))
        self.assertEqual('<CompoundNode[]>', repr(CompoundNode('test')))
        self.assertEqual("<Tag[br]['\\n']>", repr(Tag('<br/>')))
        self.assertEqual("<ListEntry(<String('test')>)>", repr(ListEntry('test')))
        self.assertEqual("<Template('n/a': None)>", repr(Template('{{n/a}}')))
        self.assertEqual("<Section[2: foo]>", repr(Section('==foo==', None)))

    def test_raw_pprint(self):
        with RedirectStreams() as streams:
            Link('[[test]]').pprint('raw')

        self.assert_strings_equal('[[test]]\n', streams.stdout)

    def test_pprint(self):
        with RedirectStreams() as streams:
            Link('[[test]]').pprint(recurse=True)

        self.assert_strings_equal("<Link:'[[test]]'>\n", streams.stdout)

    def test_pprint_nothing(self):
        with RedirectStreams() as streams:
            Link('[[test]]').pprint('headers')
            Link('[[test]]').pprint('test123')

        self.assertEqual('', streams.stdout)

    def test_pprint_recurse(self):
        with RedirectStreams() as streams:
            as_node("'''foo''' [[bar]]").pprint(recurse=True)

        expected = (
            """<CompoundNode[\n    <String("'''foo'''")>,\n    <Link:'[[bar]]'>\n]>\n"""
            """    <String("'''foo'''")>\n    <Link:'[[bar]]'>\n"""
        )
        self.assertEqual(expected, streams.stdout)

    def test_compound_rich_repr(self):
        node = as_node("'''foo''' [[bar]]")
        self.assertEqual(node.children, list(node.__rich_repr__()))

    def test_mapping_rich_repr(self):
        node = MappingNode('', content={'a': '1', 'b': '2'})
        self.assertEqual(node.children, dict(node.__rich_repr__()))

    def test_tag_rich_repr(self):
        self.assertEqual(['br', ('attrs', {})], list(Tag('<br/>').__rich_repr__()))

    def test_table_rich_repr(self):
        table = Table('{|\n! a !! b !! c\n|-\n| 1 || 2 || 3\n|-\n| 4 || 5 || 6\n|}')
        expected = [('caption', None, None), ('headers', ['a', 'b', 'c']), ('children', table.children)]
        self.assertEqual(expected, list(table.__rich_repr__()))

    def test_template_rich_repr(self):
        self.assertEqual(['n/a', None], list(Template('{{n/a}}').__rich_repr__()))

    # endregion

    # region Basics

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

    def test_basic_node_set(self):
        self.assertSetEqual({BasicNode('test')}, {BasicNode('test'), BasicNode('test')})

    def test_node_strings(self):
        text = '  test  '
        self.assertListEqual([text], list(Node(text).strings(False)))
        self.assertListEqual(['test'], list(Node(text).strings()))
        self.assertListEqual(['test'], list(String(text).strings(False)))  # the value is stripped in init
        self.assertListEqual(['test'], list(String(text).strings()))

    # endregion

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

    def test_compound_copy_with_children(self):
        node = CompoundNode.from_nodes([String('foo'), String('bar')])
        clone = node.copy()
        self.assertEqual(node, clone)
        self.assertIsNot(node[0], clone[0])
        self.assertIsNot(node[1], clone[1])

    def test_compound_copy_no_children(self):
        node = CompoundNode('test')
        self.assertEqual(node, node.copy())

    # endregion

    # region MappingNode

    def test_mapping_only_basic(self):
        self.assertFalse(MappingNode('', content={'a': '1', 'b': '2'}).only_basic)

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

    def test_mapping_get_case_insensitive_alt_ket_type(self):
        self.assertIs(None, MappingNode('', content={'a': 1, 1: 1}).get('b', case_sensitive=False))

    def test_mapping_copy(self):
        node = MappingNode('', content={'a': String('foo'), 'b': String('bar')})
        clone = node.copy()
        self.assertEqual(node, clone)
        self.assertIsNot(node['a'], clone['a'])

    # endregion

    # region Tag

    def test_invalid_raw(self):
        with self.assertRaisesRegex(ValueError, 'Invalid wiki Tag value'):
            Tag('[[test]]')

    def test_tag_basic(self):
        self.assertTrue(Tag('<br/>').is_basic)
        self.assertTrue(Tag('<hr/>').is_basic)
        self.assertFalse(Tag('<ref>{{foo|[[bar]]|[[baz]]}}</ref>').is_basic)

    def test_tag_strings(self):
        self.assertListEqual(['bar', 'baz'], list(Tag('<ref>{{foo|[[bar]]|[[baz]]}}</ref>').strings()))

    def test_tag_find_all(self):
        tag = Tag('<b>[[foo]]</b>')
        self.assertEqual([Link('[[foo]]')], list(tag.find_all(Link, title='foo')), f'No match found in {tag.value!r}')
        self.assertEqual([], list(tag.find_all(Template)))
        self.assertEqual([], list(Tag('<br/>').find_all(Template)))
        self.assertEqual([], list(Tag('<hr/>').find_all(Template)))

    def test_tag_attrs(self):
        tag = Tag('<gallery spacing="small"></gallery>')
        self.assertEqual('small', tag['spacing'])
        self.assertEqual('small', tag.get('spacing'))
        self.assertIs(None, tag.get('bar'))

    def test_tag_copy(self):
        tag = Tag('<b>[[foo]]</b>')
        clone = tag.copy()
        self.assertEqual(tag, clone)
        self.assertIsNot(tag.value, clone.value)

    # endregion

    # region String

    def test_stripped_style(self):
        self.assertEqual('test', String("'''test'''").stripped())

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

    def test_link(self):
        self.assertIsInstance(as_node("""[[test]]"""), Link)

    def test_bad_link(self):
        with self.assertRaisesRegex(ValueError, 'Link init attempted with non-link'):
            Link('{{foo}}')

    def test_link_normalize_index(self):
        link = Link.normalize_raw('[[a]] [[b]]', 1)
        self.assertEqual('b', link.title)

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

    def test_link_strings(self):
        self.assertListEqual(['bar'], list(Link('[[foo|bar]]').strings()))
        self.assertListEqual(['foo'], list(Link('[[foo]]').strings()))
        self.assertListEqual([], list(Link('[[ ]]').strings()))

    def test_link_copy(self):
        link = Link('[[foo]]', root=Mock(site='wiki.bar.com'))
        clone = link.copy()
        self.assertEqual(link, clone)
        self.assertEqual(link.source_site, clone.source_site)

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
        entry.extend(List('* foo\n** a\n** b\n')[0].sub_list)
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

    def test_list_iter_flat(self):
        # expected = [ListEntry('* foo'), ListEntry('** a'), ListEntry('** b')]
        expected = ['foo', 'a', 'b', 'c']
        self.assert_equal(expected, list(List('* foo\n** a\n** b\n*\n** c\n').iter_flat()))

    def test_list_strings(self):
        self.assertListEqual(['foo', 'bar', 'baz'], list(List('* foo\n** bar\n** baz\n').strings()))

    def test_list_copy(self):
        node = List('* foo\n** bar\n** baz\n')
        _ = node.children  # populate the cached property
        clone = node.copy()
        self.assertEqual(node, clone)

    # endregion

    # region Table

    def test_table_sep(self):
        ts = TableSeparator('foo')
        self.assert_equal("<TableSeparator('foo')>", repr(ts))
        self.assert_equal("<TableSeparator['foo']>", ts.pformat())
        self.assertListEqual(['foo'], list(ts.strings()))
        self.assertEqual(ts, ts.copy())
        self.assertEqual(1, len({ts, ts, ts}))
        self.assertNotEqual(ts, 'foo')

    def test_table_basics(self):
        table = Table('{|\n! a !! [[b]] !! c\n|-\n| 1 || 2 || 3\n|-\n| 4 || 5 || 6\n|}')
        self.assert_equal(['a', 'b', 'c'], table.headers)
        expected = [{'a': '1', 'b': '2', 'c': '3'}, {'a': '4', 'b': '5', 'c': '6'}]
        self.assert_equal(expected, [row.children for row in table.children])

    def test_table_no_rows(self):
        self.assertEqual([], Table('{|\n! a !! b !! c\n|}').rows)

    def test_table_no_headers(self):
        self.assertEqual([], Table('{|\n|\n* [[foo]]\n* [[bar]]\n|\n* [[baz]]\n|}').headers)

    def test_table_strings(self):
        table = Table('{|\n! a !! [[b]] !! c\n|-\n| 1 || 2 || 3\n|-\n| 4 || 5 || 6\n|}')
        expected = ['a', 'b', 'c', '1', '2', '3', '4', '5', '6']
        self.assertListEqual(expected, list(table.strings()))

    def test_table_copy(self):
        table = Table('{|\n! a !! [[b]] !! c\n|-\n| 1 || 2 || 3\n|-\n| 4 || 5 || 6\n|}')
        self.assertEqual(table, table.copy())

    # endregion

    # region Template

    def test_tmpl_get_error(self):
        with self.assertRaisesRegex(TypeError, 'Cannot index a template with no value'):
            _ = Template('{{n/a}}')[0]

    def test_tmpl_find_all_none(self):
        self.assertIs(None, Template('{{n/a}}').find_one(Link))

    def test_tmpl_find_all_non_node_value(self):
        tmpl = Template('{{about}}', root=Mock(title='foo', site='bar'))
        self.assertEqual('foo_(disambiguation)', tmpl.find_one(Link).title)
        self.assertIs(None, tmpl.find_one(Table))

    def test_tmpl_pformat_node(self):
        self.assert_strings_equal("<Template['n/a'][None]>", Template('{{n/a}}').pformat())
        self.assert_strings_equal("<Template['small'][<Link:'[[foo]]'>]>", Template('{{small|[[foo]]}}').pformat())

        expected = "<Template['foo'][[<String('bar')>, <String('baz')>]]>"
        self.assert_strings_equal(expected, Template('{{foo|bar|baz}}').pformat())

        compound = "        <String('foo')>,\n        <Link:'[[bar]]'>"
        expected = f"<Template['test'][\n    <CompoundNode[\n{compound}\n    ]>\n]>"
        self.assert_strings_equal(expected, Template('{{test|foo [[bar]]}}').pformat())

        tmpl = Template('{{test}}')
        tmpl.__dict__['value'] = [as_node('foo [[bar]]'), String('baz')]
        expected = f"<Template['test'][[\n    CompoundNode(\n{compound}\n    ),\n    <String('baz')>\n]]>"
        self.assert_strings_equal(expected, tmpl.pformat(max_width=10))

    def test_tmpl_copy(self):
        tmpl = Template('{{small|[[foo]]}}')
        clone = tmpl.copy()
        self.assertEqual(tmpl, clone)
        self.assertIsNot(tmpl.value, clone.value)

    # endregion

    # region Root

    def test_root_from_wiki_text(self):
        self.assertIn('foo', Root(WikiText('==foo==')))

    def test_root_getitem(self):
        self.assertIsInstance(Root('==foo==')['foo'], Section)

    def test_root_iter(self):
        self.assertEqual(['', 'foo'], [s.title for s in Root('==foo==\n===bar===\n')])

    # endregion

    # region Section

    def test_sections(self):
        node = Root('==one==\n[[test]]\n==two==\n{{n/a}}\n===two a===', site=SITE)
        root_section = node.sections
        self.assertEqual(2, root_section.depth)
        self.assertEqual(2, len(root_section.children))
        self.assertEqual(0, len(root_section['one'].children))
        self.assertEqual(Link('[[test]]', root=node), root_section['one'].content)
        self.assertEqual(1, len(root_section['two'].children))
        self.assertEqual(Template('{{n/a}}'), root_section['two'].content)
        self.assertIs(None, root_section['two']['two a'].content)

    def test_section_parents(self):
        node = Root('==a==\n===b===\n==c==\n====d====\n==e==\n===f===\n====g====\n===h===\n====i====\n')
        root = node.sections
        self.assertIn('b', root['a'])
        self.assertIn('d', root['c'])
        self.assertIn('f', root['e'])
        self.assertIn('g', root['e']['f'])
        self.assertIn('h', root['e'])
        self.assertIn('i', root['e']['h'])

    def test_section_strings(self):
        self.assertListEqual(['foo', 'foo', 'bar'], list(Section("==foo==\n'''foo''' [[bar]]", Mock()).strings()))
        node = Root('==a==\n===b===\n==c==\n====d====\n==e==\n===f===\n====g====\n===h===\n====i====\n')
        self.assertListEqual(list('abcdefghi'), list(node.strings()))

    def test_section_no_subsections_bool_true(self):
        self.assertTrue(Section('==foo==', Mock()))

    def test_section_getitem(self):
        section = Root('==foo==\n===bar===\n', Mock()).sections
        with self.assertRaises(KeyError):
            _ = section['baz']

        self.assertEqual('foo', section[0].title)

    def test_section_contains(self):
        section = Root('==foo==\n===bar===\n', Mock()).sections
        self.assertNotIn('baz', section)
        self.assertNotIn(None, section)
        self.assertNotIn(-1, section)
        self.assertIn(0, section)
        self.assertIn('foo', section)

    def test_section_find_from_child(self):
        section = Root('==foo==\n===bar===\n', Mock()).sections
        self.assertEqual('bar', section.find_section('Bar', case_sensitive=False).title)
        self.assertIs(None, section.find('baz', None))

    def test_section_pprint(self):
        with RedirectStreams() as streams:
            Section('==foo==', Mock()).pprint()

        self.assertEqual('<Section[2: foo]>\n', streams.stdout)
        self.assertIs(None, Section('==foo==', Mock()).pprint(_print=Mock(side_effect=OSError(22, 'test'))))
        with self.assertRaises(OSError):
            Section('==foo==', Mock()).pprint(_print=Mock(side_effect=OSError(23, 'test')))

    def test_section_pformat(self):
        section = Section('==foo==', Mock())
        self.assertEqual('==foo==', section.pformat('headers', recurse=False))
        self.assertEqual('==foo==', section.pformat('raw'))
        self.assertEqual('==foo==', section.pformat('raw-pretty'))
        self.assertEqual('', section.pformat('test123'))
        self.assertEqual('<Section[2: foo]>\nNone', section.pformat('content'))
        self.assertEqual("<Section[2: foo]>\n    <String('bar')>", Section('==foo==\nbar', Mock()).pformat('content'))
        section = Root('==foo==\n===bar===\n', Mock()).sections
        self.assertEqual('\n    ==foo==\n        ===bar===', section.pformat('headers'))

    def test_section_copy(self):
        node = Root('==one==\n[[test]]\n==two==\n{{n/a}}\n===two a===', site=SITE)
        _ = node.sections  # populate the cached property
        clone = node.copy()
        self.assertEqual(node, clone)
        self.assertIsNot(node['one'], clone['one'])
        self.assertIsNot(node['one'].parent, clone['one'].parent)
        self.assertIs(clone['one'].parent, clone.sections)

    # endregion


class PageExcerptParsingTest(WikiNodesTest):
    def test_mapping_get_case_insensitive(self):
        page = get_page('d_addicts_our_blues.wiki', 'Our Blues', 'wiki.d-addicts.com')
        details = page.sections.find_section('Details').content.as_mapping()
        self.assertIs(None, details.get('Original Soundtrack'))
        self.assertIsInstance(details.get('Original Soundtrack', case_sensitive=False), Link)

    def test_multi_line_keys(self):
        page = get_page('wikipedia_no_gods_no_masters.wiki', 'No Gods No Masters (Garbage album)')
        table = page.find_section('Charts').find_one(Table)
        self.assertListEqual(['Chart (2021)', 'Peak position'], table.headers)

    def test_release_history(self):
        page = get_page('wikipedia_no_gods_no_masters.wiki', 'No Gods No Masters (Garbage album)')
        table = page.find_section('Release History', case_sensitive=False).find_one(Table)
        self.assertListEqual(['Region', 'Date', 'Label', 'Distributor', 'Format(s)'], table.headers)
        self.assertEqual(4, len(table.children))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

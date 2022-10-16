#!/usr/bin/env python

from pathlib import Path
from unittest import main
from unittest.mock import Mock

from wiki_nodes import as_node, Template, Link, Tag, String, MappingNode
from wiki_nodes.nodes.handlers.base import NodeHandler, _with_parent_domains
from wiki_nodes.nodes.handlers.tags import GalleryHandler, NoWikiHandler
from wiki_nodes.nodes.handlers.templates import LangPrefixHandler, NullHandler
from wiki_nodes.testing import WikiNodesTest

DATA_DIR = Path(__file__).resolve().parent.joinpath('data', 'test_handlers')


def load_data(name: str) -> str:
    return DATA_DIR.joinpath(name).read_text('utf-8')


class BaseHandlerTest(WikiNodesTest):
    def test_missing_class_init_arg(self):
        with self.assertRaisesRegex(TypeError, 'Missing required keyword argument for class=Foo init'):
            class Foo(NodeHandler):
                def get_name(cls, node) -> str:
                    return ''

    def test_no_handler_registered(self):
        with self.assertRaisesRegex(TypeError, 'No node handlers have been registered for String nodes'):
            NodeHandler.for_node(String('test'))

    def test_no_parent_domains(self):
        self.assertListEqual(['foo', None], _with_parent_domains('foo'))
        self.assertListEqual(['', None], _with_parent_domains(''))


class TagTest(WikiNodesTest):
    def test_gallery_tag(self):
        tag = Tag(
            '<gallery captionalign="center" hideaddbutton="true" orientation="square" spacing="small" widths="150">\n'
            'Start-Up OST Album packaging preview.png|Album packaging preview\n'
            'File:test_example.jpg'
            '</gallery>'
        )
        self.assertEqual('gallery', tag.name)
        self.assertIsInstance(tag.handler, GalleryHandler)
        expected = [
            Link.from_title('File:Start-Up OST Album packaging preview.png', text='Album packaging preview'),
            Link.from_title('File:test_example.jpg'),
        ]
        self.assertListEqual(expected, tag.value)

    def test_nowiki_tag(self):
        node = as_node('<nowiki>[[test]]</nowiki>')
        self.assertIsInstance(node, Tag)
        self.assertIsInstance(node.handler, NoWikiHandler)
        self.assertEqual(String('[[test]]'), node.value)

    def test_link_in_tag(self):
        root = Mock(site='en.wikipedia.org')
        tag = Tag('<b>[[test]]</b>', root=root)
        self.assertEqual(Link('[[test]]', root=root), tag.value)


class TemplateTest(WikiNodesTest):
    def test_handler_for_generic_na(self):
        self.assertIsInstance(Template('{{n/a}}').handler, NullHandler)

    def test_handler_for_generic_prefix_lang(self):
        self.assertIsInstance(Template('{{lang-na}}').handler, LangPrefixHandler)
        self.assertIsInstance(Template('{{lang-ko}}').handler, LangPrefixHandler)

    def test_generic_handler(self):
        tmpl = Template('{{test123 | [[test]]}}')
        self.assertEqual(Link('[[test]]'), tmpl.value)
        self.assertTrue(tmpl.is_basic)
        self.assertIs(None, tmpl.handler.get_default_value())

    def test_nowiki_handler(self):
        tmpl = Template('{{nowiki | [[test]]}}')
        self.assertEqual(String('[[test]]'), tmpl.value)
        self.assertTrue(tmpl.is_basic)
        self.assertIs(None, Template('{{nowiki}}').value)
        self.assertEqual([String('a'), String('b')], Template('{{nowiki|a|b}}').value)

    def test_abbr_handler(self):
        self.assertIs(None, Template('{{abbr}}').value)
        self.assertEqual(['a'], Template('{{abbr|a}}').value)
        self.assertEqual(['abbr', 'abbreviation'], Template('{{abbr|abbr|abbreviation}}').value)

    def test_na_handler(self):
        self.assertTrue(Template('{{n/a}}').is_basic)
        self.assertIs(None, Template('{{n/a}}').value)
        self.assertEqual('N/A', Template('{{n/a|}}').value)
        self.assertEqual('unavailable', Template('{{n/a|unavailable}}').value)

    def test_wp_handler(self):
        root = Mock(site='kpop.fandom.com')
        self.assertIs(None, Template('{{wp}}', root=root).value)
        self.assertEqual(Link('[[wikipedia:ko:test]]', root=root), Template('{{wp|ko|test}}', root=root).value)
        self.assertEqual(Link('[[wikipedia:ko:foo|bar]]', root), Template('{{wp|ko|foo|bar}}', root=root).value)
        self.assertEqual(['ko', 'foo', 'bar', 'baz'], Template('{{wp|ko|foo|bar|baz}}', root=root).value)

    def test_infobox_is_not_basic(self):
        self.assertFalse(Template('{{infobox}}').is_basic)

    def test_tracklist_empty(self):
        self.assertIs(None, Template('{{tracklist}}', root=Mock(site='en.wikipedia.org')).value)

    def test_tracklist_value(self):
        root = Mock(site='en.wikipedia.org')
        template = Template(load_data('tracklist_hdl_part_2.wiki'), root=root)
        title = 'Lean On My Shoulders'
        headline = as_node("""Released on {{start date | 1 = 2019 | 2 = 7 | 3 = 20}}<ref>{{cite web
| first1       = Min-ji
| last1        = Lee
| url          = http://newsen.com/news_view.php?uid=201907200903122410
| title        = 십센치, 오늘(20일) '호텔 델루나' OST 공개…아련 감성 발라드 예고
| date         = July 20, 2019
| website      = Newsen
| access-date  = July 21, 2019
| language     = ko
| archive-date = September 28, 2020
| archive-url  = https://web.archive.org/web/20200928115121/https://www.newsen.com/news_view.php?uid=201907200903122410
| url-status   = live}}</ref>""".strip()
        )
        music = Template('{{hlist | 1 = Lee Seung-joo | 2 = Choi In-hwan}}')
        lyrics = Template('{{hlist | 1 = Ji Hoon | 2 = Park Se-jun}}')
        expected = {
            'meta': {'headline': headline, 'extra_column': 'Artist', 'total_length': '7:02', 'all_writing': None},
            'tracks': [
                {
                    'title': title, 'note': '나의 어깨에 기대어요', 'lyrics': lyrics, 'music': music,
                    'extra': Link('[[10cm (singer)|10cm]]', root=root), 'length': '3:31',
                },
                {'title': title, 'note': 'Inst.', 'lyrics': None, 'music': music, 'extra': None, 'length': '3:31'},
            ],
        }
        self.assert_equal(expected, dict(template.value))

    def test_empty_zip(self):
        self.assertIs(None, Template('{{test}}').zipped)

    def test_basic_zip(self):
        tmpl = Template('{{test|k1=a|v1=1|k2=b|v2=2|foo=bar}}')
        expected = MappingNode(tmpl.raw, content={'a': '1', 'b': '2', 'foo': 'bar'})
        self.assert_equal(expected, tmpl.zipped)

    def test_unexpected_zip(self):
        with self.assertLogs('wiki_nodes.nodes.handlers.templates', 'DEBUG') as log_ctx:
            _ = Template('{{test|k1=a|v1=1|k2=b|v2=2|k3=}}').zipped

        self.assertTrue(any('Unexpected zip key=' in line for line in log_ctx.output))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

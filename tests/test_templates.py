#!/usr/bin/env python

from pathlib import Path
from unittest import main
from unittest.mock import Mock

from wiki_nodes import Template, Link, as_node
from wiki_nodes.nodes.templates import LangPrefixHandler, NullHandler, WpHandler
from wiki_nodes.testing import WikiNodesTest

DATA_DIR = Path(__file__).resolve().parent.joinpath('data', 'test_templates')


def load_data(name: str) -> str:
    return DATA_DIR.joinpath(name).read_text('utf-8')


class TemplateTest(WikiNodesTest):
    def test_handler_for_generic_wp_link(self):
        self.assertIsInstance(Template('{{WP|en|Some Title}}').handler, WpHandler)
        self.assertIsInstance(Template('{{WP|en|Some Title|Some alt title}}').handler, WpHandler)

    def test_handler_for_generic_na(self):
        self.assertIsInstance(Template('{{n/a}}').handler, NullHandler)

    def test_handler_for_generic_prefix_lang(self):
        self.assertIsInstance(Template('{{lang-na}}').handler, LangPrefixHandler)
        self.assertIsInstance(Template('{{lang-ko}}').handler, LangPrefixHandler)

    def test_na_is_basic(self):
        self.assertTrue(Template('{{n/a}}').is_basic)

    def test_infobox_is_not_basic(self):
        self.assertFalse(Template('{{infobox}}').is_basic)

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


if __name__ == '__main__':
    main(exit=False, verbosity=2)

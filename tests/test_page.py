#!/usr/bin/env python

from pathlib import Path
from unittest import main

from wiki_nodes import Template, String, Link, as_node
from wiki_nodes.page import WikiPage
from wiki_nodes.testing import WikiNodesTest, mocked_client

SITE = 'en.wikipedia.org'
DATA_DIR = Path(__file__).resolve().parent.joinpath('data', 'test_page')


def load_data(name: str) -> str:
    return DATA_DIR.joinpath(name).read_text('utf-8')


class WikiPageTest(WikiNodesTest):
    def test_repr(self):
        self.assertEqual("<WikiPage['test' @ en.wikipedia.org]>", repr(WikiPage('test', SITE, '')))

    def test_equality(self):
        self.assertEqual(WikiPage('test', None, ''), WikiPage('test', None, ''))
        self.assertEqual(WikiPage('test', 'foo', ''), WikiPage('test', 'foo', ''))
        self.assertNotEqual(WikiPage('test', 'foo', ''), 1)
        self.assertNotEqual(WikiPage('test', 'foo', ''), WikiPage('test', 'bar', ''))
        self.assertNotEqual(WikiPage('test1', 'foo', ''), WikiPage('test2', 'foo', ''))

    def test_sort_order(self):
        a, b, c = WikiPage('foo', None, ''), WikiPage('bar', None, ''), WikiPage('baz', None, '')
        self.assertListEqual([b, c, a], sorted([a, c, b]))
        self.assertListEqual([b, c, a], sorted([a, b, c]))

    def test_set(self):
        a, b, c = WikiPage('foo', None, ''), WikiPage('bar', None, ''), WikiPage('baz', None, '')
        self.assertSetEqual({a, b, c}, {a, b, c, a, b, c, a, b, c})

    def test_no_client_no_url(self):
        with self.assertRaisesRegex(AttributeError, 'Unable to determine URL when not initialized via MediaWikiClient'):
            _ = WikiPage('test', None, '').url

    def test_url(self):
        page = WikiPage('test', None, '', client=mocked_client(SITE))
        self.assertEqual('https://en.wikipedia.org/wiki/test', page.url)

    def test_is_disambiguation(self):
        self.assertTrue(WikiPage('test', None, '', ('disambiguations',)).is_disambiguation)
        self.assertFalse(WikiPage('test', None, '', ('foo', 'bar')).is_disambiguation)

    def test_is_template(self):
        self.assertTrue(WikiPage('Template:foo', None, '').is_template)
        self.assertFalse(WikiPage('foo:bar', None, '').is_template)

    def test_as_link(self):
        self.assertEqual(Link('[[foo]]'), WikiPage('foo', None, '').as_link)

    # region Infobox

    def test_no_infobox(self):
        self.assertIs(None, WikiPage('test', None, '').infobox)
        self.assertIs(None, WikiPage('test', None, "'''foo''' [[bar]]\n").infobox)

    def test_infobox_as_content(self):
        page = WikiPage('test', None, '{{infobox | name = foo}}\n==one==\n')
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    def test_infobox_in_content_beginning(self):
        page = WikiPage('test', None, "{{infobox | name = foo}}'''bar''' baz\n==one==\n")
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    def test_infobox_in_content_middle(self):
        page = WikiPage('test', None, "abc def\n{{infobox | name = foo}}'''bar''' baz\n==one==\n")
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    # endregion

    def test_intro_none(self):
        self.assertIs(None, WikiPage('test', None, '').intro())

    def test_intro_no_infobox(self):
        self.assertEqual(String("'''foo'''"), WikiPage('test', None, "'''foo''' [[bar]]\n").intro())

    def test_intro_with_tags(self):
        page = WikiPage('test', None, "<div>'''foo''' bar [[baz]]</div>")
        self.assertEqual(as_node("'''foo''' bar [[baz]]", root=page), page.intro())

    # region Links

    def test_similar_name_link(self):
        self.assertIs(None, WikiPage('test', None, '').similar_name_link)
        self.assertIs(None, WikiPage('test', None, '{{about}}').similar_name_link)
        self.assertIs(None, WikiPage('test', None, '{{about|foo}}').similar_name_link)
        self.assertEqual('bar', WikiPage('test', None, '{{about|foo||bar}}').similar_name_link.title)
        self.assertEqual('bar', WikiPage('test', None, '{{about||foo|bar}}').similar_name_link.title)
        self.assertEqual('bar', WikiPage('test', None, '{{about||foo|bar|and|baz}}').similar_name_link.title)

    def test_disambiguation_link(self):
        self.assertIs(None, WikiPage('test', None, '').disambiguation_link)
        self.assertIs(None, WikiPage('test', None, '{{about|foo||bar}}').disambiguation_link)
        self.assertIs(None, WikiPage('test', None, '{{about||foo|bar}}').disambiguation_link)
        expected = 'test_(disambiguation)'
        cases = (
            '{{about}}',
            '{{about|foo}}',
            '{{about|foo|bar|baz|other uses}}',
            '{{about|foo|bar|baz|other uses|section=yes}}',
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(expected, WikiPage('test', None, case).disambiguation_link.title)

        cat = 'articles needing clarification'
        self.assertEqual(expected, WikiPage('test', None, '', (f'foo {cat}',)).disambiguation_link.title)

    def test_about_links(self):
        page = WikiPage('test', None, '{{about|abc|def|foo|and|bar|and|baz|other uses|section=yes}}')
        expected = [Link(f'[[{val}]]', page) for val in ('foo', 'bar', 'baz', 'test_(disambiguation)')]
        self.assertListEqual(expected, page.about_links)

    def test_get_links(self):
        page = WikiPage('test', None, '==one==\n[[foo]] blah blah {{test|[[bar]]}}')
        expected = {Link(f'[[{val}]]', page) for val in ('foo', 'bar')}
        self.assertSetEqual(expected, page.links())

    # endregion


class FullPageTests(WikiNodesTest):
    def test_start_up_ost(self):
        site = 'kpop.fandom.com'
        text = load_data('kpop_fandom_Start-Up_OST.wiki')
        page = WikiPage('Start-Up OST', site, text, ['OST'], client=mocked_client(site))
        links = {link.title: link for link in page.find_all(Link)}
        self.assertEqual(6, len(links))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

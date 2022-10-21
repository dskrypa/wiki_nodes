#!/usr/bin/env python

from unittest import main

from wiki_nodes import Template, String, Link
from wiki_nodes.page import WikiPage
from wiki_nodes.testing import WikiNodesTest, mocked_client

SITE = 'en.wikipedia.org'


class WikiPageTest(WikiNodesTest):
    def test_equality(self):
        self.assertEqual(WikiPage('test', None, '', ()), WikiPage('test', None, '', ()))
        self.assertEqual(WikiPage('test', 'foo', '', ()), WikiPage('test', 'foo', '', ()))
        self.assertNotEqual(WikiPage('test', 'foo', '', ()), 1)
        self.assertNotEqual(WikiPage('test', 'foo', '', ()), WikiPage('test', 'bar', '', ()))
        self.assertNotEqual(WikiPage('test1', 'foo', '', ()), WikiPage('test2', 'foo', '', ()))

    def test_sort_order(self):
        a = WikiPage('foo', None, '', ())
        b = WikiPage('bar', None, '', ())
        c = WikiPage('baz', None, '', ())
        self.assertListEqual([b, c, a], sorted([a, c, b]))
        self.assertListEqual([b, c, a], sorted([a, b, c]))

    def test_set(self):
        a = WikiPage('foo', None, '', ())
        b = WikiPage('bar', None, '', ())
        c = WikiPage('baz', None, '', ())
        self.assertSetEqual({a, b, c}, {a, b, c, a, b, c, a, b, c})

    def test_no_client_no_url(self):
        with self.assertRaisesRegex(AttributeError, 'Unable to determine URL when not initialized via MediaWikiClient'):
            _ = WikiPage('test', None, '', ()).url

    def test_url(self):
        page = WikiPage('test', None, '', (), client=mocked_client(SITE))
        self.assertEqual('https://en.wikipedia.org/wiki/test', page.url)

    def test_is_disambiguation(self):
        self.assertTrue(WikiPage('test', None, '', ('disambiguations',)).is_disambiguation)
        self.assertFalse(WikiPage('test', None, '', ('foo', 'bar')).is_disambiguation)

    def test_is_template(self):
        self.assertTrue(WikiPage('Template:foo', None, '', ()).is_template)
        self.assertFalse(WikiPage('foo:bar', None, '', ()).is_template)

    def test_as_link(self):
        self.assertEqual(Link('[[foo]]'), WikiPage('foo', None, '', ()).as_link)

    # region Infobox

    def test_no_infobox(self):
        self.assertIs(None, WikiPage('test', None, '', ()).infobox)
        self.assertIs(None, WikiPage('test', None, "'''foo''' [[bar]]\n", ()).infobox)

    def test_infobox_as_content(self):
        page = WikiPage('test', None, '{{infobox | name = foo}}\n==one==\n', ())
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    def test_infobox_in_content_beginning(self):
        page = WikiPage('test', None, "{{infobox | name = foo}}'''bar''' baz\n==one==\n", ())
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    def test_infobox_in_content_middle(self):
        page = WikiPage('test', None, "abc def\n{{infobox | name = foo}}'''bar''' baz\n==one==\n", ())
        self.assertIsInstance(page.infobox, Template)
        self.assertEqual('foo', page.infobox['name'])

    # endregion

    def test_intro_none(self):
        self.assertIs(None, WikiPage('test', None, '', ()).intro())

    def test_intro_no_infobox(self):
        self.assertEqual(String("'''foo'''"), WikiPage('test', None, "'''foo''' [[bar]]\n", ()).intro())


if __name__ == '__main__':
    main(exit=False, verbosity=2)

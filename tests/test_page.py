#!/usr/bin/env python

from unittest import main

from wiki_nodes import Template
from wiki_nodes.page import WikiPage
from wiki_nodes.testing import WikiNodesTest, mocked_client

SITE = 'en.wikipedia.org'


class WikiPageTest(WikiNodesTest):
    def test_no_client_no_url(self):
        with self.assertRaisesRegex(AttributeError, 'Unable to determine URL when not initialized via MediaWikiClient'):
            _ = WikiPage('test', None, '', ()).url

    def test_url(self):
        page = WikiPage('test', None, '', (), client=mocked_client(SITE))

        self.assertEqual('https://en.wikipedia.org/wiki/test', page.url)

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


if __name__ == '__main__':
    main(exit=False, verbosity=2)

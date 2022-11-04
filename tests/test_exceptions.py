#!/usr/bin/env python

from unittest import main
from unittest.mock import patch

from wiki_nodes import Link
from wiki_nodes.http.client import WikiQuery, MediaWikiClient
from wiki_nodes.exceptions import PageMissingError, NoLinkSite
from wiki_nodes.testing import WikiNodesTest


class ExceptionTest(WikiNodesTest):
    def test_bad_link_site(self):
        with self.assertRaisesRegex(NoLinkSite, 'NoLinkSite: No source site found for link='):
            _ = Link('[[test|Test]]', ).client_and_title

    def test_page_missing_error(self):
        with patch.object(WikiQuery, 'get_pages', return_value={}):
            with self.assertRaisesRegex(PageMissingError, "No page found for 'Foo' in test.example"):
                WikiQuery(MediaWikiClient('test.example'), 'Foo').get_page('Foo')

    def test_page_missing_error_extra(self):
        with patch.object(WikiQuery, 'get_pages', return_value={'Bar': ''}):
            with self.assertRaisesRegex(PageMissingError, "No page found for 'Foo' in test.example but results were"):
                WikiQuery(MediaWikiClient('test.example'), 'Foo').get_page('Foo')


if __name__ == '__main__':
    main(exit=False, verbosity=2)

#!/usr/bin/env python

from unittest import main

from wiki_nodes import MediaWikiClient
from wiki_nodes.testing import WikiNodesTest, mocked_client
from wiki_nodes.version import LooseVersion

SITE = 'en.wikipedia.org'


class WikiClientTest(WikiNodesTest):
    def test_default_scheme_https(self):
        self.assertEqual('https', MediaWikiClient(SITE).scheme)

    def test_mw_version(self):
        self.assertEqual('1.40.0-wmf.6', mocked_client(SITE).mw_version)

    def test_url_for_article(self):
        self.assertEqual('https://en.wikipedia.org/wiki/test', mocked_client(SITE).url_for_article('test'))

    def test_title_from_url(self):
        self.assertEqual('test', mocked_client(SITE).article_url_to_title('https://en.wikipedia.org/wiki/test'))
        self.assertEqual('test', mocked_client(SITE).article_url_to_title('https://en.wikipedia.org/w/wiki/test'))

    def test_merged_interwiki_map(self):
        self.assertIn('arxiv', mocked_client(SITE)._merged_interwiki_map)

    def test_article_url_prefix(self):
        self.assertEqual('https://en.wikipedia.org/w/wiki/', mocked_client(SITE).article_url_prefix)

    def test_update_params(self):
        params = mocked_client(SITE)._update_params({'foo': [1, 2]})
        expected = {'foo': '1|2', 'utf8': 1, 'format': 'json', 'formatversion': 2}
        self.assertDictEqual(expected, params)

    def test_old_version_update_params(self):
        client = mocked_client(SITE)
        client.__dict__['mw_version'] = LooseVersion('1.1')
        self.assertNotIn('formatversion', client._update_params({}))

    def test_prepare_query_params_basic(self):
        params = mocked_client(SITE)._prepare_query_params({})
        expected = {'action': 'query', 'redirects': 1}
        self.assertDictEqual(expected, params)


if __name__ == '__main__':
    main(exit=False, verbosity=2)

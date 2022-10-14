#!/usr/bin/env python

from unittest import main, TestCase
from unittest.mock import MagicMock, patch

from wiki_nodes import MediaWikiClient, Link, Template

KPOP_FANDOM_IW_MAP = {'w': 'https://community.fandom.com/wiki/$1', 'wikipedia': 'http://en.wikipedia.org/wiki/$1'}


class LinkHandlingTestCase(TestCase):
    @patch('wiki_nodes.http.MediaWikiClient.interwiki_map', KPOP_FANDOM_IW_MAP)
    def test_interwiki_client(self, *mocks):
        root = MagicMock(site='kpop.fandom.com', _interwiki_map=KPOP_FANDOM_IW_MAP)
        link = Link('[[w:c:kindie:test|Test]]', root)
        self.assertTrue(link.interwiki)
        self.assertEqual(link.iw_key_title, ('w:c:kindie', 'test'))

        client = MediaWikiClient(root.site)
        self.assertEqual(len(client.interwiki_map), len(KPOP_FANDOM_IW_MAP))  # sanity check that patch worked
        iw_client = client.interwiki_client('w:c:kindie')
        self.assertEqual(iw_client.host, 'kindie.fandom.com')

    @patch('wiki_nodes.http.MediaWikiClient.interwiki_map', KPOP_FANDOM_IW_MAP)
    @patch('wiki_nodes.http.MediaWikiClient.article_path_prefix', 'wiki/')
    def test_wp_template_1(self, *mocks):
        root = MagicMock(site='kpop.fandom.com', _interwiki_map=KPOP_FANDOM_IW_MAP)
        link = Template('{{WP|en|Some Title}}', root).value
        self.assertIsInstance(link, Link)
        self.assertTrue(link.interwiki)
        self.assertEqual(link.iw_key_title, ('wikipedia', 'en:Some Title'))
        self.assertEqual(link.url, 'http://en.wikipedia.org/wiki/en:Some_Title')
        self.assertNotIn('siteinfo', MediaWikiClient('http://en.wikipedia.org').__dict__)  # patch sanity check

    @patch('wiki_nodes.http.MediaWikiClient.interwiki_map', KPOP_FANDOM_IW_MAP)
    @patch('wiki_nodes.http.MediaWikiClient.article_path_prefix', 'wiki/')
    def test_wp_template_2(self, *mocks):
        root = MagicMock(site='kpop.fandom.com', _interwiki_map=KPOP_FANDOM_IW_MAP)
        link = Template('{{WP|ko|Some Title|Some Title in Korean}}', root).value
        self.assertIsInstance(link, Link)
        self.assertTrue(link.interwiki)
        self.assertEqual(link.iw_key_title, ('wikipedia', 'ko:Some Title'))
        self.assertEqual(link.show, 'Some Title in Korean')
        self.assertEqual(link.url, 'http://en.wikipedia.org/wiki/ko:Some_Title')
        self.assertNotIn('siteinfo', MediaWikiClient('http://en.wikipedia.org').__dict__)  # patch sanity check


if __name__ == '__main__':
    main(exit=False, verbosity=2)

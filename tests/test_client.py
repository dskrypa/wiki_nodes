#!/usr/bin/env python

from copy import deepcopy
from io import BytesIO
from json import JSONDecodeError
from unittest import main
from unittest.mock import Mock, patch

from wiki_nodes import MediaWikiClient
from wiki_nodes.exceptions import InvalidWikiError
from wiki_nodes.http.query import Query
from wiki_nodes.http.utils import _normalize_params
from wiki_nodes.testing import WikiNodesTestBase, WikiNodesTest, mocked_client, get_siteinfo
from wiki_nodes.testing import get_api_resp_data, mock_response, wiki_cache
from wiki_nodes.version import LooseVersion

SITE = 'en.wikipedia.org'
KPOP_FANDOM = 'kpop.fandom.com'


class WikiClientNoCacheMocksTest(WikiNodesTestBase):
    def setUp(self):
        MediaWikiClient._instances.clear()
        MediaWikiClient._siteinfo_cache = None

    tearDown = setUp

    def test_client_siteinfo_cache_init(self):  # noqa
        with patch('wiki_nodes.http.client.TTLDBCache') as ttl_db_cache_mock:
            MediaWikiClient(SITE)
            ttl_db_cache_mock.assert_called()

    def test_client_siteinfo(self):
        get_mocks = [mock_response({'query': get_siteinfo(SITE)}), Mock()]
        MediaWikiClient._siteinfo_cache = {}
        with patch.object(MediaWikiClient, 'get', side_effect=get_mocks):
            client = MediaWikiClient(SITE)
            self.assertEqual(2, len(client.siteinfo))
            get_mocks[0].json.assert_called()
            self.assertEqual(2, len(client.siteinfo))
            get_mocks[1].json.assert_not_called()

    def test_get_page_image_urls(self):
        title = 'I Made'
        expected = {
            'File:(G)I-DLE I Made announcement teaser.png': 'https://static.wikia.nocookie.net/kpop/images/a/a6/%28G%29I-DLE_I_Made_announcement_teaser.png/revision/latest?cb=20190210153031',
            'File:(G)I-DLE I Made tracklist.png': 'https://static.wikia.nocookie.net/kpop/images/4/4b/%28G%29I-DLE_I_Made_tracklist.png/revision/latest?cb=20190213210133',
            'File:(G)I-DLE I Made physical album cover.png': 'https://static.wikia.nocookie.net/kpop/images/8/8c/%28G%29I-DLE_I_Made_physical_album_cover.png/revision/latest?cb=20190218052609',
            'File:(G)I-DLE I Made digital cover art.png': 'https://static.wikia.nocookie.net/kpop/images/b/b0/%28G%29I-DLE_I_Made_digital_cover_art.png/revision/latest?cb=20190307015212',
        }

        with self.subTest(method='get_page_image_urls'), wiki_cache('', base_dir=':memory:') as cache:
            with patch.object(MediaWikiClient, 'get', return_value=mock_response(get_api_resp_data('i_made_images'))):
                client = mocked_client(KPOP_FANDOM, wiki_cache=cache)
                page_img_url_map = client.get_page_image_urls(title)
                self.assertEqual(1, len(page_img_url_map))
                self.assertDictEqual(expected, page_img_url_map[title])
                self.assertDictEqual({title: expected}, client.get_page_image_urls(title))  # test from cache

        responses = [
            mock_response(get_api_resp_data('i_made_image_titles')),
            mock_response(get_api_resp_data('i_made_images')),
        ]
        with self.subTest(method='get_page_image_urls_bulk'), wiki_cache('', base_dir=':memory:') as cache:
            with patch.object(MediaWikiClient, 'get', side_effect=responses):
                client = mocked_client(KPOP_FANDOM, wiki_cache=cache)
                page_img_url_map = client.get_page_image_urls_bulk(title)
                self.assertEqual(1, len(page_img_url_map))
                self.assertDictEqual(expected, page_img_url_map[title])
                self.assertDictEqual({title: expected}, client.get_page_image_urls_bulk(title))  # test from cache


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

    def test_normalize_params(self):
        params = _normalize_params({'foo': [1, 2]}, mocked_client(SITE).mw_version)
        expected = {'foo': '1|2', 'utf8': 1, 'format': 'json', 'formatversion': 2}
        self.assertDictEqual(expected, params)

    def test_old_version_normalize_params(self):
        self.assertNotIn('formatversion', _normalize_params({}, LooseVersion('1.1')))

    def test_prepare_query_params_basic(self):
        params = Query(mocked_client(SITE)).params
        expected = {'action': 'query', 'redirects': 1}
        self.assertDictEqual(expected, params)

    def test_client_repr(self):
        self.assertEqual(f'<MediaWikiClient({SITE})>', repr(MediaWikiClient(SITE)))

    def test_client_deepcopy(self):
        with patch('wiki_nodes.http.client.WikiCache'):
            client = MediaWikiClient(SITE)
            clone = deepcopy(client)
            self.assertIs(client, clone)

    def test_client_deepcopy_forced_init(self):
        with patch('wiki_nodes.http.client.WikiCache'):
            client = MediaWikiClient(SITE)
            MediaWikiClient._instances.clear()
            clone = deepcopy(client)
            self.assertFalse(client is clone)

    def test_client_siteinfo_invalid(self):
        MediaWikiClient._siteinfo_cache = {}
        resp = mock_response(JSONDecodeError('', '', 0), url='hxxp://foo/bar')
        with patch.object(MediaWikiClient, 'get', return_value=resp):
            client = MediaWikiClient(SITE)
            with self.assertRaisesRegex(InvalidWikiError, f'Invalid site: {SITE!r}'):
                _ = client.siteinfo

    def test_client_siteinfo_invalid_community(self):
        MediaWikiClient._siteinfo_cache = {}
        resp = mock_response(JSONDecodeError('', '', 0), url='hxxp://foo/Not_a_valid_community/?from=bar')
        with patch.object(MediaWikiClient, 'get', return_value=resp):
            client = MediaWikiClient(SITE)
            with self.assertRaisesRegex(InvalidWikiError, "Invalid site: 'bar'"):
                _ = client.siteinfo

    def test_client_siteinfo_invalid_community_error(self):
        MediaWikiClient._siteinfo_cache = {}
        resp = mock_response(JSONDecodeError('', '', 0), url='hxxp://foo/Not_a_valid_community/')
        with patch.object(MediaWikiClient, 'get', return_value=resp):
            client = MediaWikiClient(SITE)
            with self.assertRaisesRegex(InvalidWikiError, f'Invalid site: {SITE!r}'):
                _ = client.siteinfo

    def test_no_interwiki_client(self):
        client = MediaWikiClient(SITE)
        client.__dict__.update(interwiki_map={}, lc_interwiki_map={})
        self.assertIs(None, client.interwiki_client('foo'))

    def test_article_url_to_title_trailing_query(self):
        self.assertEqual('foo?bar', mocked_client(SITE).article_url_to_title('https://en.wikipedia.org/wiki/foo?bar'))

    def test_query(self):  # noqa
        with patch('wiki_nodes.http.client.Query') as query_mock:
            MediaWikiClient(SITE).query()
            query_mock.assert_called()

    def test_parse(self):  # noqa
        client = MediaWikiClient(SITE)
        with patch('wiki_nodes.http.client.Parse') as parse_mock:
            client.parse()
            parse_mock.assert_called()
        with patch('wiki_nodes.http.client.Parse.page') as parse_mock:
            client.parse_page('foo')
            parse_mock.assert_called_with(client, 'foo')

    def test_get_file_content(self):
        with patch.object(MediaWikiClient, 'get', return_value=mock_response(raw=BytesIO(b'abc'))):
            self.assertEqual((b'abc', 0), MediaWikiClient(SITE)._get_file_content('test'))
        resp = mock_response(raw=BytesIO(b'abc'), headers={'Content-Length': 3})
        with patch.object(MediaWikiClient, 'get', return_value=resp):
            self.assertEqual((b'abc', 3), MediaWikiClient(SITE)._get_file_content('test'))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

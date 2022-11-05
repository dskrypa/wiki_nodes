#!/usr/bin/env python

from unittest import main
from unittest.mock import Mock, patch

from wiki_nodes import MediaWikiClient
from wiki_nodes.exceptions import WikiResponseError
from wiki_nodes.http.query import Query, QueryResponse
from wiki_nodes.testing import WikiNodesTestBase, WikiNodesTest, mocked_client, mock_response, wiki_cache
from wiki_nodes.version import LooseVersion

SITE = 'en.wikipedia.org'
KPOP_FANDOM = 'kpop.fandom.com'


class QueryNoCacheMocksTest(WikiNodesTestBase):
    def setUp(self):
        MediaWikiClient._instances.clear()
        MediaWikiClient._siteinfo_cache = None

    tearDown = setUp

    def test_search(self):
        query_str = '(g)i-dle'
        result = {'ns': 0, 'title': '(G)I-DLE', 'pageid': 21279, 'size': 20924, 'wordcount': 2781, 'snippet': '', 'timestamp': '2022-11-05T07:06:27Z'}
        raw = {'batchcomplete': True, 'query': {'search': [result]}}
        expected = {'(G)I-DLE': result}
        with patch.object(MediaWikiClient, 'get', return_value=mock_response([raw, raw])):
            with wiki_cache('', base_dir=':memory:') as cache:
                client = mocked_client(KPOP_FANDOM, wiki_cache=cache)
                with self.subTest(via='Query'):
                    query = Query.search(client, query_str)
                    self.assertEqual(1, len(query.get_responses()))
                    self.assertEqual(expected, query.get_results())
                    self.assertEqual(expected, query.get_results())  # test from stored responses
                with self.subTest(via='client'):
                    self.assertEqual({'(G)I-DLE': result}, client.search(query_str))
                    with patch.object(Query, 'search') as search_mock:
                        self.assertEqual({'(G)I-DLE': result}, client.search(query_str))  # test from cache
                        search_mock.assert_not_called()


class QueryTest(WikiNodesTest):
    def test_prepare_query_params_basic(self):
        expected = {'action': 'query', 'redirects': 1}
        self.assertDictEqual(expected, Query(mocked_client(SITE)).params)

    def test_prepare_search_params(self):
        expected = {
            'action': 'query', 'redirects': 1, 'list': 'search', 'srsearch': 'foo', 'srlimit': 10, 'sroffset': 10
        }
        self.assertDictEqual(expected, Query.search(mocked_client(SITE), 'foo', None, offset=10).params)

    def test_prepare_all_cats_params(self):
        expected = {'action': 'query', 'redirects': 1, 'list': 'allcategories', 'aclimit': 500}
        self.assertDictEqual(expected, Query(mocked_client(SITE), list='allcategories').params)

    def test_set_properties(self):
        props = {'iwlinks', 'categories', 'revisions'}
        exp_base = {'action': 'query', 'redirects': 1, 'prop': props, 'cllimit': 500}
        client = mocked_client(SITE)
        self.assertDictEqual(exp_base | {'iwprop': 'url', 'rvslots': 'main'}, Query(client, prop=props).params)
        client.__dict__['mw_version'] = LooseVersion('1.20')
        self.assertDictEqual(exp_base | {'iwurl': 1}, Query(client, prop=list(props)).params)

    def test_split_titles(self):
        exp_base = {'action': 'query', 'redirects': 1, 'format': 'json', 'formatversion': 2, 'utf8': 1}
        expected = [exp_base | {'titles': 'a|b|c'}, exp_base | {'titles': 'd|e'}]
        with patch.object(Query, 'max_titles_per_query', 3):
            query = Query(mocked_client(SITE), titles=['a', 'b', 'c', 'd', 'e'])
            self.assertEqual(expected, list(query._param_page_iter()))

    def test_get_resp_dict(self):
        with self.assertLogs('wiki_nodes.http.query', 'DEBUG') as log_ctx:
            QueryResponse(Mock(), mock_response({})).parse()
            self.assertTrue(any('was empty.' in line for line in log_ctx.output))
        with self.assertLogs('wiki_nodes.http.query', 'DEBUG') as log_ctx:
            QueryResponse(Mock(), mock_response([[None]]))._get_resp_dict()
            self.assertTrue(any('was not a dict; found: [None]' in line for line in log_ctx.output))
        with self.assertRaises(WikiResponseError):
            QueryResponse(Mock(), mock_response({'error': 'foo'}))._get_resp_dict()
        with self.assertLogs('wiki_nodes.http.query', 'DEBUG') as log_ctx:
            QueryResponse(Mock(), mock_response({'error': 'foo', 'query': {}}))._get_resp_dict()
            self.assertTrue(
                any('error was encountered, but query results were found' in line for line in log_ctx.output)
            )
        result = {'error': None, 'query': {}}
        self.assertEqual(result, QueryResponse(Mock(), mock_response(result))._get_resp_dict())


if __name__ == '__main__':
    main(exit=False, verbosity=2)

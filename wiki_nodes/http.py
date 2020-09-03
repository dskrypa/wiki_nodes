"""
Library for retrieving data from `MediaWiki sites via REST API <https://www.mediawiki.org/wiki/API>`_ or normal
requests.

:author: Doug Skrypa
"""

import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from distutils.version import LooseVersion
from json import JSONDecodeError
from typing import Iterable, Optional, Union, Dict, Any, Tuple, Collection, Mapping, Set
from urllib.parse import urlparse, unquote, parse_qs

from requests import RequestException, Response

from db_cache import TTLDBCache, DBCache
from requests_client import RequestsClient
from .compat import cached_property
from .exceptions import WikiResponseError, PageMissingError, InvalidWikiError
from .page import WikiPage
from .utils import partitioned

__all__ = ['MediaWikiClient']
log = logging.getLogger(__name__)
qlog = logging.getLogger(__name__ + '.query')
qlog.setLevel(logging.WARNING)
URL_MATCH = re.compile('^[a-zA-Z]+://').match
PageData = Dict[str, Dict[str, Any]]


class MediaWikiClient(RequestsClient):
    _siteinfo_cache = None
    _instances = {}             # type: Dict[str, MediaWikiClient]

    def __new__(cls, host_or_url: str, *args, **kwargs):
        host = urlparse(host_or_url).hostname if URL_MATCH(host_or_url) else host_or_url
        try:
            return cls._instances[host]
        except KeyError:
            cls._instances[host] = instance = super().__new__(cls)
            return instance

    def __init__(self, host_or_url: str, *args, ttl=3600 * 6, **kwargs):
        if not getattr(self, '_MediaWikiClient__initialized', False):
            headers = kwargs.get('headers') or {}
            headers.setdefault('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
            headers.setdefault('Accept-Encoding', 'gzip, deflate')
            headers.setdefault('Accept-Language', 'en-US,en;q=0.5')
            # headers.setdefault('Upgrade-Insecure-Requests', '1')
            if not URL_MATCH(host_or_url):
                kwargs.setdefault('scheme', 'https')
            super().__init__(host_or_url, *args, **kwargs)
            if self.host in ('en.wikipedia.org', 'www.generasia.com'):
                self.path_prefix = 'w'
            if MediaWikiClient._siteinfo_cache is None:
                MediaWikiClient._siteinfo_cache = TTLDBCache('siteinfo', cache_subdir='wiki', ttl=3600 * 24)
            self._page_cache = TTLDBCache(f'{self.host}_pages', cache_subdir='wiki', ttl=ttl)
            self._search_title_cache = TTLDBCache(f'{self.host}_search_titles', cache_subdir='wiki', ttl=ttl)
            self._search_cache = TTLDBCache(f'{self.host}_searches', cache_subdir='wiki', ttl=ttl)
            # All keys in _norm_title_cache should be normalized to upper case to improve matching and prevent dupes
            self._norm_title_cache = DBCache(f'{self.host}_normalized_titles', cache_subdir='wiki', time_fmt='%Y')
            self.__initialized = True

    def __repr__(self):
        return f'<{self.__class__.__name__}({self.host})>'

    @cached_property
    def siteinfo(self) -> Dict[str, Any]:
        """Site metadata, including MediaWiki version.  Cached to disk with TTL = 24 hours."""
        try:
            return self._siteinfo_cache[self.host]
        except KeyError:
            params = {'action': 'query', 'format': 'json', 'meta': 'siteinfo', 'siprop': 'general|interwikimap'}
            resp = self.get('api.php', params=params)  # type: Response
            try:
                self._siteinfo_cache[self.host] = siteinfo = resp.json()['query']
            except JSONDecodeError as e:
                site = None
                if 'Not_a_valid_community' in resp.url:
                    site = parse_qs(urlparse(resp.url).params).get('from')
                site = site or self.host
                raise InvalidWikiError(f'Invalid site: {site!r}')
            return siteinfo

    @cached_property
    def mw_version(self) -> LooseVersion:
        """
        The version of MediaWiki that this site is running.  Used to adjust query parameters due to API changes between
        versions.
        """
        return LooseVersion(self.siteinfo['general']['generator'].split()[-1])

    @cached_property
    def interwiki_map(self) -> Dict[str, str]:
        rows = self.siteinfo['interwikimap']
        return {row['prefix']: row['url'] for row in rows}

    @cached_property
    def lc_interwiki_map(self) -> Dict[str, str]:
        return {k.lower(): v for k, v in self.interwiki_map.items()}

    @cached_property
    def _merged_interwiki_map(self):
        iw_map = self.interwiki_map.copy()
        iw_map.update(self.lc_interwiki_map)
        return iw_map

    def interwiki_client(self, iw_map_key: str) -> Optional['MediaWikiClient']:
        if iw_map_key.startswith('w:c:'):
            community = iw_map_key.rsplit(':', 1)[-1]
            iw_map_key = 'w'
        else:
            community = None

        try:
            url = self.interwiki_map.get(iw_map_key) or self.lc_interwiki_map[iw_map_key.lower()]
        except KeyError:
            return None
        else:
            if community:
                url = url.replace('//community.', f'//{community}.')
            return MediaWikiClient(url, nopath=True)

    @cached_property
    def article_path_prefix(self) -> str:
        return self.siteinfo['general']['articlepath'].replace('$1', '')

    def article_url_to_title(self, url: str) -> str:
        return urlparse(unquote(url)).path.replace(self.article_path_prefix, '', 1)

    def _update_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Include useful default parameters, and handle conversion of lists/tuples/sets to pipe-delimited strings."""
        params['format'] = 'json'
        if self.mw_version >= LooseVersion('1.25'):     # https://www.mediawiki.org/wiki/API:JSON_version_2
            params['formatversion'] = 2
        params['utf8'] = 1
        for key, val in params.items():
            # TODO: Figure out U+001F usage when a value containing | is found
            # Docs: If | in value, use U+001F as the separator & prefix value with it, e.g. param=%1Fvalue1%1Fvalue2
            if isinstance(val, Collection) and not isinstance(val, str):
            # if isinstance(val, (list, tuple, set)):
                params[key] = '|'.join(map(str, val))
                # params[key] = ''.join(map('\u001f{}'.format, val))    # doesn't work for vals without |
        return params

    def query(self, **params) -> Dict[str, Dict[str, Any]]:
        """
        Submit, then parse and transform a `query request <https://www.mediawiki.org/wiki/API:Query>`_

        If the response contained a ``continue`` field, then additional requests will be submitted to gather all of the
        results.

        Note: Limit of 50 titles per query, though API docs say the limit for bots is 500

        :param params: Query API parameters
        :return dict: Mapping of {title: dict(results)}
        """
        params['action'] = 'query'
        params['redirects'] = 1
        properties = params.get('prop', [])
        properties = {properties} if isinstance(properties, str) else set(properties)
        if 'iwlinks' in properties:                     # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Iwlinks
            if self.mw_version >= LooseVersion('1.24'):
                params['iwprop'] = 'url'
            else:
                params['iwurl'] = 1
        if 'categories' in properties:              # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Categories
            params['cllimit'] = 500     # default: 10
        if 'revisions' in properties:               # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Revisions
            if self.mw_version >= LooseVersion('1.32'):
                params['rvslots'] = 'main'
        if params.get('list') == 'allcategories':
            params.setdefault('aclimit', 500)

        titles = params.pop('titles', None)
        if titles:
            # noinspection PyTypeChecker
            if isinstance(titles, str) or len(titles) <= 50:
                return self._query(titles=titles, **params)
            else:
                full_resp = {}
                for group in partitioned(list(titles), 50):
                    full_resp.update(self._query(titles=group, **params))
                return full_resp
        else:
            return self._query(**params)

    def _query(self, *, no_parse=False, **params) -> Dict[str, Dict[str, Any]]:
        params = self._update_params(params)
        resp = self.get('api.php', params=params)
        if no_parse:
            return resp.json()
        parsed, prop_continue, other_continue = self._parse_query(resp.json(), resp.url)
        skip_merge = {'pageid', 'ns', 'title'}
        while prop_continue or other_continue:
            continue_params = deepcopy(params)
            if prop_continue:
                continue_params['prop'] = '|'.join(prop_continue.keys())
                for continue_cmd in prop_continue.values():
                    continue_params.update(continue_cmd)
            if other_continue:
                continue_params.update(other_continue)

            resp = self.get('api.php', params=continue_params)
            _parsed, prop_continue, other_continue = self._parse_query(resp.json(), resp.url)
            for title, data in _parsed.items():
                full = parsed[title]
                for key, val in data.items():
                    if key == 'iwlinks':
                        try:
                            full_val = full[key]
                        except KeyError:
                            full_val = full[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}

                        for iw_name, iw_links in val.items():
                            full_val[iw_name].update(iw_links)
                    else:
                        try:
                            full_val = full[key]
                        except KeyError:
                            full[key] = val
                        else:
                            if isinstance(full_val, list):
                                full_val.extend(val)
                            elif isinstance(full_val, dict):
                                full_val.update(val)
                            elif key in skip_merge:
                                pass
                            else:
                                if val is not None and full_val is None:
                                    full[key] = val
                                elif val == full_val:
                                    pass
                                else:
                                    base = f'Unexpected value to merge for title={title!r} key={key!r} type='
                                    log.error(f'{base}{type(full_val).__name__} full_val={full_val!r} new val={val!r}')

        return parsed

    def _parse_query(self, response: Mapping[str, Any], url: str) -> Tuple[Dict[str, Dict[str, Any]], Any, Any]:
        if 'query' not in response and 'error' in response:
            raise WikiResponseError(json.dumps(response['error']))

        try:
            results = response['query']
        except KeyError:
            log.debug(f'Response from {url} contained no \'query\' key; found: {", ".join(response)}')
            # log.debug(f'Complete response: {json.dumps(response, sort_keys=True, indent=4)}')
            return {}, None, None
        except TypeError:
            if not response:
                log.debug(f'Response from {url} was empty.')
            else:
                log.debug(f'Response from {url} was not a dict; found: {response}')
            return {}, None, None

        if 'pages' in results:
            parsed = self._parse_query_pages(results)
        elif 'allcategories' in results:
            parsed = {row['category']: row['size'] for row in results['allcategories']}
        elif 'search' in results:
            parsed = {row['title']: row for row in results['search']}
        else:
            query_keys = ', '.join(results)
            log.debug(f'Query results from {url} did not contain any handled keys; found: {query_keys}')
            return {}, None, None

        prop_continue = response.get('query-continue')
        other_continue = response.get('continue')
        return parsed, prop_continue, other_continue

    def _parse_query_pages(self, results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        pages = results['pages']
        redirects = results.get('redirects', [])
        redirects = {r['to']: r['from'] for r in (redirects.values() if isinstance(redirects, dict) else redirects)}
        if isinstance(pages, dict):
            pages = pages.values()

        if self.mw_version >= LooseVersion('1.25'):
            iw_key = 'title'
            rev_key = 'content'
        else:
            iw_key, rev_key = '*', '*'

        parsed = {}
        for page in pages:
            title = page['title']
            qlog.debug(f'Processing page with title={title!r}, keys: {", ".join(sorted(page))}')
            # if 'revisions' not in page:
            #     qlog.debug(f' > Content: {json.dumps(page, sort_keys=True, indent=4)}')
            content = parsed[title] = {'redirected_from': redirects.get(title)}
            for key, val in page.items():
                if key == 'revisions':
                    if self.mw_version >= LooseVersion('1.32'):
                        content[key] = [rev['slots']['main']['content'] for rev in val]
                    else:
                        content[key] = [rev[rev_key] for rev in val]
                elif key == 'categories':
                    content[key] = [cat['title'].split(':', maxsplit=1)[1] for cat in val]
                elif key == 'iwlinks':
                    iwlinks = content[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}
                    for iwlink in val:
                        iwlinks[iwlink['prefix']][iwlink[iw_key]] = iwlink['url']
                elif key == 'links':
                    content[key] = [link['title'] for link in val]
                else:
                    content[key] = val
        return parsed

    def parse(self, **params) -> Dict[str, Any]:
        """
        Submit, then parse and transform a `parse request <https://www.mediawiki.org/wiki/API:Parse>`_

        The parse API only accepts one page at a time.

        :param params: Parse API parameters
        :return:
        """
        params['action'] = 'parse'
        params['redirects'] = 1
        properties = params.get('prop', [])
        properties = {properties} if isinstance(properties, str) else set(properties)
        if 'text' in properties:
            params['disabletoc'] = 1
            params['disableeditsection'] = 1

        resp = self.get('api.php', params=self._update_params(params))
        content = {}
        page = resp.json()['parse']
        for key, val in page.items():
            if key in ('wikitext', 'categorieshtml'):
                content[key] = val['*']
            elif key == 'text':
                content['html'] = val['*']
            elif key == 'categories':
                content[key] = [cat['*'] for cat in val]
            elif key == 'iwlinks':
                iwlinks = content[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}
                for iwlink in val:
                    link_text = iwlink['*'].split(':', maxsplit=1)[1]
                    iwlinks[iwlink['prefix']][link_text] = iwlink['url']
            elif key == 'links':
                content[key] = [wl['*'] for wl in val]
            else:
                content[key] = val
        return content

    def query_content(self, titles: Union[str, Iterable[str]]) -> Dict[str, Any]:
        """Get the contents of the latest revision of one or more pages as wikitext."""
        pages = {}
        resp = self.query(titles=titles, rvprop='content', prop='revisions')
        for title, data in resp.items():
            revisions = data.get('revisions')
            pages[title] = revisions[0] if revisions else None
        return pages

    def query_categories(self, titles: Union[str, Iterable[str]]) -> Dict[str, Any]:
        """Get the categories of one or more pages."""
        resp = self.query(titles=titles, prop='categories')
        return {title: data.get('categories', []) for title, data in resp.items()}

    def _cached_and_needed(self, titles: Union[str, Iterable[str]], no_cache=False) -> Tuple[PageData, Set[str]]:
        if isinstance(titles, str):
            titles = [titles]
        need = set()
        pages = {}
        for title in titles:
            try:
                norm_title = self._norm_title_cache[normalize(title)]
            except KeyError:
                norm_title = title
            else:
                qlog.debug(f'Normalized title {title!r} to {norm_title!r}')

            if no_cache:
                need.add(title)
            else:
                for _title in self._search_title_cache.get(norm_title, (norm_title,)):
                    key = title if _title == norm_title else _title
                    try:
                        page = self._page_cache[_title]
                    except KeyError:
                        need.add(key)
                        qlog.debug(f'No content was found in {self.host} page cache for title={norm_title!r}')
                    else:
                        if page:
                            pages[key] = page
                            qlog.debug(f'Found content in {self.host} page cache for title={norm_title!r}')
                        else:
                            qlog.debug(f'Found empty content in {self.host} page cache for title={norm_title!r}')
        return pages, need

    def _store_normalized(self, orig, normalized, reason):
        qlog.debug(f'Storing title normalization for {orig!r} => {normalized!r} [{reason}]')
        self._norm_title_cache[orig] = normalized

    def _cache_page(self, title, categories=None, revisions=None):
        self._page_cache[title] = entry = {
            'title': title,
            'categories': categories or [],
            'wikitext': revisions[0] if revisions else None
        }
        return entry

    def _cache_search_pages(self, term, titles):
        self._search_title_cache[term] = list(titles)

    def _process_pages_resp(self, resp, need, norm_to_orig, pages, allow_unexpected=False):
        no_data = []
        qlog.debug(f'Found {len(resp)} pages: [{", ".join(map(repr, sorted(resp)))}]')
        lc_norm_to_norm = None
        for title, data in resp.items():
            qlog.debug(f'Processing page with title={title!r}, data: {", ".join(sorted(data))}')
            if data.get('pageid') is None:  # The page does not exist
                no_data.append(title)
            else:
                entry = self._cache_page(title, data.get('categories'), data.get('revisions'))
                redirected_from = normalize(data['redirected_from'] or '')
                if redirected_from:
                    self._store_normalized(redirected_from, title, 'redirect')
                    try:
                        pages[norm_to_orig.pop(redirected_from)] = entry
                    except KeyError:
                        lc_redirected_from = redirected_from.lower()
                        if lc_redirected_from in norm_to_orig:
                            pages[norm_to_orig.pop(lc_redirected_from)] = entry
                        else:
                            log.debug(f'Unexpected KeyError for key={redirected_from!r} in norm_to_orig={norm_to_orig}')
                else:
                    norm_title = normalize(title)
                    lc_title = norm_title.lower()
                    if title not in need:  # Not all sites indicate when a redirect happened
                        if norm_title in norm_to_orig:
                            self._store_normalized(norm_title, title, 'quiet redirect')
                            pages[norm_to_orig.pop(norm_title)] = entry
                        elif lc_title in norm_to_orig:
                            self._store_normalized(lc_title, title, 'quiet redirect')
                            pages[norm_to_orig.pop(lc_title)] = entry
                        elif allow_unexpected:
                            pages[title] = entry
                        else:
                            if lc_norm_to_norm is None:
                                lc_norm_to_norm = {k.lower(): k for k in norm_to_orig}
                            if lc_title in lc_norm_to_norm:
                                norm_title = lc_norm_to_norm[lc_title]
                                self._store_normalized(norm_title, title, 'quiet redirect')
                                pages[norm_to_orig.pop(norm_title)] = entry
                            else:
                                fmt = 'Received page from {} for title={!r} that did not match any requested title'
                                log.debug(fmt.format(self.host, title))
                    else:
                        # Exact title match
                        pages[norm_to_orig.pop(norm_title)] = entry

        return no_data

    def query_pages(
        self, titles: Union[str, Iterable[str]], search=False, no_cache=False, gsrwhat='nearmatch'
    ) -> PageData:
        """
        Get the full page content and the following additional data about each of the provided page titles:\n
          - categories

        Data retrieved by this method is cached in a TTL=1h persistent disk cache.

        If any of the provided titles did not exist, they will not be included in the returned dict.

        Notes:\n
          - The keys in the result may be different than the titles requested
            - Punctuation may be stripped, if it did not belong in the title
            - The case of the title may be different

        :param str|list|set|tuple titles: One or more page titles (as it appears in the URL for the page)
        :param bool search: Whether the provided titles should also be searched for, in case there is not an exact
          match.  This does not seem to work when multiple titles are provided as the search term.
        :param bool no_cache: Bypass the page cache, and retrieve a fresh version of the specified page(s)
        :param str gsrwhat: The search type to use when search is True
        :return dict: Mapping of {title: dict(page data)}
        """
        pages, need = self._cached_and_needed(titles, no_cache)
        if need:
            norm_to_orig = {normalize(title): title for title in need}  # Return the exact titles that were requested
            resp = self.query(titles=need, rvprop='content', prop=['revisions', 'categories'])
            no_data = self._process_pages_resp(resp, need, norm_to_orig, pages)

            if no_data and search:
                log.debug(f'Re-attempting retrieval of pages via searches: {sorted(no_data)}')
                _no_data, no_data = no_data, []
                for title in _no_data:
                    kwargs = {'generator': 'search', 'gsrsearch': title, 'gsrwhat': gsrwhat}
                    resp = self.query(rvprop='content', prop=['revisions', 'categories'], **kwargs)
                    self._cache_search_pages(title, resp)
                    no_data.extend(self._process_pages_resp(resp, need, norm_to_orig, pages, gsrwhat == 'text'))

            for title in no_data:
                qlog.debug(f'No page was found from {self.host} for title={title!r} - caching null page')
                # norm_title = normalize(title)
                self._page_cache[title] = None
                # if norm_title in norm_to_orig:
                #     norm_to_orig.pop(norm_title)

            for title in norm_to_orig.values():
                if title not in self._page_cache:
                    qlog.debug(f'No content was returned from {self.host} for title={title!r} - caching null page')
                    self._page_cache[title] = None

        return pages

    def query_page(self, title: str, search=False, no_cache=False, gsrwhat='nearmatch') -> Dict[str, Any]:
        results = self.query_pages(title, search=search, no_cache=no_cache, gsrwhat=gsrwhat)
        if not results:
            raise PageMissingError(title, self.host)
        try:
            return results[title]
        except KeyError:
            raise PageMissingError(title, self.host, f'but results were found for: {", ".join(sorted(results))}')

    def parse_page(self, page: str) -> Dict[str, Any]:
        resp = self.parse(page=page, prop=['wikitext', 'text', 'categories', 'links', 'iwlinks', 'displaytitle'])
        return resp

    def search(
            self, query: str, search_type: str = 'nearmatch', limit: int = 10, offset: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Search for pages that match the given query.

        `API documentation <https://www.mediawiki.org/wiki/Special:MyLanguage/API:Search>`_

        :param str query: The query
        :param str search_type: The type of search to perform (title, text, nearmatch); some types may be disabled in
          some wikis.
        :param int limit: Number of results to return (max: 500)
        :param int offset: The number of results to skip when requesting additional results for the given query
        :return dict: The parsed response
        """
        lc_query = f'{search_type}::{query.lower()}'
        try:
            results = self._search_cache[lc_query]
        except KeyError:
            params = {
                # 'srprop': ['timestamp', 'snippet', 'redirecttitle', 'categorysnippet']
            }
            if search_type is not None:
                params['srwhat'] = search_type
            if offset is not None:
                params['sroffset'] = offset
            self._search_cache[lc_query] = results = self.query(list='search', srsearch=query, srlimit=limit, **params)
        return results

    def get_pages(
        self,
        titles: Union[str, Iterable[str]],
        preserve_comments=False,
        search=False,
        no_cache=False,
        gsrwhat='nearmatch',
    ) -> Dict[str, WikiPage]:
        raw_pages = self.query_pages(titles, search=search, no_cache=no_cache, gsrwhat=gsrwhat)
        pages = {
            result_title: WikiPage(
                data['title'], self.host, data['wikitext'], data['categories'], preserve_comments,
                self._merged_interwiki_map
            )
            for result_title, data in raw_pages.items()
        }   # The result_title may have redirected to the actual title
        return pages

    def get_page(
        self, title: str, preserve_comments=False, search=False, no_cache=False, gsrwhat='nearmatch'
    ) -> WikiPage:
        data = self.query_page(title, search=search, no_cache=no_cache, gsrwhat=gsrwhat)
        page = WikiPage(
            data['title'], self.host, data['wikitext'], data['categories'], preserve_comments,
            self._merged_interwiki_map
        )
        return page

    @classmethod
    def page_for_article(cls, article_url: str, preserve_comments=False, no_cache=False) -> WikiPage:
        client = cls(article_url, nopath=True)
        return client.get_page(client.article_url_to_title(article_url), preserve_comments, no_cache=no_cache)

    @classmethod
    def get_multi_site_page(
        cls,
        title: str,
        sites: Iterable[str],
        preserve_comments=False,
        search=False,
        no_cache=False,
        gsrwhat='nearmatch',
    ) -> Tuple[Dict[str, WikiPage], Dict[str, Exception]]:
        """
        :param str title: A page title
        :param iterable sites: A list or other iterable that yields site host strings
        :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param bool search: Whether the provided title should also be searched for, in case there is not an exact match.
        :param bool no_cache: Bypass the page cache, and retrieve a fresh version of the specified page(s)
        :param str gsrwhat: The search type to use when search is True
        :return tuple: Tuple containing mappings of {site: WikiPage}, {site: errors}
        """
        clients = [cls(site, nopath=True) for site in sites]
        with ThreadPoolExecutor(max_workers=max(1, len(clients))) as executor:
            _futures = {
                executor.submit(client.get_page, title, preserve_comments, search, no_cache, gsrwhat): client.host
                for client in clients
            }
            results = {}
            errors = {}
            for future in as_completed(_futures):
                site = _futures[future]
                try:
                    results[site] = future.result()
                except (RequestException, PageMissingError, InvalidWikiError) as e:
                    log.error(f'Error retrieving page={title!r} from site={site}: {e}')
                    errors[site] = e

            return results, errors

    @classmethod
    def get_multi_site_pages(
        cls,
        site_title_map: Mapping[Union[str, 'MediaWikiClient'], Iterable[str]],
        preserve_comments=False,
        search=False,
        no_cache=False,
        gsrwhat='nearmatch',
    ) -> Tuple[Dict[str, Dict[str, WikiPage]], Dict[str, Exception]]:
        """
        :param dict site_title_map: Mapping of {site|MediaWikiClient: list(titles)}
        :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param bool search: Whether the provided title should also be searched for, in case there is not an exact match.
        :param bool no_cache: Bypass the page cache, and retrieve a fresh version of the specified page(s)
        :param str gsrwhat: The search type to use when search is True
        :return tuple: Tuple containing mappings of {site: results}, {site: errors}
        """
        client_title_map = {
            (site if isinstance(site, cls) else cls(site, nopath=True)): titles
            for site, titles in site_title_map.items()
        }
        with ThreadPoolExecutor(max_workers=max(1, len(client_title_map))) as executor:
            _futures = {
                executor.submit(client.get_pages, titles, preserve_comments, search, no_cache, gsrwhat): client.host
                for client, titles in client_title_map.items()
            }
            results = {}
            errors = {}
            for future in as_completed(_futures):
                site = _futures[future]
                try:
                    results[site] = future.result()
                except (RequestException, InvalidWikiError) as e:
                    log.error(f'Error retrieving pages from site={site}: {e}')
                    errors[site] = e

            return results, errors


def normalize(title: str) -> str:
    return title.replace('_', ' ').strip()


if __name__ == '__main__':
    qlog.setLevel(logging.NOTSET)

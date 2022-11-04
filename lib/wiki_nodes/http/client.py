"""
Library for retrieving data from `MediaWiki sites via REST API <https://www.mediawiki.org/wiki/API>`_ or normal
requests.

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from json import JSONDecodeError
from shutil import copyfileobj
from typing import Iterable, Optional, Union, Any, Mapping, Iterator
from urllib.parse import urlparse, unquote, parse_qs

from requests import RequestException, Response

from db_cache import TTLDBCache
from requests_client import RequestsClient

from ..exceptions import PageMissingError, InvalidWikiError
from ..utils import cached_property
from ..version import LooseVersion
from .cache import WikiCache
from .parse import Parse
from .query import Query
from .utils import TitleDataMap, PageEntry, TitleEntryMap, Titles, normalize_title

__all__ = ['MediaWikiClient']
log = logging.getLogger(__name__)
qlog = logging.getLogger(__name__ + '.query')
qlog.setLevel(logging.WARNING)

URL_MATCH = re.compile('^[a-zA-Z]+://').match


class MediaWikiClient(RequestsClient):
    _pickle_queries = False
    _siteinfo_cache = None
    _instances = {}             # type: dict[str, MediaWikiClient]

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
            self.__init()
            self._cache = WikiCache(self.host, ttl)

    def __init(self):
        if MediaWikiClient._siteinfo_cache is None:
            MediaWikiClient._siteinfo_cache = TTLDBCache('siteinfo', cache_subdir='wiki', ttl=86_400)  # 3600 * 24
        self.__initialized = True

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.host})>'

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        state['_cache'] = self._cache
        return state

    def __setstate__(self, state: dict[str, Any]):
        if not getattr(self, '_MediaWikiClient__initialized', False):
            cache = state.pop('_cache')
            super().__setstate__(state)
            self.__init()
            self._cache = cache

    def __getnewargs__(self):
        return (self.host,)

    @cached_property
    def siteinfo(self) -> dict[str, Any]:
        """Site metadata, including MediaWiki version.  Cached to disk with TTL = 24 hours."""
        try:
            return self._siteinfo_cache[self.host]
        except KeyError:
            params = {'action': 'query', 'format': 'json', 'meta': 'siteinfo', 'siprop': 'general|interwikimap'}
            resp = self.get('api.php', params=params)  # type: Response
            try:
                self._siteinfo_cache[self.host] = siteinfo = resp.json()['query']
            except JSONDecodeError:
                site = self.host
                if 'Not_a_valid_community' in resp.url:
                    try:
                        site = parse_qs(urlparse(resp.url).query)['from'][0]  # noqa
                    except Exception:  # noqa
                        pass
                raise InvalidWikiError(f'Invalid site: {site!r}')
            return siteinfo

    @cached_property
    def mw_version(self) -> LooseVersion:
        """
        The version of MediaWiki that this site is running.  Used to adjust query parameters due to API changes between
        versions.
        """
        return LooseVersion(self.siteinfo['general']['generator'].split()[-1])

    # region Inter-Wiki Methods

    @cached_property
    def interwiki_map(self) -> dict[str, str]:
        rows = self.siteinfo['interwikimap']
        return {row['prefix']: row['url'] for row in rows}

    @cached_property
    def lc_interwiki_map(self) -> dict[str, str]:
        return {k.lower(): v for k, v in self.interwiki_map.items()}

    @cached_property
    def _merged_interwiki_map(self):
        iw_map = self.interwiki_map.copy()
        iw_map.update(self.lc_interwiki_map)
        return iw_map

    def interwiki_client(self, iw_map_key: str) -> Optional[MediaWikiClient]:
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

    # endregion

    # region Article URL Methods

    @cached_property
    def article_path_prefix(self) -> str:
        return self.siteinfo['general']['articlepath'].replace('$1', '')

    @cached_property
    def article_url_prefix(self) -> str:
        return self.url_for(self.article_path_prefix)

    def article_url_to_title(self, url: str) -> str:
        if url.startswith(self.article_url_prefix):
            return url[len(self.article_url_prefix):]
        else:
            parsed = urlparse(url)
            uri_path = unquote(parsed.path)
            title = uri_path.replace(self.article_path_prefix, '', 1)
            if url.endswith('?') and not title.endswith('?'):  # TODO: Is this necessary?
                log.debug(f'TODO_CASE: Encountered {url=} ending in ? with {title=} not ending in ?')
                title += '?'
            elif parsed.query and not parse_qs(parsed.query):
                title = f'{title}?{parsed.query}'
            return title

    def url_for_article(self, title: str) -> str:
        # gen_info = self.siteinfo['general']  # Note: gen_info['server'] may use http when https is supported
        # return gen_info['server'] + gen_info['articlepath'].replace('$1', title.replace(' ', '_'))
        return self.url_for(self.article_path_prefix + title.replace(' ', '_'), relative=False)

    # endregion

    # region Mid-Level Parse/Query/Search Methods

    def query(self, **params) -> TitleDataMap:
        """
        Submit, then parse and transform a `query request <https://www.mediawiki.org/wiki/API:Query>`_

        If the response contained a ``continue`` field, then additional requests will be submitted to gather all of the
        results.

        Note: Limit of 50 titles per query, though API docs say the limit for bots is 500

        :param params: Query API parameters
        :return: Mapping of {title: dict(results)}
        """
        return Query(self, **params).get_results()

    def parse(self, **params) -> dict[str, Any]:
        """
        Submit, then parse and transform a `parse request <https://www.mediawiki.org/wiki/API:Parse>`_

        The parse API only accepts one page at a time.

        :param params: Parse API parameters
        :return:
        """
        return Parse(self, **params).get_results()

    def parse_page(self, page: str) -> dict[str, Any]:
        return Parse.page(self, page).get_results()

    def query_content(self, titles: Titles) -> dict[str, Optional[str]]:
        """Get the contents of the latest revision of one or more pages as wikitext."""
        pages = {}
        for title, data in Query.content(self, titles).get_results().items():
            revisions = data.get('revisions')
            pages[title] = revisions[0] if revisions else None
        return pages

    def query_categories(self, titles: Titles) -> dict[str, list[str]]:
        """Get the categories of one or more pages."""
        resp = Query.categories(self, titles).get_results()
        return {title: data.get('categories', []) for title, data in resp.items()}

    def query_pages(
        self, titles: Titles, search: bool = False, no_cache: bool = False, gsrwhat: str = 'nearmatch'
    ) -> TitleEntryMap:
        """
        Get the full page content and the following additional data about each of the provided page titles:\n
          - categories

        Data retrieved by this method is cached in a TTL=1h persistent disk cache.

        If any of the provided titles did not exist, they will not be included in the returned dict.

        Notes:\n
          - The keys in the result may be different than the titles requested
            - Punctuation may be stripped, if it did not belong in the title
            - The case of the title may be different

        :param titles: One or more page titles (as it appears in the URL for the page)
        :param search: Whether the provided titles should also be searched for, in case there is not an exact
          match.  This does not seem to work when multiple titles are provided as the search term.
        :param no_cache: Bypass the page cache, and retrieve a fresh version of the specified page(s)
        :param gsrwhat: The search type to use when search is True
        :return: Mapping of {title: dict(page data)}
        """
        return PageQuery(self, titles, search, no_cache, gsrwhat).get_pages()

    def query_page(self, title: str, search=False, no_cache=False, gsrwhat='nearmatch') -> PageEntry:
        return PageQuery(self, title, search, no_cache, gsrwhat).get_page(title)

    def search(self, query: str, search_type: str = 'nearmatch', limit: int = 10, offset: int = None) -> TitleDataMap:
        """
        Search for pages that match the given query.

        `API documentation <https://www.mediawiki.org/wiki/Special:MyLanguage/API:Search>`_

        :param query: The query
        :param search_type: The type of search to perform (title, text, nearmatch); some types may be disabled in
          some wikis.
        :param limit: Number of results to return (max: 500)
        :param offset: The number of results to skip when requesting additional results for the given query
        :return: The parsed response
        """
        lc_query = f'{search_type}::{query.lower()}'
        cache = self._cache.searches
        try:
            results = cache[lc_query]
        except KeyError:
            cache[lc_query] = results = Query.search(self, query, search_type, limit, offset).get_results()

        return results

    # endregion

    # region High-Level WikiPage Methods

    def get_pages(
        self,
        titles: Titles,
        preserve_comments: bool = False,
        search: bool = False,
        no_cache: bool = False,
        gsrwhat: str = 'nearmatch',
    ) -> dict[str, WikiPage]:
        raw_pages = self.query_pages(titles, search=search, no_cache=no_cache, gsrwhat=gsrwhat)
        pages = {
            result_title: WikiPage(
                data['title'], self.host, data['wikitext'], data['categories'], preserve_comments,
                self._merged_interwiki_map, self
            )
            for result_title, data in raw_pages.items()
        }   # The result_title may have redirected to the actual title
        return pages

    def get_page(
        self,
        title: str,
        preserve_comments: bool = False,
        search: bool = False,
        no_cache: bool = False,
        gsrwhat: str = 'nearmatch',
    ) -> WikiPage:
        data = self.query_page(title, search=search, no_cache=no_cache, gsrwhat=gsrwhat)
        page = WikiPage(
            data['title'], self.host, data['wikitext'], data['categories'], preserve_comments,
            self._merged_interwiki_map, self
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
        preserve_comments: bool = False,
        search: bool = False,
        no_cache: bool = False,
        gsrwhat: str = 'nearmatch',
    ) -> tuple[dict[str, WikiPage], dict[str, Exception]]:
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
        site_title_map: Mapping[Union[str, MediaWikiClient], Iterable[str]],
        preserve_comments: bool = False,
        search: bool = False,
        no_cache: bool = False,
        gsrwhat: str = 'nearmatch',
    ) -> tuple[dict[str, dict[str, WikiPage]], dict[str, Exception]]:
        """
        :param site_title_map: Mapping of {site|MediaWikiClient: list(titles)}
        :param preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param search: Whether the provided title should also be searched for, in case there is not an exact match.
        :param no_cache: Bypass the page cache, and retrieve a fresh version of the specified page(s)
        :param gsrwhat: The search type to use when search is True
        :return: Tuple containing mappings of {site: results}, {site: errors}
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

    # endregion

    # region Image Methods

    def get_page_image_titles(self, titles: Titles) -> dict[str, list[str]]:
        """
        :param titles: One or more page titles
        :return: Mapping of {page title: [image titles]}
        """
        needed, img_titles = self._cache.get_misc('images', titles)
        if needed:
            # resp = Query.image_titles(self, titles).get_results()
            resp = Query.image_titles(self, needed).get_results()
            results = {title: [image['title'] for image in data.get('images', [])] for title, data in resp.items()}
            self._cache.store_misc('images', results)
            img_titles.update(results)
        return img_titles

    def get_image_urls(self, titles: Titles) -> dict[str, str]:
        """
        :param titles: One or more image titles (NOT page titles)
        :return: Mapping of {image title: download URL}
        """
        needed, urls = self._cache.get_misc('imageinfo', titles)
        if needed:
            resp = Query.image_info(self, needed, 'url').get_results()
            resp_urls = {  # Some entries may have missing: True and no imageinfo key
                title: img_info[0]['url'] for title, data in resp.items() if (img_info := data.get('imageinfo'))
            }
            self._cache.store_misc('imageinfo', resp_urls)
            urls.update(resp_urls)
        return urls

    def get_page_image_urls(self, titles: Titles) -> dict[str, dict[str, str]]:
        """
        :param titles: One or more page titles (NOT image titles)
        :return: Mapping of {page title: {image title: image URL}}
        """
        page_image_title_map = self.get_page_image_titles(titles)
        page_image_url_map = {
            page_title: self.get_image_urls(image_titles) for page_title, image_titles in page_image_title_map.items()
        }
        return page_image_url_map

    def get_image(self, title_or_url: str) -> bytes:
        try:
            name = _image_name(title_or_url)
        except ValueError as e:
            log.debug(e)
            name = None

        try:
            return self._cache.get_image(name)
        except KeyError:
            pass

        url = title_or_url if URL_MATCH(title_or_url) else self.get_image_urls(title_or_url)[title_or_url]
        resp = self.get(url, relative=False, stream=True)
        try:
            content_len = int(resp.headers['Content-Length'])
        except (ValueError, TypeError, KeyError):
            content_len = 0
        bio = BytesIO()
        resp.raw.decode_content = True
        copyfileobj(resp.raw, bio)
        data = bio.getvalue()
        log.debug(f'Downloaded {len(data):,d} B (expected {content_len:,d} B) from {url}')
        if content_len and len(data) == content_len:
            self._cache.store_image(name, data)
        return data

    # endregion


def _image_name(title_or_url: str) -> str:
    try:
        file_name_match = _image_name._file_name_match
    except AttributeError:
        file_name_match = _image_name._file_name_match = re.compile(r'.*\.\w{3,4}$').match

    if URL_MATCH(title_or_url):
        path = urlparse(title_or_url).path
        while path and not file_name_match(path):
            path = path.rsplit('/', 1)[0]
        if file_name_match(path):
            title = path.rsplit('/', 1)[-1]
        else:
            raise ValueError(f'Unable to determine filename from {title_or_url=}')
    else:
        title = title_or_url

    if title.lower().startswith('file:'):
        title = title.split(':', 1)[1]

    return title


class PageQuery:
    def __init__(
        self,
        client: MediaWikiClient,
        titles: Titles,
        search: bool = False,
        no_cache: bool = False,
        gsrwhat: str = 'nearmatch',
    ):
        self.client = client
        self.titles = [titles] if isinstance(titles, str) else titles
        self._search = search
        self.no_cache = no_cache
        self._gsrwhat = gsrwhat
        self._pages = {}  # type: dict[str, PageEntry]
        self._no_data = set()
        self._cache: WikiCache = client._cache

    def get_pages(self) -> dict[str, PageEntry]:
        if self.needed:
            unquoted_need = set(map(unquote, self.needed))
            resp = self.client.query(titles=unquoted_need, rvprop='content', prop=['revisions', 'categories'])
            self._process_pages_resp(resp)
            if self.missing and self._search:
                missing = sorted(self.missing)
                log.debug(f'Re-attempting retrieval of pages via searches: {missing}')
                for title in missing:
                    kwargs = {'generator': 'search', 'gsrsearch': title, 'gsrwhat': self._gsrwhat}
                    resp = self.client.query(rvprop='content', prop=['revisions', 'categories'], **kwargs)
                    self._cache.search_titles[title] = list(resp)
                    self._process_pages_resp(resp, self._gsrwhat == 'text')

            for title in sorted(self._no_data.union(self.missing)):
                if title not in self._cache.pages:
                    qlog.debug(f'No page was found from {self.client.host} for {title=} - caching null page')
                    self._cache.pages[title] = None

        return self._pages

    def get_page(self, title: str) -> PageEntry:
        results = self.get_pages()
        if not results:
            raise PageMissingError(title, self.client.host)
        try:
            return results[title]
        except KeyError:
            raise PageMissingError(title, self.client.host, f'but results were found for: {", ".join(sorted(results))}')

    @cached_property
    def needed(self) -> set[str]:
        need = set()
        for title in self.titles:
            try:
                norm_title = self._cache.normalized_titles[normalize_title(title)]
            except KeyError:
                norm_title = title
            else:
                qlog.debug(f'Normalized title {title!r} to {norm_title!r}')

            if self.no_cache:
                need.add(title)
            else:
                for _title in self._cache.search_titles.get(norm_title, (norm_title,)):
                    key = title if _title == norm_title else _title
                    try:
                        page = self._cache.pages[_title]
                    except KeyError:
                        need.add(key)
                        qlog.debug(f'No content was found in {self.client.host} page cache for title={norm_title!r}')
                    else:
                        if page:
                            self._pages[key] = page
                            qlog.debug(f'Found content in {self.client.host} page cache for title={norm_title!r}')
                        else:
                            qlog.debug(f'Found empty content in {self.client.host} page cache for title={norm_title!r}')
        return need

    @cached_property
    def missing(self) -> set[str]:
        return self.needed.copy()

    @cached_property
    def norm_to_orig(self) -> dict[str, str]:
        return {normalize_title(title): title for title in self.needed}  # Return the exact titles that were requested

    @cached_property
    def lc_norm_to_norm(self) -> dict[str, str]:
        return {k.lower(): k for k in self.norm_to_orig}

    def _response_entries(self, title_data_map: TitleDataMap) -> Iterator[tuple[str, str, dict[str, Any], PageEntry]]:
        for title, data in title_data_map.items():
            qlog.debug(f'Processing page with title={title!r}, data: {", ".join(sorted(data))}')
            if data.get('pageid') is None:  # The page does not exist
                self._no_data.add(title)
                continue

            rev = data.get('revisions')
            self._cache.pages[title] = entry = {
                'title': title, 'categories': data.get('categories') or [], 'wikitext': rev[0] if rev else None
            }
            yield title, normalize_title(title), data, entry

    def _process_pages_resp(self, title_data_map: TitleDataMap, allow_unexpected: bool = False):
        for title, norm_title, data, entry in self._response_entries(title_data_map):
            if redirected_from := normalize_title(data.get('redirected_from') or ''):
                self._store_normalized(redirected_from, title, 'redirect')
                if original := (self._original_title(redirected_from) or self._original_title(norm_title)):
                    self._store_page(original, entry)
                elif allow_unexpected:
                    self._store_page(title, entry)
                else:
                    log.debug(
                        f'Received page {title=} {redirected_from=} from {self.client.host} that does not match any'
                        f' requested titles'
                    )
            else:
                if title in self.needed:
                    self._store_page(title, entry)
                elif original := self._original_title(norm_title, title):
                    self._store_page(original, entry)
                elif allow_unexpected:
                    self._store_page(title, entry)
                else:
                    log.debug(
                        f'Received page {title=} from {self.client.host} that does not match any requested titles'
                    )

    def _original_title(self, norm_title: str, title: str = None) -> Optional[str]:
        try:
            orig = self.norm_to_orig[norm_title]
        except KeyError:
            pass
        else:
            if title:
                self._store_normalized(norm_title, title, 'quiet redirect')
            return orig

        lc_norm = norm_title.lower()
        try:
            orig = self.norm_to_orig[lc_norm]
        except KeyError:
            pass
        else:
            if title:
                self._store_normalized(lc_norm, title, 'quiet redirect')
            return orig

        try:
            norm_title = self.lc_norm_to_norm[lc_norm]
            orig = self.norm_to_orig[norm_title]
        except KeyError:
            pass
        else:
            if title:
                self._store_normalized(norm_title, title, 'quiet redirect')
            return orig
        return None

    def _store_normalized(self, orig: str, normalized: str, reason: str):
        qlog.debug(f'Storing title normalization for {orig!r} => {normalized!r} [{reason}]')
        self._cache.normalized_titles[orig] = normalized

    def _store_page(self, title: str, entry: PageEntry):
        self._pages[title] = entry
        self.missing.discard(title)
        self._no_data.discard(title)


from ..page import WikiPage  # noqa  # Down here due to circular dependency


if __name__ == '__main__':
    qlog.setLevel(logging.NOTSET)

"""
Functionality related to using the `Query API <https://www.mediawiki.org/wiki/API:Query>`__
"""

from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from json import dumps
from typing import TYPE_CHECKING, Any, Collection, Iterator

from ..exceptions import WikiResponseError
from ..utils import partitioned
from ..version import LooseVersion
from .utils import TitleDataMap, Titles, _normalize_params, _multi_value_param

if TYPE_CHECKING:
    from requests import Response
    from ..typing import StrOrStrs
    from .client import MediaWikiClient

__all__ = ['Query', 'QueryResponse', 'PageData']
log = logging.getLogger(__name__)
qlog = logging.getLogger(__name__ + '.query')
qlog.setLevel(logging.WARNING)


class Query:
    """
    Submit, then parse and transform a `query request <https://www.mediawiki.org/wiki/API:Query>`_

    If the response contained a ``continue`` field, then additional requests will be submitted to gather all of the
    results.

    Note: Limit of 50 titles per query, though API docs say the limit for bots is 500

    :param client: The MediaWikiClient through which the query will be submitted
    :param params: Query API parameters
    """
    __slots__ = ('client', 'params', 'titles')

    def __init__(self, client: MediaWikiClient, *, prop: StrOrStrs = None, titles: StrOrStrs = None, **params):
        params['action'] = 'query'
        params['redirects'] = 1
        if params.get('list') == 'allcategories':
            params.setdefault('aclimit', 500)
        self.titles = titles
        self.params = params
        self.client = client
        if prop:
            self._set_properties(prop)

    # region Alternate Constructors

    @classmethod
    def search(
        cls, client: MediaWikiClient, query: str, search_type: str = 'nearmatch', limit: int = 10, offset: int = None
    ) -> Query:
        params = {
            # 'srprop': ['timestamp', 'snippet', 'redirecttitle', 'categorysnippet']
        }
        if search_type is not None:
            params['srwhat'] = search_type
        if offset is not None:
            params['sroffset'] = offset
        return cls(client, list='search', srsearch=query, srlimit=limit, **params)

    @classmethod
    def categories(cls, client: MediaWikiClient, titles: Titles) -> Query:
        return cls(client, titles=titles, prop='categories')

    @classmethod
    def content(cls, client: MediaWikiClient, titles: Titles) -> Query:
        return cls(client, titles=titles, rvprop='content', prop='revisions')

    @classmethod
    def image_titles(cls, client: MediaWikiClient, titles: Titles) -> Query:
        return cls(client, prop='images', titles=titles)

    @classmethod
    def image_info(cls, client: MediaWikiClient, titles: Titles, img_properties: StrOrStrs) -> Query:
        return cls(client, prop='imageinfo', titles=titles, iiprop=img_properties)

    # endregion

    def _set_properties(self, properties: Collection[str]):
        if isinstance(properties, str):
            properties = {properties}
        elif not isinstance(properties, set):
            properties = set(properties)

        self.params['prop'] = properties
        if 'iwlinks' in properties:  # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Iwlinks
            if self.client.mw_version >= LooseVersion('1.24'):
                self.params['iwprop'] = 'url'
            else:
                self.params['iwurl'] = 1

        if 'categories' in properties:  # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Categories
            self.params['cllimit'] = 500  # default: 10

        if 'revisions' in properties:  # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Revisions
            if self.client.mw_version >= LooseVersion('1.32'):
                self.params['rvslots'] = 'main'

    def get_results(self) -> TitleDataMap:
        """
        :return: Mapping of {title: dict(results)}
        """
        return {
            title: page.data
            for params in self._param_page_iter()
            for title, page in self._get_paginated_results(params).items()
        }

    def _param_page_iter(self) -> Iterator[dict[str, Any]]:
        """
        When requesting a large number of titles, the requests for those titles must be split so that each query
        requests a maximum of 50 titles.
        """
        params = _normalize_params(self.params.copy(), self.client.mw_version)
        if titles := self.titles:
            if isinstance(titles, str):
                params['titles'] = titles
                yield params
            elif len(titles) <= 50:
                params['titles'] = _multi_value_param(titles)
                yield params
            else:
                for group in partitioned(list(titles), 50):
                    yield {'titles': _multi_value_param(group), **params}
        else:
            yield params

    def _get_paginated_results(self, params: dict[str, Any]) -> dict[str, PageData]:
        query_resp = QueryResponse(self, self.client.get('api.php', params=params))
        title_page_map, prop_continue, other_continue = query_resp.parse()
        while prop_continue or other_continue:
            continue_params = deepcopy(params)
            if prop_continue:
                continue_params['prop'] = '|'.join(prop_continue.keys())
                for continue_cmd in prop_continue.values():
                    continue_params.update(continue_cmd)
            if other_continue:
                continue_params.update(other_continue)

            query_resp = QueryResponse(self, self.client.get('api.php', params=continue_params))
            new_tpm, prop_continue, other_continue = query_resp.parse()
            # log.debug(f'From {resp.url=} - new_tpm.keys()={new_tpm.keys()}')
            for title, new_page_data in new_tpm.items():
                try:
                    page_data = title_page_map[title]
                except KeyError:
                    title_page_map[title] = new_page_data
                else:
                    page_data.update(new_page_data.data)

        return title_page_map


class QueryResponse:
    __slots__ = ('query', 'resp')

    def __init__(self, query: Query, resp: Response):
        self.query = query
        self.resp = resp

    def _get_resp_dict(self):
        if not (response := self.resp.json()):
            log.debug(f'Response from {self.resp.url} was empty.')
            return {}
        try:
            error = response['error']
        except KeyError:
            return response
        except TypeError:
            log.warning(f'Response from {self.resp.url} was not a dict; found: {response}')
            return {}

        if 'query' not in response:
            raise WikiResponseError(dumps(error))
        elif error:
            log.warning(f'An error was encountered, but query results were found for {self.resp.url}: {error}')

        return response

    def parse(self) -> tuple[dict[str, PageData], Any, Any]:
        if not (response := self._get_resp_dict()):
            return response, None, None

        try:
            results = response['query']
        except KeyError:
            if len(response) != 1 or not response.get('batchcomplete'):
                log.debug(f'Response from {self.resp.url} contained no \'query\' key; found: {", ".join(response)}')
            # log.debug(f'Complete response: {dumps(response, sort_keys=True, indent=4)}')
            return {}, None, None

        if 'pages' in results:
            parsed = self._parse_query_pages(results)
        elif 'allcategories' in results:
            parsed = {row['category']: row['size'] for row in results['allcategories']}
        elif 'search' in results:
            parsed = {row['title']: row for row in results['search']}
        else:
            query_keys = ', '.join(results)
            log.debug(f'Query results from {self.resp.url} did not contain any handled keys; found: {query_keys}')
            return {}, None, None

        prop_continue = response.get('query-continue')
        other_continue = response.get('continue')
        return parsed, prop_continue, other_continue

    def _parse_query_pages(self, results: dict[str, Any]) -> dict[str, PageData]:
        redirects = results.get('redirects', [])
        redirects = {r['to']: r['from'] for r in (redirects.values() if isinstance(redirects, dict) else redirects)}
        if isinstance((pages := results['pages']), dict):
            pages = pages.values()

        mw_version = self.query.client.mw_version
        parsed = (PageData.from_query_resp(page, redirects, mw_version) for page in pages)
        return {page.title: page for page in parsed}


class PageData:
    _skip_merge = {'pageid', 'ns', 'title', 'redirected_from'}
    __slots__ = ('title', 'data')

    def __init__(self, title: str, data: dict[str, Any]):
        self.title = title
        self.data = data

    @classmethod
    def from_query_resp(cls, data: dict[str, Any], redirects: dict[str, str], mw_version: LooseVersion) -> PageData:
        if mw_version >= LooseVersion('1.25'):
            iw_key, rev_key = 'title', 'content'
        else:
            iw_key, rev_key = '*', '*'

        title = data['title']
        qlog.debug(f'Processing page with title={title!r}, keys: {", ".join(sorted(data))}')
        # if 'revisions' not in page:
        #     qlog.debug(f' > Content: {dumps(page, sort_keys=True, indent=4)}')
        if redirected_from := redirects.get(title):
            content = {'redirected_from': redirected_from}
        else:
            content = {}

        for key, val in data.items():
            if key == 'revisions':
                if mw_version >= LooseVersion('1.32'):
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

        return cls(title, content)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.title!r}]>'

    def update(self, data: dict[str, Any]):
        for key, val in data.items():
            if key == 'iwlinks':
                self._update_iw_links(val)
            else:
                self._update_value(key, val)

    def _update_iw_links(self, iw_link_map: defaultdict[str, dict[str, str]]):
        try:
            link_map = self.data['iwlinks']
        except KeyError:
            self.data['iwlinks'] = link_map = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}

        for iw_name, iw_links in iw_link_map.items():
            link_map[iw_name].update(iw_links)

    def _update_value(self, key: str, value):
        try:
            full_val = self.data[key]
        except KeyError:
            self.data[key] = value
        else:
            if isinstance(full_val, list):
                full_val.extend(value)
            elif isinstance(full_val, dict):
                full_val.update(value)
            elif isinstance(full_val, int):
                self.data[key] = value
            elif key in self._skip_merge:
                pass
            else:
                if value is not None and full_val is None:
                    self.data[key] = value
                elif value == full_val:
                    pass
                else:
                    val_type = full_val.__class__.__name__
                    log.error(f'Unexpected merge value for {self} {key=} {val_type=} {full_val=} new {value=}')

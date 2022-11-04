"""
Functionality related to using the `Parse API <https://www.mediawiki.org/wiki/API:Parse>`__
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Collection

from .utils import _normalize_params

if TYPE_CHECKING:
    from ..typing import StrOrStrs
    from .client import MediaWikiClient

__all__ = ['Parse']


class Parse:
    """
    Submit, then parse and transform a `parse request <https://www.mediawiki.org/wiki/API:Parse>`_

    The parse API only accepts one page at a time.

    :param client: The MediaWikiClient through which the query will be submitted
    :param params: Parse API parameters
    """
    __slots__ = ('client', 'params')

    def __init__(self, client: MediaWikiClient, *, prop: StrOrStrs = None, **params):
        params['action'] = 'parse'
        params['redirects'] = 1
        self.params = params
        self.client = client
        if prop:
            self._set_properties(prop)

    @classmethod
    def page(cls, client: MediaWikiClient, page: str) -> Parse:
        return cls(client, page=page, prop=['wikitext', 'text', 'categories', 'links', 'iwlinks', 'displaytitle'])

    def _set_properties(self, properties: Collection[str]):
        if isinstance(properties, str):
            properties = {properties}
        elif not isinstance(properties, set):
            properties = set(properties)

        self.params['prop'] = properties
        if 'text' in properties:
            self.params['disabletoc'] = 1
            self.params['disableeditsection'] = 1

    def get_results(self) -> dict[str, Any]:
        params = _normalize_params(self.params.copy(), self.client.mw_version)
        resp = self.client.get('api.php', params=params)
        return _normalize_parse_page_data(resp.json()['parse'])


def _normalize_parse_page_data(data: dict[str, Any]) -> dict[str, Any]:
    content = {}
    for key, val in data.items():
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

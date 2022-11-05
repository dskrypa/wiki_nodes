"""
MediaWikiClient utilities.
"""

from __future__ import annotations

import re
from typing import Iterable, Union, Any, Collection
from urllib.parse import urlparse, unquote

from ..version import LooseVersion

URL_MATCH = re.compile('^[a-zA-Z]+://').match

TitleDataMap = dict[str, dict[str, Any]]
PageEntry = dict[str, Union[str, list[str], None]]
TitleEntryMap = dict[str, PageEntry]
Titles = Union[str, Collection[str]]


def normalize_title(title: str) -> str:
    return unquote(title.replace('_', ' ').strip())


def _normalize_params(params: dict[str, Any], mw_version: LooseVersion) -> dict[str, Any]:
    """Include useful default parameters, and handle conversion of lists/tuples/sets to pipe-delimited strings."""
    params['format'] = 'json'
    if mw_version >= LooseVersion('1.25'):  # https://www.mediawiki.org/wiki/API:JSON_version_2
        params['formatversion'] = 2
    params['utf8'] = 1
    for key, val in params.items():
        if isinstance(val, Collection) and not isinstance(val, str):
            params[key] = _multi_value_param(val)

    return params


def _multi_value_param(value: Iterable[Any]) -> str:
    # TODO: Figure out U+001F usage when a value containing | is found
    # Docs: If | in value, use U+001F as the separator & prefix value with it, e.g. param=%1Fvalue1%1Fvalue2
    return '|'.join(map(str, value))
    # return ''.join(map('\u001f{}'.format, val))    # doesn't work for vals without |


def _normalize_file_name(title_or_url: str) -> str:
    try:
        file_name_match = _normalize_file_name._file_name_match
    except AttributeError:
        file_name_match = _normalize_file_name._file_name_match = re.compile(r'.*\.\w{3,4}$').match

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

from __future__ import annotations

from typing import Iterable, Union, Any, Collection

from ..version import LooseVersion

TitleDataMap = dict[str, dict[str, Any]]
PageEntry = dict[str, Union[str, list[str], None]]
TitleEntryMap = dict[str, PageEntry]
Titles = Union[str, Iterable[str]]


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

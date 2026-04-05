from collections.abc import Collection
from typing import Any, TypedDict

StrOrStrs = str | Collection[str] | None
OptStr = str | None


class PageEntry(TypedDict):
    title: str
    wikitext: str
    categories: Collection[str]


TitleEntryMap = dict[str, PageEntry]
TitleDataMap = dict[str, dict[str, Any]]
Titles = str | Collection[str]

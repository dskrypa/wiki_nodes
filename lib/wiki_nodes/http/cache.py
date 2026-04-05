"""
Caching for wiki pages, images, searches, etc.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, TypedDict

from db_cache import DBCache, TTLDBCache
from db_cache.utils import get_user_cache_dir

from .utils import normalize_title

if TYPE_CHECKING:
    from ._typing import Titles

    PathLike = str | Path
    Memory = Literal[':memory:']

    class CacheState(TypedDict):
        ttl: int
        base_dir: Path | Memory
        img_dir: Path


__all__ = ['WikiCache']
log = logging.getLogger(__name__)


class WikiCache:
    __slots__ = ('ttl', 'base_dir', 'img_dir', 'pages', 'search_titles', 'searches', 'normalized_titles', 'misc')

    ttl: int
    pages: TTLDBCache
    search_titles: TTLDBCache
    searches: TTLDBCache
    normalized_titles: DBCache
    misc: TTLDBCache
    base_dir: Path | Memory
    img_dir: Path

    def __init__(self, host: str, ttl: int = 21_600, base_dir: PathLike | None = None, img_dir: PathLike | None = None):
        self.ttl = ttl  # Note: default value of 21_600 = 3600 * 6 (6 hours)
        self.base_dir = _prep_dir(base_dir, f'wiki/{host}')
        self.reset_caches(False)
        self.img_dir = _prep_dir(img_dir, f'wiki/{host}/images')  # type: ignore

    def __getstate__(self) -> CacheState:
        return {'ttl': self.ttl, 'base_dir': self.base_dir, 'img_dir': self.img_dir}

    def __setstate__(self, state: CacheState):
        self.ttl = state['ttl']
        self.base_dir = state['base_dir']
        self.img_dir = state['img_dir']
        self.reset_caches(False)

    def reset_caches(self, hard: bool = False):
        cache_dir = self.base_dir
        if hard and cache_dir != ':memory:':
            for path in cache_dir.glob('*.db'):
                if path.is_file():
                    log.debug(f'Deleting cache file: {path.as_posix()}')
                    path.unlink()

        key = 'db_path' if cache_dir == ':memory:' else 'cache_dir'
        kwargs = {key: cache_dir, 'ttl': self.ttl}
        self.pages = TTLDBCache('pages', **kwargs)
        self.search_titles = TTLDBCache('search_titles', **kwargs)
        self.searches = TTLDBCache('searches', **kwargs)
        # All keys in normalized_titles should be normalized to upper case to improve matching and prevent dupes
        self.normalized_titles = DBCache('normalized_titles', time_fmt='%Y', **{key: cache_dir})
        self.misc = TTLDBCache('misc', **kwargs)

    def get_misc(self, group: str, titles: Titles) -> tuple[list[str], dict[str, Any]]:
        titles = [titles] if isinstance(titles, str) else titles
        needed = []
        found = {}
        for title in titles:
            try:
                found[title] = self.misc[(group, normalize_title(title))]
            except KeyError:
                needed.append(title)
        # log.debug(f'Found for {group=} cached={found.keys()} {needed=}')
        return needed, found

    def store_misc(self, group: str, data: Mapping[str, Any]):
        # log.debug(f'Storing for {group=} keys={data.keys()}')
        self.misc.update({(group, normalize_title(title)): value for title, value in data.items()})

    def get_image(self, name: str | None) -> bytes:
        if name:
            path = self.img_dir.joinpath(name)
            if path.exists():
                log.debug(f'Found cached image for {name=}')
                return path.read_bytes()
        raise KeyError(name)

    def store_image(self, name: str | None, data: bytes):
        if name:
            self.img_dir.joinpath(name).write_bytes(data)


def _prep_dir(path: PathLike | None, default: str) -> Path | Memory:
    if path:
        if path == ':memory:':
            return path

        path: Path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    return get_user_cache_dir(default)

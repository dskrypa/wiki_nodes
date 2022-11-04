"""
Caching for wiki pages, images, searches, etc.
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union, Any, Mapping

from requests import Response

from db_cache import TTLDBCache, DBCache
from db_cache.utils import get_user_cache_dir

from .utils import Titles, normalize_title

if TYPE_CHECKING:
    from ..typing import PathLike

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

    def __init__(self, host: str, ttl: int = 21_600, base_dir: PathLike = None, img_dir: PathLike = None):
        self.ttl = ttl  # Note: default value of 21_600 = 3600 * 6 (6 hours)
        self.base_dir = Path(base_dir or get_user_cache_dir(f'wiki/{host}'))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.reset_caches(False)
        self.img_dir = Path(img_dir or get_user_cache_dir(f'wiki/{host}/images'))
        self.img_dir.mkdir(parents=True, exist_ok=True)

    def __getstate__(self) -> dict[str, Union[int, Path]]:
        return {'ttl': self.ttl, 'base_dir': self.base_dir, 'img_dir': self.img_dir}

    def __setstate__(self, state: dict[str, Union[int, Path]]):
        self.ttl = state['ttl']
        self.base_dir = state['base_dir']
        self.img_dir = state['img_dir']
        self.reset_caches(False)

    def reset_caches(self, hard: bool = False):
        cache_dir = self.base_dir
        if hard:
            for path in cache_dir.iterdir():
                if path.is_file() and path.suffix == '.db':
                    log.debug(f'Deleting cache file: {path.as_posix()}')
                    path.unlink()

        self.pages = TTLDBCache('pages', cache_dir=cache_dir, ttl=self.ttl)
        self.search_titles = TTLDBCache('search_titles', cache_dir=cache_dir, ttl=self.ttl)
        self.searches = TTLDBCache('searches', cache_dir=cache_dir, ttl=self.ttl)
        # All keys in normalized_titles should be normalized to upper case to improve matching and prevent dupes
        self.normalized_titles = DBCache('normalized_titles', cache_dir=cache_dir, time_fmt='%Y')
        self.misc = TTLDBCache('misc', cache_dir=cache_dir, ttl=self.ttl)

    def store_response(self, resp: Response):
        now = datetime.now()
        resp_dir = self.base_dir.joinpath('responses', now.strftime('%Y-%m-%d'))
        if not resp_dir.exists():
            resp_dir.mkdir(parents=True)
        resp_dir.joinpath(f'{now.timestamp()}.url').write_text(resp.url + '\n', encoding='utf-8')
        with resp_dir.joinpath(f'{now.timestamp()}.pkl').open('wb') as f:
            pickle.dump(resp, f)

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

    def get_image(self, name: Optional[str]) -> bytes:
        if name:
            path = self.img_dir.joinpath(name)
            if path.exists():
                log.debug(f'Found cached image for {name=}')
                return path.read_bytes()
        raise KeyError(name)

    def store_image(self, name: Optional[str], data: bytes):
        if name:
            self.img_dir.joinpath(name).write_bytes(data)

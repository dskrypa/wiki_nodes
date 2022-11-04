#!/usr/bin/env python

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ContextManager
from unittest import TestCase, main

from wiki_nodes.http.cache import WikiCache


@contextmanager
def wiki_cache(*args, **kwargs) -> ContextManager[WikiCache]:
    with TemporaryDirectory() as td:
        temp_dir = Path(td)
        base_dir, img_dir = temp_dir.joinpath('base'), temp_dir.joinpath('img')
        yield WikiCache(*args, base_dir=base_dir, img_dir=img_dir, **kwargs)


class CacheTest(TestCase):
    def test_deepcopy_cache(self):
        with wiki_cache('', 12345) as cache:
            clone = deepcopy(cache)
            self.assertFalse(cache is clone)
            self.assertEqual(12345, clone.ttl)
            self.assertEqual(cache.base_dir, clone.base_dir)
            self.assertEqual(cache.img_dir, clone.img_dir)

    def test_store_get_image(self):
        with wiki_cache('') as cache:
            cache.store_image('foo', b'abc')
            cache.store_image('', b'def')
            self.assertEqual(1, len(list(cache.img_dir.iterdir())))
            self.assertEqual(b'abc', cache.get_image('foo'))
            with self.assertRaises(KeyError):
                cache.get_image('bar')
            with self.assertRaises(KeyError):
                cache.get_image('')

    def test_store_get_misc(self):
        with wiki_cache('') as cache:
            cache.store_misc('foo', {'bar': 'baz'})
            needed, found = cache.get_misc('foo', ['bar', 'baz'])
            self.assertEqual(['baz'], needed)
            self.assertEqual({'bar': 'baz'}, found)

    def test_reset_hard(self):
        with wiki_cache('') as cache:
            other_path = cache.base_dir.joinpath('foo.bar')
            db_path = cache.base_dir.joinpath('foo.db')
            other_path.touch()
            db_path.touch()
            cache.reset_caches()
            self.assertTrue(other_path.exists())
            self.assertTrue(db_path.exists())
            cache.reset_caches(True)
            self.assertTrue(other_path.exists())
            self.assertFalse(db_path.exists())


if __name__ == '__main__':
    main(exit=False, verbosity=2)

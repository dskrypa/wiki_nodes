#!/usr/bin/env python

from copy import deepcopy
from unittest import TestCase, main

from wiki_nodes.http.cache import WikiCache
from wiki_nodes.testing import wiki_cache


class CacheTest(TestCase):
    def test_deepcopy_cache(self):
        with wiki_cache('', 12345, base_dir=':memory:') as cache:
            clone = deepcopy(cache)
            self.assertFalse(cache is clone)
            self.assertEqual(12345, clone.ttl)
            self.assertEqual(cache.base_dir, clone.base_dir)
            self.assertEqual(cache.img_dir, clone.img_dir)

    def test_store_get_image(self):
        with wiki_cache('', base_dir=':memory:') as cache:
            cache.store_image('foo', b'abc')
            cache.store_image('', b'def')
            self.assertEqual(1, len(list(cache.img_dir.iterdir())))
            self.assertEqual(b'abc', cache.get_image('foo'))
            with self.assertRaises(KeyError):
                cache.get_image('bar')
            with self.assertRaises(KeyError):
                cache.get_image('')

    def test_store_get_misc(self):
        cache = WikiCache('', base_dir=':memory:', img_dir=':memory:')
        cache.store_misc('foo', {'bar': 'baz'})
        needed, found = cache.get_misc('foo', ['bar', 'baz'])
        self.assertEqual(['baz'], needed)
        self.assertEqual({'bar': 'baz'}, found)

    def test_reset_hard(self):
        with wiki_cache('', img_dir=':memory:') as cache:
            dir_path = cache.base_dir.joinpath('bar.db')
            dir_path.mkdir()
            other_path = cache.base_dir.joinpath('foo.bar')
            db_path = cache.base_dir.joinpath('foo.db')
            other_path.touch()
            db_path.touch()
            cache.reset_caches()
            self.assertTrue(dir_path.exists())
            self.assertTrue(other_path.exists())
            self.assertTrue(db_path.exists())
            cache.reset_caches(True)
            self.assertTrue(dir_path.exists())
            self.assertTrue(other_path.exists())
            self.assertFalse(db_path.exists())


if __name__ == '__main__':
    main(exit=False, verbosity=2)

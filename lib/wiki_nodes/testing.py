"""
Helpers for unit tests

:author: Doug Skrypa
"""

from __future__ import annotations

import json
import sys
from contextlib import AbstractContextManager
from difflib import unified_diff
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import Mock, seal, patch

from .http import MediaWikiClient, WikiCache
from .utils import rich_repr

__all__ = ['WikiNodesTest', 'format_diff', 'sealed_mock', 'RedirectStreams', 'mocked_client', 'get_siteinfo']

TEST_DATA_DIR = Path(__file__).resolve().parents[2].joinpath('tests', 'data')


class WikiNodesTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._mwc_request_patch = patch.object(MediaWikiClient, 'request')  # Prevent any actual requests from leaking
        cls._mwc_request_patch.start()  # noqa
        cls._wiki_cache_reset_patch = patch.object(WikiCache, 'reset_caches')
        cls._wiki_cache_reset_patch.start()  # noqa
        cls._wiki_cache_init_patch = patch.object(WikiCache, '__init__', return_value=None)
        cls._wiki_cache_init_patch.start()  # noqa
        MediaWikiClient._siteinfo_cache = Mock()

    @classmethod
    def tearDownClass(cls):
        cls._mwc_request_patch.stop()  # noqa
        cls._wiki_cache_reset_patch.stop()  # noqa
        cls._wiki_cache_init_patch.stop()  # noqa

    def tearDown(self):
        MediaWikiClient._instances.clear()

    def assert_dict_equal(self, d1, d2, msg: str = None):
        self.assertIsInstance(d1, dict, 'First argument is not a dictionary')
        self.assertIsInstance(d2, dict, 'Second argument is not a dictionary')
        if d1 != d2:
            standard_msg = f'{d1} != {d2}\n{format_dict_diff(d1, d2)}'
            self.fail(self._formatMessage(msg, standard_msg))

    def assert_equal(self, expected, actual, msg: str = None):
        if expected != actual:
            diff_str = format_diff(rich_repr(expected), rich_repr(actual))
            if not diff_str.strip():
                self.assertEqual(expected, actual, msg)  # Provides a generic diff / message
            else:
                suffix = f'\n{msg}' if msg else ''
                self.fail(f'Objects did not match:\n{diff_str}{suffix}')

    def assert_strings_equal(
        self, expected: str, actual: str, message: str = None, diff_lines: int = 3, trim: bool = False
    ):
        if trim:
            expected = expected.rstrip()
            actual = '\n'.join(line.rstrip() for line in actual.splitlines())
        if message:
            self.assertEqual(expected, actual, message)
        elif expected != actual:
            diff = format_diff(expected, actual, n=diff_lines)
            if not diff.strip():
                self.assertEqual(expected, actual)
            else:
                self.fail('Strings did not match:\n' + diff)

    def assert_str_contains(self, sub_text: str, text: str, diff_lines: int = 3):
        if sub_text not in text:
            diff = format_diff(sub_text, text, n=diff_lines)
            self.fail('String did not contain expected text:\n' + diff)


def _colored(text: str, color: int, end: str = '\n'):
    return f'\x1b[38;5;{color}m{text}\x1b[0m{end}'


def format_diff(a: str, b: str, name_a: str = 'expected', name_b: str = '  actual', n: int = 3) -> str:
    sio = StringIO()
    a = a.splitlines()
    b = b.splitlines()
    for i, line in enumerate(unified_diff(a, b, name_a, name_b, n=n, lineterm='')):
        if line.startswith('+') and i > 1:
            sio.write(_colored(line, 2))
        elif line.startswith('-') and i > 1:
            sio.write(_colored(line, 1))
        elif line.startswith('@@ '):
            sio.write(_colored(line, 6, '\n\n'))
        else:
            sio.write(line + '\n')

    return sio.getvalue()


def format_dict_diff(a: dict[str, Any], b: dict[str, Any]) -> str:
    formatted_a = []
    formatted_b = []
    for key in sorted(set(a) | set(b)):
        try:
            val_a = a[key]
        except KeyError:
            str_b = f'{key!r}: {b[key]!r}'
            formatted_a.append(' ' * len(str_b))
            formatted_b.append(_colored(str_b, 2, ''))
        else:
            str_a = f'{key!r}: {val_a!r}'
            try:
                val_b = b[key]
            except KeyError:
                str_b = ' ' * len(str_a)
                formatted_a.append(_colored(str_a, 1, ''))
                formatted_b.append(str_b)
            else:
                str_b = f'{key!r}: {val_b!r}'
                if val_a == val_b:
                    formatted_a.append(str_a)
                    formatted_b.append(str_b)
                else:
                    formatted_a.append(_colored(str_a, 2, ''))
                    formatted_b.append(_colored(str_b, 1, ''))

    kvs_a = ', '.join(formatted_a)
    kvs_b = ', '.join(formatted_b)
    return f'- {{{kvs_a}}}\n+ {{{kvs_b}}}'


def sealed_mock(*args, **kwargs):
    kwargs.setdefault('return_value', None)
    mock = Mock(*args, **kwargs)
    seal(mock)
    return mock


class RedirectStreams(AbstractContextManager):
    def __init__(self):
        self._old = {}
        self._stdout = StringIO()
        self._stderr = StringIO()

    @property
    def stdout(self) -> str:
        return self._stdout.getvalue()

    @property
    def stderr(self) -> str:
        return self._stderr.getvalue()

    def __enter__(self) -> RedirectStreams:
        streams = {'stdout': self._stdout, 'stderr': self._stderr}
        for name, io in streams.items():
            self._old[name] = getattr(sys, name)
            setattr(sys, name, io)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        while self._old:
            name, orig = self._old.popitem()
            setattr(sys, name, orig)


@lru_cache(5)
def get_siteinfo(site: str):
    with TEST_DATA_DIR.joinpath('siteinfo').joinpath(f'{site}.json').open('r', encoding='utf-8') as f:
        return json.load(f)


def mocked_client(site: str):
    client = MediaWikiClient(site)
    try:
        siteinfo = get_siteinfo(site)
    except FileNotFoundError:
        pass
    else:
        client.__dict__['siteinfo'] = siteinfo

    return client

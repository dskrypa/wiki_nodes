"""
Helpers for unit tests

:author: Doug Skrypa
"""

from __future__ import annotations

import json
import sys
from contextlib import AbstractContextManager, contextmanager
from difflib import unified_diff
from functools import lru_cache
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ContextManager
from unittest import TestCase
from unittest.mock import Mock, seal, patch

from .http.cache import WikiCache
from .http.client import MediaWikiClient
from .utils import rich_repr

__all__ = [
    'WikiNodesTest',
    'format_diff',
    'sealed_mock',
    'RedirectStreams',
    'mocked_client',
    'get_siteinfo',
    'get_api_resp_data',
    'mock_response',
    'wiki_cache',
]

TEST_DATA_DIR = Path(__file__).resolve().parents[2].joinpath('tests', 'data')


class WikiNodesTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Prevent any actual requests from leaking
        cls._mwc_request_patch = patch.object(MediaWikiClient, 'request')
        cls._mwc_request_patch.start()  # noqa
        # Avoid relatively heavy introspection during frequent client init
        cls._generate_user_agent_patch = patch('requests_client.client.generate_user_agent', return_value='FAKE_UA')
        cls._generate_user_agent_patch.start()  # noqa
        # Prevent TTLDBCache init during client instance init
        MediaWikiClient._siteinfo_cache = Mock()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._mwc_request_patch.stop()  # noqa
        cls._generate_user_agent_patch.stop()  # noqa

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


class WikiNodesTest(WikiNodesTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Prevent unintended fs access
        cls._wiki_cache_reset_patch = patch.object(WikiCache, 'reset_caches')
        cls._wiki_cache_reset_patch.start()  # noqa
        # Prevent unintended dir/file creation
        cls._wiki_cache_init_patch = patch.object(WikiCache, '__init__', return_value=None)
        cls._wiki_cache_init_patch.start()  # noqa

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._wiki_cache_reset_patch.stop()  # noqa
        cls._wiki_cache_init_patch.stop()  # noqa


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


@lru_cache(5)
def get_api_resp_data(name: str):
    with TEST_DATA_DIR.joinpath('api_responses').joinpath(f'{name}.json').open('r', encoding='utf-8') as f:
        return json.load(f)


def mock_response(json_data=None, **kwargs):
    if not isinstance(json_data, list):
        json_data = [json_data]
    return Mock(json=Mock(side_effect=json_data), **kwargs)


def mocked_client(site: str, **kwargs):
    client = MediaWikiClient(site, **kwargs)
    try:
        siteinfo = get_siteinfo(site)
    except FileNotFoundError:
        pass
    else:
        client.__dict__['siteinfo'] = siteinfo

    return client


def _dump_site_info(client: MediaWikiClient) -> str:
    sio = StringIO()
    sio.write('{\n')
    last = len(client.siteinfo)
    for i, (key, value) in enumerate(sorted(client.siteinfo.items()), 1):
        suffix = ',\n' if i < last else '\n'
        if key == 'interwikimap':
            sio.write(f'    "{key}": [\n')
            sio.write(',\n'.join('        ' + json.dumps(row, sort_keys=True, ensure_ascii=False) for row in value))
            sio.write(f'\n    ]{suffix}')
        else:
            serialized = json.dumps(value, sort_keys=True, indent=4, ensure_ascii=False)
            if serialized.startswith(('{\n', '[\n')):
                lines = serialized.splitlines()
                sio.write(f'    "{key}": {lines[0]}\n')
                sio.write('\n'.join('    ' + line for line in lines[1:-1]))
                sio.write(f'\n    {lines[-1]}{suffix}')
            else:
                sio.write(f'    "{key}": {serialized}{suffix}')
    sio.write('}')
    return sio.getvalue()


@contextmanager
def wiki_cache(*args, **kwargs) -> ContextManager[WikiCache]:
    with TemporaryDirectory() as td:
        temp_dir = Path(td)
        kwargs.setdefault('base_dir', temp_dir.joinpath('base'))
        kwargs.setdefault('img_dir', temp_dir.joinpath('img'))
        yield WikiCache(*args, **kwargs)

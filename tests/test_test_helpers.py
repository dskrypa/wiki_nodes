#!/usr/bin/env python

import sys
from unittest import main, TestCase

from wiki_nodes.testing import WikiNodesTest, sealed_mock, RedirectStreams


class TestHelperTest(TestCase):
    def test_assert_strings_equal(self):
        self.assertIs(None, WikiNodesTest().assert_strings_equal('foo', 'foo'))
        self.assertIs(None, WikiNodesTest().assert_strings_equal('foo', 'foo  ', trim=True))
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_strings_equal('foo', 'bar')
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_strings_equal('foo', 'bar', 'baz')

    def test_assert_str_contains(self):
        self.assertIs(None, WikiNodesTest().assert_str_contains('a', 'aa'))
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_str_contains('a', 'b')

    def test_assert_dict_equal(self):
        self.assertIs(None, WikiNodesTest().assert_dict_equal({'a': 1}, {'a': 1}))
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_dict_equal({'a': 1, 'b': 3}, {'a': 2, 'b': 3})
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_dict_equal({'a': 1}, {'b': 1})

    def test_assert_equal(self):
        self.assertIs(None, WikiNodesTest().assert_equal({'a': 1}, {'a': 1}))
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_equal({'a': 1, 'b': 3}, {'a': 2, 'b': 3})
        with self.assertRaises(AssertionError):
            WikiNodesTest().assert_equal({'a': 1}, {'b': 1})

    def test_assert_str_eq_newline_missing(self):
        try:
            WikiNodesTest().assert_strings_equal('[[test]]', '[[test]]\n')
        except AssertionError as e:
            self.assertIn('- [[test]]\n+ [[test]]\n\n?         \n+\n', str(e))
        else:
            self.fail('No AssertionError was raised')

    def test_sealed_mock(self):
        with self.assertRaises(AttributeError):
            _ = sealed_mock().foo

    def test_redirect_stderr(self):
        with RedirectStreams() as streams:
            print('test', file=sys.stderr)

        self.assertEqual('test\n', streams.stderr)


if __name__ == '__main__':
    try:
        main(verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()

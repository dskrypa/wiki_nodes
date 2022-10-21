#!/usr/bin/env python

from unittest import main

from wiki_nodes import Template, String
from wiki_nodes.page import WikiPage
from wiki_nodes.testing import WikiNodesTest
from wiki_nodes.nodes.typing import is_compound_with_ele, is_container_with_ele


class TypingTest(WikiNodesTest):
    def test_is_compound_with_template_ele(self):
        page = WikiPage('test', None, "{{For|other uses|foo}}'''bar''' baz")
        self.assertTrue(is_compound_with_ele(page.sections.content, 0, Template, lc_name='for'))
        self.assertTrue(is_compound_with_ele(page.sections.content, 0, Template))
        self.assertFalse(is_compound_with_ele(page.sections.content, 9, String))
        self.assertFalse(is_compound_with_ele(page.sections.content, 0, String))
        self.assertFalse(is_compound_with_ele(page.sections.content[0], 0, Template, lc_name='bar'))
        self.assertFalse(is_compound_with_ele(page.sections.content, 0, Template, lc_name='bar'))
        self.assertFalse(is_compound_with_ele(page.sections.content, 0, Template, lc_name='for', foo='bar'))

    def test_is_container_with_template_ele(self):
        page = WikiPage('test', None, "{{For|other uses|foo}}'''bar''' baz")
        self.assertTrue(is_container_with_ele(page.sections.content, 0, Template, lc_name='for'))
        self.assertFalse(is_container_with_ele(page.sections.content, 0, Template, lc_name='bar'))
        self.assertFalse(is_container_with_ele(page.sections.content[0], 0, Template, lc_name='bar'))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

#!/usr/bin/env python

from textwrap import dedent
from unittest import main
from unittest.mock import Mock

from wiki_nodes.nodes import Section, Root, List, ListEntry, CompoundNode
from wiki_nodes.nodes.transformers import dl_key_content_pairs, transform_section, merge_map_chain, fix_nested_dl_ul_ol
from wiki_nodes.nodes.transformers import dl_keys_to_subsections, convert_hanging_dl_lists, convert_lists_to_maps
from wiki_nodes.testing import WikiNodesTest


class SectionTransformerTest(WikiNodesTest):
    def test_skips(self):
        funcs = (
            transform_section, dl_keys_to_subsections, convert_lists_to_maps,
            convert_hanging_dl_lists, fix_nested_dl_ul_ol, merge_map_chain
        )
        original = Section('==foo==\nbar', Mock())
        for func in funcs:
            section, content = func(original)
            self.assertIs(original, section)

    def test_dl_key_content_pairs_no_content(self):
        transformed = list(dl_key_content_pairs(CompoundNode(' ')))
        self.assertEqual(0, len(transformed))

    # region dl_keys_to_subsections

    def test_dl_keys_to_subsections(self):
        original_text = (
            '==Track list==\n'
            ';Digital\n#"foo abc" - 2:54\n#"bar def" - 3:12\n#"baz ghi" - 3:47\n'
            ';Physical\n#"foo rst" - 3:18\n#"bar uvw" - 2:46\n#"baz xyz" - 2:29\n'
        )
        original = Section(original_text, Mock(site='foo', title='bar'))
        self.assertEqual(0, len(original.children))

        section, content = dl_keys_to_subsections(original)
        self.assertIsNot(original, section)
        self.assertNotEqual(original, section)
        self.assertEqual(0, len(original.children))

        self.assertEqual(0, len(content))
        self.assertEqual(2, len(section.children))
        for name in ('Digital', 'Physical'):
            with self.subTest(name=name):
                sub_section = section.children[name]
                self.assertEqual(name, sub_section.title)
                self.assertEqual(3, len(sub_section.content))

    def test_dl_keys_to_subsections_no_clone(self):
        original_text = (
            '==Track list==\n'
            ';Digital\n#"foo abc" - 2:54\n#"bar def" - 3:12\n#"baz ghi" - 3:47\n'
            ';Physical\n#"foo rst" - 3:18\n#"bar uvw" - 2:46\n#"baz xyz" - 2:29\n'
        )
        original = Section(original_text, Mock(site='foo', title='bar'))
        self.assertEqual(0, len(original.children))
        section, content = dl_keys_to_subsections(original, False)
        self.assertIs(original, section)
        self.assertEqual(2, len(original.children))
        self.assertEqual(2, len(section.children))

    def test_dl_keys_to_subsections_non_compound(self):
        original = Section('==foo==\nbar', Mock())
        section, content = dl_keys_to_subsections(original)
        self.assertIs(original, section)

    def test_dl_keys_to_subsections_non_dl(self):
        original = Section('==foo==\n#"foo abc" - 2:54\n#"bar def" - 3:12\n#"baz ghi" - 3:47\n', Mock())
        section, content = dl_keys_to_subsections(original)
        self.assertIsNot(original, section)
        self.assertEqual(original, section)
        self.assertEqual(original.content, content)

    def test_dl_keys_to_subsections_with_header_link(self):
        original_text = '==Track list==\n;Foo [[bar]]\n#"foo abc" - 2:54\n#"bar def" - 3:12\n#"baz ghi" - 3:47\n'
        original = Section(original_text, Mock(site='foo', title='bar'))
        section, content = dl_keys_to_subsections(original, False)
        self.assertEqual('Foo bar', section._subsections[0].title)

    # endregion

    def test_full_transform_section(self):
        content = dedent("""
        ; Artist
        : [[Girls' Generation]]
        ; Album
        : MR. TAXI
        ; Released
        : 2011.12.14
        ; Tracklist
        # [[Mr. Taxi (song)|MR. TAXI]]
        # [[The Boys (song)|The Boys]]
        # [[Telepathy (Girls' Generation)|Telepathy]] (텔레파시)
        """).strip()
        expected = {
            'Artist': ListEntry("; Artist\n: [[Girls' Generation]]"),
            'Album': ListEntry('; Album\n: MR. TAXI'),
            'Released': ListEntry('; Released\n: 2011.12.14'),
            'Tracklist': List('\n'.join(content.splitlines()[-3:])),
        }
        root = Root(content)
        self.assert_equal(expected, transform_section(root.sections)[1][0].children)

        expected = [
            'Artist', "Girls' Generation", 'Album', 'MR. TAXI', 'Released', '2011.12.14', 'Tracklist',
            'MR. TAXI', 'The Boys', 'Telepathy', '(텔레파시)'
        ]
        self.assert_equal(expected, list(root.strings()))


if __name__ == '__main__':
    main(exit=False, verbosity=2)

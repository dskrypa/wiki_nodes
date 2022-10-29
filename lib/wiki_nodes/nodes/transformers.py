"""
Utilities for transforming Nodes into forms that are easier to process.
"""

from __future__ import annotations

from copy import copy
from typing import Optional

from .enums import ListType
from .nodes import Section, List, CompoundNode, MappingNode, AnyNode

__all__ = [
    'transform_section',
    'dl_keys_to_subsections',
    'convert_lists_to_maps',
    'convert_hanging_dl_lists',
    'fix_nested_dl_ul_ol',
    'merge_map_chain',
]

TransformedSection = tuple[Section, CompoundNode | AnyNode | None]


# region Section Transformers


def transform_section(section: Section, clone: bool = True) -> TransformedSection:
    """
    Apply all section transforms to the provided :class:`.Section`.

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, None)
    except Skip as e:
        return section, e.content

    content = convert_lists_to_maps(section, False, content)[1]
    content = convert_hanging_dl_lists(section, False, content)[1]
    content = fix_nested_dl_ul_ol(section, False, content)[1]
    content = merge_map_chain(section, False, content)[1]
    content = dl_keys_to_subsections(section, False, content)[1]

    return section, content


def dl_keys_to_subsections(section: Section, clone: bool = True, content: CompoundNode = None) -> TransformedSection:
    """
    Transforms definition list keys into subsection headers, and the content beneath them into the content for those
    subsections.  If the given section's content is not a :class:`.CompoundNode`, then the section and it's content
    are returned unchanged.  If it is CompoundNode, then the section is processed.

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :param content: The section's content, if already pre-processed by another transformer.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, content)
    except Skip as e:
        return section, e.content

    children = []
    did_fix = False
    title: Optional[str] = None
    subsection_nodes = []
    for child in content:
        new_title = None
        # if isinstance(child, List) and len(child) == 1 and child.raw.string.startswith(';'):
        if isinstance(child, List) and len(child) == 1 and child.type == ListType.DL:
            new_title = ' '.join(child.children[0].value.strings())

        if new_title:
            if title:
                did_fix = True
                section._add_pseudo_sub_section(title, subsection_nodes)
                subsection_nodes = []

            title = new_title
        elif title:
            subsection_nodes.append(child)
        else:
            children.append(child)

    if title:
        did_fix = True
        section._add_pseudo_sub_section(title, subsection_nodes)

    if did_fix:
        content.children.clear()
        content.children.extend(children)

    return section, content


def convert_lists_to_maps(section: Section, clone: bool = True, content: CompoundNode = None) -> TransformedSection:
    """
    Convert List objects to MappingNode objects, if possible

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :param content: The section's content, if already pre-processed by another transformer.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, content)
    except Skip as e:
        return section, e.content

    children = []
    did_convert = False
    last = len(content) - 1
    for i, child in enumerate(content):
        if isinstance(child, List) and (len(child) > 1 or (i < last and isinstance(content[i + 1], List))):
            try:
                if as_map := child.as_mapping():
                    did_convert = True
                    child = as_map
            except Exception:  # noqa
                # log.debug(f'Was not a mapping: {short_repr(child)}', exc_info=True)
                pass
            # else:
            #     if as_map:
            #         log.debug(f'Successfully converted to mapping: {short_repr(child)}')
            #     else:
            #         log.debug(f'Was not a mapping: {short_repr(child)}')

        children.append(child)

    if did_convert:
        content.children.clear()
        content.children.extend(children)

    return section, content


def convert_hanging_dl_lists(section: Section, clone: bool = True, content: CompoundNode = None) -> TransformedSection:
    """
    When a level 1 ul/ol follows a level 1 dl, and the last value in the dl is None, then that ul/ol will be converted
    to be that dl's value (it will become a sublist of that dl).

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :param content: The section's content, if already pre-processed by another transformer.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, content)
    except Skip as e:
        return section, e.content

    children = []
    did_fix = False
    last_map, last_key = None, None
    for child in content:
        if isinstance(child, List):
            if last_map:
                did_fix = True
                last_map[last_key] = child
                last_map, last_key = None, None
            else:
                children.append(child)
        elif isinstance(child, MappingNode):
            children.append(child)
            try:
                key, val = list(child.items())[-1]
            except IndexError:
                last_map, last_key = None, None
            else:
                if val is None:
                    last_map, last_key = child, key
                else:
                    last_map, last_key = None, None
        else:
            children.append(child)
            last_map, last_key = None, None

    if did_fix:
        content.children.clear()
        content.children.extend(children)

    return section, content


def fix_nested_dl_ul_ol(section: Section, clone: bool = True, content: CompoundNode = None) -> TransformedSection:
    """
    When a dl contains a value that is a ul, and that ul contains a nested ol, this fixes the lists so that they are
    properly nested.

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :param content: The section's content, if already pre-processed by another transformer.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, content)
    except Skip as e:
        return section, e.content

    children = []
    did_fix = False
    last_list, last_entry = None, None
    for child in content:
        if isinstance(child, MappingNode):
            children.append(child)
            try:
                key, val = list(child.items())[-1]
            except IndexError:
                last_list, last_entry = None, None
            else:
                # if isinstance(val, List) and val.start_char == '*':
                if isinstance(val, List) and val.type == ListType.UL:
                    last_list = val
                    last_entry = val[-1]
                else:
                    last_list, last_entry = None, None
        elif isinstance(child, List):
            # if last_list and child.start_char == '#':
            if last_list and child.type == ListType.OL:
                did_fix = True
                last_entry.extend(child)
            # elif last_list and child.start_char == '*':
            elif last_list and child.type == ListType.UL:
                did_fix = True
                last_list.extend(child)
                last_list = child
                last_entry = child[-1]
            else:
                children.append(child)
                last_list, last_entry = None, None
        else:
            children.append(child)
            last_list, last_entry = None, None

    if did_fix:
        content.children.clear()
        content.children.extend(children)

    return section, content


def merge_map_chain(section: Section, clone: bool = True, content: CompoundNode = None) -> TransformedSection:
    """
    Merge / combine consecutive :class:`.MappingNode` objects into a single MappingNode.

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :param content: The section's content, if already pre-processed by another transformer.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    try:
        section, content = _prep_section(section, clone, content)
    except Skip as e:
        return section, e.content

    children = []
    did_merge = False
    last_map = None
    for child in content:
        if isinstance(child, MappingNode):
            if last_map:
                last_map.update(child)
                did_merge = True
            else:
                children.append(child)

            last_map = child
        else:
            children.append(child)
            last_map = None

    if did_merge:
        content.children.clear()
        content.children.extend(children)

    return section, content


def _prep_section(section: Section, clone: bool, content: CompoundNode | None) -> tuple[Section, CompoundNode]:
    if not isinstance(section.content, CompoundNode):
        raise Skip(section.content if content is None else content)
    if clone:
        section = section.copy()
    if content is None:
        content = copy(section.content)
    return section, content


# endregion


class Skip(Exception):
    """Used internally to signal that a transform should be skipped"""

    def __init__(self, content: AnyNode | None):
        self.content = content

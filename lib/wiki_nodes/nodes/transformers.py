"""
Utilities for transforming Nodes into forms that are easier to process.
"""

from __future__ import annotations

from copy import copy
from typing import Optional

from .nodes import Section, List, String, CompoundNode, ContainerNode, AnyNode

__all__ = ['dl_keys_to_subsections']


# region Section Transformers


def dl_keys_to_subsections(section: Section, clone: bool = True) -> tuple[Section, CompoundNode | AnyNode | None]:
    """
    Transforms dictionary list keys into subsection headers, and the content beneath them into the content for those
    subsections.  If the given section's content is not a :class:`.CompoundNode`, then the section and it's content
    are returned unchanged.  If it is CompoundNode, then the section is processed.

    :param section: The section to process / transform.
    :param clone: If True, then then a copy of the Section is created and any new subsections are created in that copy,
      otherwise, the given Section is modified in-place.
    :return: 2-Tuple of the transformed Section and the remaining base section content after the transformation.
    """
    if not isinstance(section.content, CompoundNode):
        return section, section.content
    if clone:
        section = section.copy()
    content = copy(section.content)

    children = []
    did_fix = False
    title: Optional[str] = None
    subsection_nodes = []
    for child in content:
        new_title = None
        if isinstance(child, List) and len(child) == 1 and child.raw.string.startswith(';'):
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


# endregion

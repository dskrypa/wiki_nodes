"""

"""

import logging
import re
from typing import Union

from wikitextparser import WikiText

from ..utils import strip_style, wiki_attr_values, short_repr

__all__ = ['as_node']
log = logging.getLogger(__name__)

WTP_TYPE_METHOD_NODE_MAP = {
    'Template': 'templates',
    'Comment': 'comments',
    'ExtensionTag': 'get_tags',
    'Tag': 'get_tags',          # Requires .get_tags() to be called before being in ._type_to_spans
    'Table': 'tables',          # Requires .tables to be accessed before being in ._type_to_spans
    'WikiList': 'get_lists',    # Requires .get_lists() to be called before being in ._type_to_spans
    # 'WikiLink': 'wikilinks',
}
WTP_ACCESS_FIRST = {'Tag', 'Table', 'WikiList'}


def as_node(
    wiki_text: Union[str, WikiText], root: 'Root' = None, preserve_comments: bool = False, strict_tags: bool = False
):
    """
    :param wiki_text: The content to process
    :param root: The root node that is an ancestor of this node
    :param preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
    :param strict_tags: If True, require tags to be either self-closing or have a matching closing tag to consider
      it a tag, otherwise classify it as a string.
    :return Node: A :class:`Node` or subclass thereof
    """
    if wiki_text is None:
        return wiki_text
    if isinstance(wiki_text, str):
        wiki_text = WikiText(wiki_text)

    node_start = wiki_text.span[0]
    values = {}
    first = None
    first_attr = None
    for wtp_type, attr in WTP_TYPE_METHOD_NODE_MAP.items():
        # log.debug(f'Types available: {wiki_text._type_to_spans.keys()}; ExtensionTags: {wiki_text._type_to_spans["ExtensionTag"]}')
        if wtp_type in WTP_ACCESS_FIRST:
            values[attr] = wiki_attr_values(wiki_text, attr)

        type_spans = iter(wiki_text._subspans(wtp_type))
        if span := next(type_spans, None):
            if strict_tags and attr == 'get_tags':
                tag = wiki_attr_values(wiki_text, attr, values)[0]
                obj_str = tag.string
                if tag.contents.strip():
                    if not obj_str.endswith(f'</{tag.name}>'):
                        log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                        span = next(type_spans, None)
                else:
                    if obj_str != f'<{tag.name}/>':     # self-closing
                        log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                        span = next(type_spans, None)

        if span:
            # log.debug(f'Found {wtp_type:>8s} @ {span}')
            start = span[0]
            if first is None or first > start:
                # if first is None:
                #     log.debug('  > It was the first object found')
                # else:
                #     log.debug('  > It came before the previously discovered first object')
                first = start
                first_attr = attr
                if first == node_start:
                    # log.debug('    > It is definitely the first object')
                    break

    if first_attr:
        raw_objs = wiki_attr_values(wiki_text, first_attr, values)
        drop = first_attr == 'comments' and not preserve_comments
        # if first > 10:
        #     obj_area = f'{wiki_text(first-10, first)}{colored(wiki_text(first), "red")}{wiki_text(first+1, first+10)}'
        # else:
        #     obj_area = f'{colored(wiki_text(0), "red")}{wiki_text(1, 20)}'
        # log.debug(f'Found {first_attr:>9s} @ pos={first:>7,d} start={node_start:>7,d}  in [{short_repr(wiki_text)}]: [{obj_area}]')
        raw_obj = raw_objs[0]
        node = WTP_ATTR_TO_NODE_MAP[first_attr](raw_obj, root, preserve_comments)
        if raw_obj.string.strip() == wiki_text.string.strip():
            # log.debug(f'  > It was the only thing in this node: {node}')
            return None if drop else node

        before, node_str, after = map(str.strip, wiki_text.string.partition(raw_obj.string))
        return _process_node_parts(wiki_text, node, before, after, drop, root, preserve_comments)
    else:
        # log.debug(f'No complex objs found in [{wiki_text(0, 50)!r}]')
        links = wiki_text.wikilinks
        if not links:
            return String(wiki_text, root)
        elif strip_style(links[0].string) == strip_style(wiki_text.string):
            return Link(wiki_text, root)

        node = CompoundNode(wiki_text, root, preserve_comments)
        node.children.extend(extract_links(node.raw, root))
        return node


def _process_node_parts(wiki_text, node, before, after, drop, root, preserve_comments):
    before_node = as_node(before, root, preserve_comments) if before else None
    after_node = as_node(after, root, preserve_comments) if after else None

    if isinstance(node, Tag) and node.name == 'nowiki':
        # Combine it with any surrounding Strings, or just take its value as a String if there's nothing to combine
        # Only need to check for nowiki tags here since a String will always be returned instead of a nowiki tag
        node = node.value
        if not before and not after:
            return node
        elif isinstance(before_node, String):
            if isinstance(after_node, String):
                return before_node + node + after_node
            else:
                node = before_node + node
                if not after:
                    return node
                before = None
        elif isinstance(after_node, String):
            node = node + after_node
            if not before:
                return node
            after = None

    compound = CompoundNode(wiki_text, root, preserve_comments)

    if before:
        # log.debug(f'  > It had something before it: [{short_repr(before)}]')
        if drop and not after:
            return before_node
        elif type(before_node) is CompoundNode:  # It was not a subclass that stands on its own
            compound.children.extend(before_node.children)
        elif before_node is not None:
            compound.children.append(before_node)

    if not drop:
        compound.children.append(node)

    if after:
        # log.debug(f'  > It had something after it: [{short_repr(after)}]')
        if drop and not before:
            return after_node
        elif type(after_node) is CompoundNode:
            compound.children.extend(after_node.children)
        elif after_node is None:
            if len(compound) == 1:
                return compound[0]
        else:
            compound.children.append(after_node)

    return compound


def extract_links(raw, root: 'Root' = None) -> list[Union['Link', 'String']]:
    try:
        end_match = extract_links._end_match
        start_match = extract_links._start_match
    except AttributeError:
        end_match = extract_links._end_match = re.compile(r'^(.*?)([\'"]+)$', re.DOTALL).match
        start_match = extract_links._start_match = re.compile(r'^([\'"]+)(.*)$', re.DOTALL).match

    content = []
    raw_str = raw.string.strip()
    # log.debug(f'\n\nProcessing {raw_str=!r}', extra={'color': 14})
    links = raw.wikilinks
    while links and raw_str:
        link = links.pop(0)
        # log.debug(f'Links remaining={len(links)}; processing {link=}')
        before, link_text, raw_str = map(str.strip, raw_str.partition(link.string))
        # log.debug(f'\n\nSplit raw into:\nbefore={before!r}\nlink={link_text!r}\nafter={raw_str!r}')
        if before and raw_str and (bm := end_match(before)) and (am := start_match(raw_str)):
            # if bm := end_match(before):
            # log.debug(f' > Found quotes at the end of before: {bm.group(2)}')
            #   if am := start_match(raw_str):
            # log.debug(f' > Found quotes at the beginning of after: {am.group(1)}')
            before = bm.group(1).strip()  # noqa
            link_text = f'{bm.group(2)}{link_text}{am.group(1)}'
            raw_str = am.group(2).strip()
        if before:
            content.append(String(before, root))
        content.append(Link(link_text, root))
        if raw_str:
            # log.debug(f'Replacing links=\n{links}\nwith links=\n{WikiText(raw_str).wikilinks}')
            links = WikiText(raw_str).wikilinks     # Prevent breaking on nested links

    if raw_str:
        content.append(String(raw_str, root))
    return content


# Down here due to circular dependency
from .nodes import BasicNode, CompoundNode, Tag, String, Link, List, Table, Template, Root

WTP_ATTR_TO_NODE_MAP = {
    'get_tags': Tag, 'templates': Template, 'tables': Table, 'get_lists': List, 'comments': BasicNode,
    # 'wikilinks': Link, 'string': String
}

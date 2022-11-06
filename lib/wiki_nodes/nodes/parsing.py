"""
Parse wiki page components from a string or WikiText object and convert them into Nodes.

Note: WikiText populates some values in its ``_type_to_spans`` attribute before calling particular functions, but the
following methods must be called before their respective spans are present: get_tags, get_tables, get_lists
"""

from __future__ import annotations

# import itertools
import logging
from typing import TYPE_CHECKING, Union, Type, Optional, Match

from wikitextparser import WikiText

from ..utils import IntervalCoverageMap, short_repr

if TYPE_CHECKING:
    from .nodes import Root, CompoundNode

__all__ = ['as_node']
log = logging.getLogger(__name__)

WTP_TYPE_METHODS = (
    ('Template', 'templates', WikiText.templates.__get__),
    ('Comment', 'comments', WikiText.comments.__get__),
    ('ExtensionTag', 'get_tags', WikiText.get_tags),
    ('Tag', 'get_tags', WikiText.get_tags),
    ('Table', 'tables', WikiText.tables.__get__),
    ('WikiList', 'get_lists', WikiText.get_lists),
    ('WikiLink', 'wikilinks', WikiText.wikilinks.__get__),
)
WTP_ATTR_TO_NODE_MAP = {}
CompoundNode: Type[CompoundNode] = None  # Replaced in _init_globals


def _init_globals():
    """Called at the bottom of the module. Avoids module-level circular imports."""
    global WTP_ATTR_TO_NODE_MAP, CompoundNode  # noqa

    from .nodes import BasicNode, CompoundNode, Tag, List, Table, Template, String, Link  # noqa

    WTP_ATTR_TO_NODE_MAP = {
        'get_tags': (Tag, True),
        'templates': (Template, True),
        'tables': (Table, True),
        'get_lists': (List, True),
        'comments': (BasicNode, True),
        'wikilinks': (Link, False),
        'string': (String, False),
    }


# as_node_counter = itertools.count()


def as_node(
    text: Union[str, WikiText, None],
    root: Root = None,
    preserve_comments: bool = False,
    strict_tags: bool = False,
):
    # c = next(as_node_counter)
    # log.debug(f'[{c}] as_node({short_repr(text)})', extra={'color': 13})
    if not text:
        return None

    wiki_text = WikiText(text) if isinstance(text, str) else text
    nodes = [node for node in _iter_nodes(wiki_text, root, preserve_comments, strict_tags)]
    if not nodes:
        # log.debug(f'[{c}] No spans/objects found')
        return None
    elif len(nodes) == 1:
        # log.debug(f'[{c}] Returning first node={nodes[0]}')
        return nodes[0]
    else:
        # log.debug(f'[{c}] Returning CompoundNode with {len(nodes)} children={nodes}')
        node = CompoundNode(wiki_text, root, preserve_comments)
        node.children.extend(nodes)
        return node


def _iter_nodes(wiki_text: WikiText, root: Optional[Root], preserve_comments: bool = False, strict_tags: bool = False):
    span_obj_map = get_span_obj_map(wiki_text, preserve_comments, strict_tags)
    # for (a, b), (attr, raw_obj) in sorted(span_obj_map.items()):
    for _span, (attr, raw_obj) in sorted(span_obj_map.items()):
        # log.debug(f'[{c}] Processing {attr} @ ({a}, {b}): {raw_obj}')
        try:
            node_cls, accepts_comments = WTP_ATTR_TO_NODE_MAP[attr]
        except KeyError:  # attr was None (a comment when preserve_comments is False)
            continue
        if accepts_comments:
            yield node_cls(raw_obj, root, preserve_comments)
        else:
            yield node_cls(raw_obj, root)


def get_span_obj_map(wiki_text: WikiText, preserve_comments: bool = False, strict_tags: bool = False):
    non_overlapping_spans = IntervalCoverageMap()
    for wtp_type, attr, method in WTP_TYPE_METHODS:
        attr_values = {obj.span: obj for obj in method(wiki_text)}  # noqa
        for a, b, re_match, matching_byte_array in wiki_text._subspans(wtp_type):  # type: int, int, Match, bytearray
            span = (a, b)
            # log.debug(f'For {wtp_type=}, processing {span=} with {attr_values=}')
            obj = attr_values[span]
            if strict_tags and attr == 'get_tags':
                obj_str: str = obj.string
                if obj.contents.strip():
                    if not obj_str.endswith(f'</{obj.name}>'):
                        log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                        attr = 'string'
                elif not (obj_str.startswith(f'<{obj.name}') and obj_str.endswith('/>')):  # self-closing
                    log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                    attr = 'string'
            elif not preserve_comments and attr == 'comments':
                attr = None

            non_overlapping_spans[span] = (attr, obj)

    # Fill in the gaps between parsed page components that contain text with "string" spans
    wt_str = wiki_text.string
    pos = 0
    for a, b in sorted(non_overlapping_spans):
        if a > pos and (plain_str := wt_str[pos:a].strip()):
            non_overlapping_spans[(pos, a)] = ('string', plain_str)
        pos = b

    # Treat any trailing text as a string
    wt_len = len(wt_str)
    if (pos < wt_len or not non_overlapping_spans) and (plain_str := wt_str[pos:].strip()):
        non_overlapping_spans[(pos, wt_len)] = ('string', plain_str)

    return non_overlapping_spans


_init_globals()
del _init_globals

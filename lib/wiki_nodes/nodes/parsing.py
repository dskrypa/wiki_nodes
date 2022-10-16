"""

"""

from __future__ import annotations

# import itertools
import logging
from typing import TYPE_CHECKING, Union, Type

from wikitextparser import WikiText

from ..utils import IntervalCoverageMap, short_repr

if TYPE_CHECKING:
    from .nodes import Root, CompoundNode

__all__ = ['as_node']
log = logging.getLogger(__name__)

WTP_TYPE_METHOD_NODE_MAP = {
    'Template': ('templates', False),
    'Comment': ('comments', False),
    'ExtensionTag': ('get_tags', True),
    'Tag': ('get_tags', True),              # Requires .get_tags() to be called before being in ._type_to_spans
    'Table': ('tables', False),             # Requires .tables to be accessed before being in ._type_to_spans
    'WikiList': ('get_lists', True),        # Requires .get_lists() to be called before being in ._type_to_spans
    'WikiLink': ('wikilinks', False),
}
WTP_ATTR_TO_NODE_MAP = {}
CompoundNode: Type[CompoundNode] = None  # Replaced in _init_globals


def _init_globals():
    """Called at the bottom of the module. Avoids module-level circular imports."""
    global WTP_ATTR_TO_NODE_MAP, CompoundNode  # noqa

    from .nodes import BasicNode, CompoundNode, Tag, List, Table, Template, String, Link  # noqa

    WTP_ATTR_TO_NODE_MAP = {
        'get_tags': Tag,
        'templates': Template,
        'tables': Table,
        'get_lists': List,
        'comments': BasicNode,
        'wikilinks': Link,
        'string': String,
    }


# as_node_counter = itertools.count()


def as_node(
    text: Union[str, WikiText, None], root: Root = None, preserve_comments: bool = False, strict_tags: bool = False
):
    # c = next(as_node_counter)
    # log.debug(f'[{c}] as_node({short_repr(text)})', extra={'color': 13})
    if not text:
        return None

    wiki_text = WikiText(text) if isinstance(text, str) else text
    span_obj_map = get_span_obj_map(wiki_text, preserve_comments, strict_tags)
    if not span_obj_map:
        # log.debug(f'[{c}] No spans/objects found')
        return None

    no_comment_attrs = ('wikilinks', 'string')
    nodes = []
    # for (a, b), (attr, raw_obj) in sorted(span_obj_map.items()):
    for _, (attr, raw_obj) in sorted(span_obj_map.items()):
        # log.debug(f'[{c}] Processing {attr} @ ({a}, {b}): {raw_obj}')
        if attr is None:
            continue
        elif attr in no_comment_attrs:
            nodes.append(WTP_ATTR_TO_NODE_MAP[attr](raw_obj, root))
        else:
            nodes.append(WTP_ATTR_TO_NODE_MAP[attr](raw_obj, root, preserve_comments))

    if len(nodes) == 1:
        # log.debug(f'[{c}] Returning first node={nodes[0]}')
        return nodes[0]
    else:
        # log.debug(f'[{c}] Returning CompoundNode with {len(nodes)} children={nodes}')
        node = CompoundNode(wiki_text, root, preserve_comments)
        node.children.extend(nodes)
        return node


def get_span_obj_map(wiki_text: WikiText, preserve_comments: bool = False, strict_tags: bool = False):
    non_overlapping_spans = IntervalCoverageMap()
    for wtp_type, (attr, do_call) in WTP_TYPE_METHOD_NODE_MAP.items():
        if do_call:
            attr_values = {obj.span: obj for obj in getattr(wiki_text, attr)()}
        else:
            attr_values = {obj.span: obj for obj in getattr(wiki_text, attr)}

        for a, b, re_match, matching_byte_array in wiki_text._subspans(wtp_type):
            span = (a, b)
            # log.debug(f'For {wtp_type=}, processing {span=} with {attr_values=}')
            obj = attr_values[span]
            if strict_tags and attr == 'get_tags':
                obj_str = obj.string
                if obj.contents.strip():
                    if not obj_str.endswith(f'</{obj.name}>'):
                        log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                        attr = 'string'
                else:
                    if obj_str != f'<{obj.name}/>':     # self-closing
                        log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                        attr = 'string'
            elif not preserve_comments and attr == 'comments':
                attr = None

            non_overlapping_spans[span] = (attr, obj)

    wt_str = wiki_text.string
    pos = 0
    for a, b in sorted(non_overlapping_spans):
        if a > pos and (plain_str := wt_str[pos:a].strip()):
            non_overlapping_spans[(pos, a)] = ('string', plain_str)
        pos = b

    wt_len = len(wt_str)
    if (pos < wt_len or not non_overlapping_spans) and (plain_str := wt_str[pos:].strip()):
        non_overlapping_spans[(pos, wt_len)] = ('string', plain_str)

    return non_overlapping_spans


_init_globals()
del _init_globals

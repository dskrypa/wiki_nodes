"""
Template processing handlers.
"""

from __future__ import annotations

import logging
import re
from abc import ABC
from typing import TYPE_CHECKING, Optional

from ...utils import strip_style
from ..nodes import Template, String, Link, MappingNode
from ..parsing import as_node
from .base import NodeHandler

if TYPE_CHECKING:
    from wikitextparser import Argument

__all__ = ['TemplateHandler']
log = logging.getLogger(__name__)


class TemplateHandler(NodeHandler[Template], root=True):
    __slots__ = ()
    basic: bool = None

    def __init_subclass__(cls, basic: bool = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if basic is not None:
            cls.basic = basic

    @classmethod
    def get_name(cls, node: Template) -> str:
        return node.lc_name

    @property
    def is_basic(self) -> bool:
        if self.basic is not None:
            return self.basic
        tmpl = self.node
        return tmpl.value is None or isinstance(tmpl.value, (String, Link))

    # region Get Value Methods

    def get_value(self):
        tmpl = self.node
        if not (args := tmpl.raw.arguments):
            return None
        elif all(arg.positional for arg in args):
            return self.get_all_pos_value(args)

        return self.get_mapping_value(args)

    def get_default_value(self):
        return None

    def get_all_pos_value(self, args: list[Argument]):
        tmpl = self.node
        if len(args) == 1:
            raw_value = args[0].value or self.get_default_value()
            return as_node(raw_value, tmpl.root, tmpl.preserve_comments)
        return [as_node(a.value, tmpl.root, tmpl.preserve_comments) for a in args]

    def get_mapping_value(self, args: list[Argument]) -> MappingNode:
        tmpl = self.node
        mapping = MappingNode(tmpl.raw, tmpl.root, tmpl.preserve_comments)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = as_node(arg.value.strip(), tmpl.root, tmpl.preserve_comments, strict_tags=True)

        return mapping

    # endregion

    def zip_value(self, value) -> Optional[MappingNode]:
        if not isinstance(value, MappingNode):
            return None

        tmpl = self.node
        mapping = MappingNode(tmpl.raw, tmpl.root, tmpl.preserve_comments)
        keys, values = [], []
        num_search = re.compile(r'[a-z](\d+)$', re.IGNORECASE).search

        for key, value in tmpl.value.items():
            if num_search(key):
                if len(keys) == len(values):
                    if isinstance(value, String):
                        keys.append(value.value)
                    else:
                        log.debug(f'Unexpected zip key={value!r}')
                else:
                    values.append(value)
            else:
                keys.append(key)
                values.append(value)

        mapping.update(zip(keys, values))
        return mapping

    def make_disambiguation_link(self) -> Optional[Link]:
        if title := getattr(self.node.root, 'title', None):
            return Link(f'[[{title}_(disambiguation)]]', self.node.root)
        return None


# region Common Handlers


class NullHandler(TemplateHandler, for_name='n/a', basic=True):
    __slots__ = ()

    def get_default_value(self):
        return 'N/A'


class NoWikiHandler(TemplateHandler, for_name='nowiki'):
    __slots__ = ()

    def get_value(self):
        if not (args := self.node.raw.arguments):
            return None

        values = [String(a.value) for a in args]
        if len(values) == 1:
            return values[0]
        return values


class AbbrHandler(TemplateHandler, for_name='abbr'):
    __slots__ = ()

    def get_value(self):
        if not (args := self.node.raw.arguments):
            return None
        return [a.value for a in args]  # [short, long]


# region Disambiguation Template Handlers


class AboutHandler(TemplateHandler, for_name='about'):
    __slots__ = ()

    def get_value(self) -> list[Link]:
        args = [arg.value for arg in self.node.raw.arguments if arg.positional]
        links = [Link(f'[[{title}]]', self.node.root) for arg in args[2::2] if (title := arg.strip())]
        n = len(args)
        if (not args or n == 1 or (n > 3 and n % 2 == 0)) and (link := self.make_disambiguation_link()):
            links.append(link)
        return links


class ForHandler(TemplateHandler, for_name='for'):
    __slots__ = ()

    def get_value(self) -> list[Link]:
        args = [arg.value for arg in self.node.raw.arguments if arg.positional]
        if len(args) < 2 and (link := self.make_disambiguation_link()):
            return [link]
        return [Link(f'[[{title}]]', self.node.root) for arg in args[1:] if (title := arg.strip())]


class OtherUsesHandler(TemplateHandler, for_name='other uses'):
    __slots__ = ()

    def get_value(self) -> Optional[Link]:
        if title := next((arg.value for arg in self.node.raw.arguments if arg.positional), None):
            return Link(f'[[{title}_(disambiguation)]]', self.node.root)
        return self.make_disambiguation_link()


class OtherUsesOfHandler(TemplateHandler, for_name='other uses of'):
    __slots__ = ()

    def get_value(self) -> Optional[Link]:
        if args := [arg.value for arg in self.node.raw.arguments if arg.positional][1:]:
            return Link(f'[[{args[-1]}_(disambiguation)]]', self.node.root)
        return self.make_disambiguation_link()


class RedirectDistinguishForHandler(TemplateHandler, for_name='redirect-distinguish-for'):
    __slots__ = ()

    def get_value(self) -> list[Link]:
        args = [arg.value for arg in self.node.raw.arguments if arg.positional]
        links = [Link(f'[[{arg}]]', self.node.root) for arg in args[1::2]]
        n = len(args)
        if (n == 2 or n % 2 == 1) and (link := self.make_disambiguation_link()):
            links.append(link)
        return links


class AboutDistinguishHandler(TemplateHandler, for_name='about-distinguish'):
    __slots__ = ()

    def get_value(self) -> list[Link]:
        args = [arg.value for arg in self.node.raw.arguments if arg.positional]
        links = []
        for arg in args[1:]:
            try:
                title, text = arg.split('{{!}}')
            except ValueError:
                links.append(Link(f'[[{arg}]]', self.node.root))
            else:
                links.append(Link.from_title(title, self.node.root, text))
        return links


# endregion


class MainHandler(TemplateHandler, for_names=('main', 'see also')):
    __slots__ = ()

    def get_all_pos_value(self, args: list[Argument]):
        tmpl = self.node
        if len(args) == 1:
            raw_value = args[0].value or self.get_default_value()
            value = as_node(raw_value, tmpl.root, tmpl.preserve_comments)
            if isinstance(value, String):
                value = Link.from_title(value.value, tmpl.root)
            return value
        return [as_node(a.value, tmpl.root, tmpl.preserve_comments) for a in args]


class InfoboxHandler(TemplateHandler, prefix='infobox', basic=False):
    __slots__ = ()

    def get_mapping_value(self, args: list[Argument]) -> MappingNode:
        tmpl = self.node
        mapping = MappingNode(tmpl.raw, tmpl.root, tmpl.preserve_comments)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = node = as_node(arg.value.strip(), tmpl.root, tmpl.preserve_comments, strict_tags=True)
            # log.debug(f'[{tmpl.lc_name}] Processing {key=} {node=}')
            if key == 'image' and isinstance(node, String) and node:
                mapping[key] = Link.from_title(
                    node.value if node.value.lower().startswith('file:') else f'File:{node.value}', tmpl.root
                )

        return mapping


class LangPrefixHandler(TemplateHandler, prefix='lang-'):
    __slots__ = ()

    def get_value(self):
        tmpl = self.node
        if not (args := tmpl.raw.arguments):
            return None
        elif all(arg.positional for arg in args):
            return self.get_all_pos_value(args)
        elif len(args) == 1:
            return as_node(args[0].value.strip())

        return self.get_mapping_value(args)


class KoHhrmHandler(LangPrefixHandler, for_name='ko-hhrm'):
    __slots__ = ()


# endregion


# region fandom.com Handlers


class WpHandler(TemplateHandler, for_name='wp', site='fandom.com'):
    __slots__ = ()

    def get_value(self):
        tmpl = self.node
        if not (args := tmpl.raw.arguments):
            return None
        elif len(args) in (2, 3):  # {{WP|lang|title|text (optional)}}
            vals = tuple(a.value for a in args)
            lang, title = vals[:2]
            return Link.from_title(f'wikipedia:{lang}:{title}', tmpl.root, vals[2] if len(vals) == 3 else None)
        return super().get_value()


# endregion


# region Wikipedia Handlers


class WikipediaHandler(TemplateHandler, ABC, site='en.wikipedia.org'):
    __slots__ = ()


# class WikipediaStartDateHandler(WikipediaHandler, for_name='start date'):
#     __slots__ = ()
#
#
# class WikipediaHorizontalListHandler(WikipediaHandler, for_name='hlist'):
#     __slots__ = ()


class WikipediaTrackListHandler(WikipediaHandler, for_name='tracklist', basic=False):
    __slots__ = ()

    def get_value(self):
        if not (value := super().get_value()):
            return value

        meta, rows = parse_rows_with_meta(value)
        # node = self.node
        # return MappingNode(node.raw, node.root, node.preserve_comments, content={'meta': meta, 'tracks': rows})
        return {'meta': meta, 'tracks': rows}


class WikipediaTrackListingHandler(WikipediaTrackListHandler, for_name='track listing', basic=False):
    __slots__ = ()


# endregion


def parse_rows_with_meta(value: MappingNode):
    meta, rows = {}, {}
    row_key_match = re.compile(r'^([a-z]+)(\d+)$', re.IGNORECASE).match

    for key, val in value.items():
        if m := row_key_match(key):
            name, num = m.groups()
            try:
                rows[num][name] = val
            except KeyError:
                rows[num] = {name: val}
        else:
            meta[key] = val

    keys = {k for row in rows.values() for k in row}
    rows = {int(k): row for k, row in rows.items() if any(v is not None for v in row.values())}
    rows = [{k: row.get(k) for k in keys} for _, row in sorted(rows.items())]
    return meta, rows

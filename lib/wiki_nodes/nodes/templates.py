"""

"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type, Union, Optional

from ..utils import strip_style
from .nodes import Template, String, Link, MappingNode
from .parsing import as_node

if TYPE_CHECKING:
    from .nodes import Template

__all__ = []
log = logging.getLogger(__name__)


class TemplateHandler:
    __slots__ = ('template',)
    _site_name_handler_map = {}
    _site_prefix_handler_map = {}
    site: Optional[str] = None
    name: Optional[str] = None
    prefix: Optional[str] = None
    basic: bool = None

    def __init_subclass__(
        cls, tmpl_name: str = None, prefix: str = None, site: str = None, basic: bool = None, **kwargs
    ):  # noqa
        super().__init_subclass__(**kwargs)
        if site is not None:
            cls.site = site
        if basic is not None:
            cls.basic = basic
        if tmpl_name:
            cls.name = tmpl_name
            cls.prefix = None
            try:
                cls._site_name_handler_map[site][tmpl_name] = cls
            except KeyError:
                cls._site_name_handler_map[site] = {tmpl_name: cls}
        elif prefix:
            cls.prefix = prefix
            cls.name = None
            try:
                cls._site_prefix_handler_map[site][prefix] = cls
            except KeyError:
                cls._site_prefix_handler_map[site] = {prefix: cls}
        elif ABC not in cls.__bases__:
            raise TypeError(f'Missing required keyword argument for class={cls.__name__} init: tmpl_name or prefix')

    def __init__(self, template: Template):
        self.template = template

    @classmethod
    def for_template(cls, template: Template) -> TemplateHandler:
        try:
            site = template.root.site
        except AttributeError:
            site = None
        sites = (site, None) if site else (None,)
        for site in sites:
            if handler := cls._for_template(site, template):
                # log.warning(f'Found handler={handler.__name__} for {site=} name={template.lc_name!r}')
                return handler(template)

        # log.warning(f'Could not find a handler for {sites=} name={template.lc_name!r}')
        return cls(template)

    @classmethod
    def _for_template(cls, site: Optional[str], template: Template) -> Optional[Type[TemplateHandler]]:
        name = template.lc_name
        try:
            return cls._site_name_handler_map[site][name]
        except KeyError:
            pass
        try:
            prefix_handler_map = cls._site_prefix_handler_map[site]
        except KeyError:
            pass
        else:
            for prefix, handler in prefix_handler_map.items():
                if name.startswith(prefix):
                    return handler
        return None

    @property
    def is_basic(self) -> bool:
        if self.basic is not None:
            return self.basic
        tmpl = self.template
        return tmpl.value is None or isinstance(tmpl.value, (String, Link))

    # region Get Value Methods

    def get_value(self):
        tmpl = self.template
        if not (args := tmpl.raw.arguments):
            return None
        elif all(arg.positional for arg in args):
            return self.get_all_pos_value(args)

        return self.get_mapping_value(args)

    def get_default_value(self):
        return None

    def get_all_pos_value(self, args):
        tmpl = self.template
        if len(args) == 1:
            raw_value = args[0].value or self.get_default_value()
            return as_node(raw_value, tmpl.root, tmpl.preserve_comments)
        return [as_node(a.value, tmpl.root, tmpl.preserve_comments) for a in args]

    def get_mapping_value(self, args) -> MappingNode:
        tmpl = self.template
        mapping = MappingNode(tmpl.raw, tmpl.root, tmpl.preserve_comments)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = as_node(arg.value.strip(), tmpl.root, tmpl.preserve_comments, strict_tags=True)

        return mapping

    # endregion

    def zip_value(self, value) -> Optional[MappingNode]:
        if not isinstance(value, MappingNode):
            return None

        tmpl = self.template
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


class NullHandler(TemplateHandler, tmpl_name='n/a', basic=True):
    __slots__ = ()

    def get_default_value(self):
        return 'N/A'


class AbbrHandler(TemplateHandler, tmpl_name='abbr'):
    def get_value(self):
        tmpl = self.template
        if not (args := tmpl.raw.arguments):
            return None
        return [a.value for a in args]  # [short, long]


class WpHandler(TemplateHandler, tmpl_name='wp'):
    def get_value(self):
        tmpl = self.template
        if not (args := tmpl.raw.arguments):
            return None
        elif len(args) in (2, 3):  # {{WP|lang|title|text (optional)}}
            vals = tuple(a.value for a in args)
            lang, title = vals[:2]
            return Link.from_title(f'wikipedia:{lang}:{title}', tmpl.root, vals[2] if len(vals) == 3 else None)
        return super().get_value()


class MainHandler(TemplateHandler, tmpl_name='main'):
    __slots__ = ()

    def get_all_pos_value(self, args):
        tmpl = self.template
        if len(args) == 1:
            raw_value = args[0].value or self.get_default_value()
            value = as_node(raw_value, tmpl.root, tmpl.preserve_comments)
            if isinstance(value, String):
                value = Link.from_title(value.value, tmpl.root)
            return value
        return [as_node(a.value, tmpl.root, tmpl.preserve_comments) for a in args]


class SeeAlsoHandler(MainHandler, tmpl_name='see also'):
    __slots__ = ()


class InfoboxHandler(TemplateHandler, prefix='infobox', basic=False):
    __slots__ = ()

    def get_mapping_value(self, args) -> MappingNode:
        tmpl = self.template
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
        tmpl = self.template
        if not (args := tmpl.raw.arguments):
            return None
        elif all(arg.positional for arg in args):
            return self.get_all_pos_value(args)
        elif len(args) == 1:
            return as_node(args[0].value.strip())

        return self.get_mapping_value(args)


class KoHhrmHandler(LangPrefixHandler, tmpl_name='ko-hhrm'):
    __slots__ = ()


# region Wikipedia Handlers


class WikipediaHandler(ABC, TemplateHandler, site='en.wikipedia.org'):
    __slots__ = ()


# class WikipediaStartDateHandler(WikipediaHandler, tmpl_name='start date'):
#     __slots__ = ()
#
#
# class WikipediaHorizontalListHandler(WikipediaHandler, tmpl_name='hlist'):
#     __slots__ = ()


class WikipediaTrackListHandler(WikipediaHandler, tmpl_name='tracklist', basic=False):
    __slots__ = ()

    def get_value(self):
        if not (value := super().get_value()):
            return value

        meta, rows = parse_rows_with_meta(value)
        return {'meta': meta, 'tracks': rows}


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

"""
Takes the next step with WikiText parsed by :mod:`wikitextparser` to process it into nodes based on what each section
contains, and provide a more top-down approach to traversing content on a given page.

This is still a work in process - some data types are not fully handled yet, and some aspects are subject to change.

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import MutableMapping
from copy import copy
from typing import TYPE_CHECKING, Iterable, Optional, Union, TypeVar, Type, Iterator, Callable, Mapping, Match, Generic

from wikitextparser import (
    WikiText, Section as _Section, Template as _Template, Table as _Table, Tag as _Tag, WikiLink as _Link,
    WikiList as _List
)

from ..exceptions import NoLinkSite, NoLinkTarget
from ..utils import strip_style, ClearableCachedPropertyMixin, cached_property, rich_repr

if TYPE_CHECKING:
    from ..http import MediaWikiClient
    from .handlers import TagHandler, TemplateHandler

__all__ = [
    'Node', 'BasicNode', 'CompoundNode', 'ContainerNode', 'MappingNode', 'Tag', 'String', 'Link', 'ListEntry', 'List',
    'Table', 'Template', 'Root', 'Section', 'TableSeparator', 'N', 'AnyNode'
]
log = logging.getLogger(__name__)

T = TypeVar('T')
N = TypeVar('N', bound='Node')
C = TypeVar('C', bound='Node')
KT = TypeVar('KT')
OptStr = Optional[str]
Raw = Union[str, WikiText]
AnyNode = Union[
    'Node', 'BasicNode', 'CompoundNode', 'MappingNode', 'Tag', 'String', 'Link', 'ListEntry', 'List', 'Table',
    'Template', 'Root', 'Section'
]

_NotSet = object()


class Node(ClearableCachedPropertyMixin):
    __slots__ = ('raw', 'preserve_comments', 'root', '__compressed')

    _raw_attr: OptStr = None
    _raw_meth: OptStr = None

    def __init_subclass__(cls, attr: OptStr = None, method: OptStr = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if attr:
            cls._raw_attr = attr
        if method:
            cls._raw_meth = method

    def __init__(self, raw: Raw, root: Root = None, preserve_comments: bool = False, _index: int = 0):
        self.raw = self.normalize_raw(raw, _index)
        self.preserve_comments = preserve_comments
        self.root = root

    @classmethod
    def normalize_raw(cls, raw: Raw, index: int = 0) -> WikiText:
        if isinstance(raw, str):
            raw = WikiText(raw)
        if (attr := cls._raw_attr) and type(raw) is WikiText:
            raw_seq = getattr(raw, attr)
        elif (method := cls._raw_meth) and type(raw) is WikiText:
            raw_seq = getattr(raw, method)()
        else:
            return raw
        try:
            return raw_seq[index]
        except IndexError as e:
            raise ValueError(f'Invalid wiki {cls.__name__} value') from e

    def stripped(self, *args, **kwargs) -> str:
        return strip_style(self.raw.string, *args, **kwargs)

    # region Internal Methods

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}()>'

    def __bool__(self) -> bool:
        return bool(self.raw.string)

    @property
    def _compressed(self) -> str:
        try:
            return self.__compressed
        except AttributeError:
            pass
        compressed = ''.join(part for line in self.raw.string.splitlines() for part in line.split() if part)
        self.__compressed = compressed
        return compressed

    def __eq__(self, other) -> bool:
        if other.__class__ != self.__class__:
            return False
        return self._compressed == other._compressed

    # endregion

    @property
    def is_basic(self) -> Optional[bool]:
        return None

    # region Printing / Formatting Methods

    def raw_pprint(self, pretty: bool = False):
        _print(self.raw.pformat() if pretty else self.raw.string)

    def _pprint(self, indentation: int = 0):
        _print(self.pformat(indentation))

    def pformat(self, indentation: int = 0):
        return (' ' * indentation) + repr(self)

    def pprint(self, mode: str = 'reprs', indent: int = 0, recurse: bool = False):
        if mode in {'raw', 'raw-pretty'}:
            self.raw_pprint(mode == 'raw-pretty')
        elif mode == 'headers':  # Only implemented by Section
            return
        elif mode in {'reprs', 'content', 'processed'}:
            self._pprint(indent)

        if recurse:
            try:
                children = self.children  # noqa
            except AttributeError:
                return
            indent += 4
            try:
                children = children.values()
            except AttributeError:
                pass
            for child in children:
                child.pprint(mode, indent, recurse)

    # endregion

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        yield from ()

    def find_one(self, node_cls: Type[N], *args, **kwargs) -> Optional[N]:
        """
        :param node_cls: The class of :class:`Node` to find
        :param args: Positional args to pass to :meth:`.find_all`
        :param kwargs: Keyword args to pass to :meth:`.find_all`
        :return: The first :class:`Node` object that matches the given criteria, or None if no matching nodes could be
          found.
        """
        return next(self.find_all(node_cls, *args, **kwargs), None)


class BasicNode(Node):
    __slots__ = ()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.raw!r})>'

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.raw.string)

    @property
    def is_basic(self) -> bool:
        return True


class ContainerNode(Node, Generic[C], ABC):
    __slots__ = ()

    @property
    @abstractmethod
    def children(self):
        raise NotImplementedError

    @property
    def is_basic(self) -> bool:
        return False

    # region Dunder Methods

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}{self.children!r}>'

    def __getitem__(self, item) -> C:
        return self.children[item]

    def __setitem__(self, key, value: C):
        self.children[key] = value

    def __delitem__(self, key):
        del self.children[key]

    def __iter__(self) -> Iterator[C]:
        yield from self.children

    def __len__(self) -> int:
        return len(self.children)

    def __bool__(self) -> bool:
        return bool(self.children)

    def __eq__(self, other) -> bool:
        if other.__class__ != self.__class__:
            return False
        return self._compressed == other._compressed and self.children == other.children

    # endregion

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        """
        Find all descendant nodes of the given type, optionally with additional matching criteria.

        :param node_cls: The class of :class:`Node` to find
        :param recurse: Whether descendant nodes should be searched recursively or just the direct children of this node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        for value in self:
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)


class CompoundNode(ContainerNode[C]):
    @cached_property
    def children(self) -> list[C]:
        return []

    @property
    def only_basic(self) -> bool:
        """True if all children are basic; not cached because children may change"""
        return self.__class__ is CompoundNode and all(c.is_basic for c in self.children)

    def pformat(self, indentation: int = 0) -> str:
        indent = ' ' * indentation
        inside = indent + (' ' * 4)
        child_lines = ('\n'.join(inside + line for line in c.pformat().splitlines()) for c in self.children)
        children = ',\n'.join(child_lines)
        return f'{indent}<{self.__class__.__name__}[\n{children}\n{indent}]>'

    def __rich_repr__(self):
        yield from self.children

    @classmethod
    def from_nodes(
        cls, nodes: Iterable[N], root: Root = None, preserve_comments: bool = False, delim: str = '\n'
    ) -> CompoundNode[N]:
        node = cls(delim.join(n.raw.string for n in nodes), root, preserve_comments)
        node.children.extend(nodes)
        return node


class MappingNode(ContainerNode[C], MutableMapping[KT, C]):
    __slots__ = ('children',)
    children: dict[Union[str, C], Optional[C]]

    def __init__(self, raw: Raw, root: Root = None, preserve_comments: bool = False, content=None):
        super().__init__(raw, root, preserve_comments)
        self.children = {}
        if content:
            self.children.update(content)

    def keys(self):
        return self.children.keys()

    def get(self, key: KT, default: T = None, case_sensitive: bool = True) -> Union[C, T]:
        try:
            return self.children[key]
        except KeyError:
            if case_sensitive or not isinstance(key, str):
                return default

        ci_key = key.casefold()
        for name, val in self.children.items():
            try:
                if name.casefold() == ci_key:
                    return val
            except AttributeError:
                pass

        return default

    @property
    def only_basic(self) -> bool:
        return False

    def pformat(self, indentation: int = 0):
        indent = ' ' * indentation
        inside = indent + (' ' * 4)
        child_lines = (
            '\n'.join(inside + line for line in f'{k!r}: {v.pformat() if v is not None else None}'.splitlines())
            for k, v in self.children.items()
        )
        children = ',\n'.join(child_lines)
        return f'{indent}<{self.__class__.__name__}{{\n{children}\n{indent}}}>'

    def __rich_repr__(self):
        yield from self.children.items()

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        """
        Find all descendant nodes of the given type, optionally with additional matching criteria.

        :param type node_cls: The class of :class:`Node` to find
        :param bool recurse: Whether descendant nodes should be searched recursively or just the direct children of this
          node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        for value in self.values():
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)


class Tag(BasicNode, method='get_tags'):
    raw: _Tag
    name: str
    attrs: dict[str, str]

    def __init__(self, raw: Union[Raw, _Tag], root: Root = None, preserve_comments: bool = False):
        super().__init__(raw, root, preserve_comments)
        self.name = self.raw.name
        self.attrs = self.raw.attrs

    def __repr__(self) -> str:
        attrs = f':{self.attrs}' if self.attrs else ''
        return f'<{self.__class__.__name__}[{self.name}{attrs}][{self.value}]>'

    @cached_property
    def handler(self) -> TagHandler:
        from .handlers import TagHandler

        return TagHandler.for_node(self)

    @cached_property
    def value(self):
        return self.handler.get_value()

    @property
    def is_basic(self) -> Optional[bool]:
        if (value := self.value) is not None:
            return not isinstance(value, Node) or value.is_basic
        return True

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if value := self.value:
            yield from _find_all(value, node_cls, recurse, **kwargs)

    def __getitem__(self, item):
        return self.attrs[item]

    def get(self, item, default=None):
        return self.attrs.get(item, default)

    def __rich_repr__(self):
        yield self.name
        yield 'attrs', self.attrs


class String(BasicNode):
    __slots__ = ('value',)
    raw: WikiText
    value: str

    def __init__(self, raw: Raw, root: Root = None):
        super().__init__(raw, root)
        self.value = strip_style(self.raw.string)

    @property
    def lower(self) -> str:
        return self.value.lower()

    # region Dunder Methods

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.raw.string.strip()!r})>'

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: Union[Node, str]) -> bool:
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.value)

    def __add__(self, other: Union[Node, str]) -> String:
        try:
            other_str = other.raw.string
        except AttributeError:
            other_str = other
        return String(self.raw.string + other_str, self.root)

    def __bool__(self) -> bool:
        return bool(self.value)

    # endregion


class Link(BasicNode):
    raw: _Link
    title: str
    text: str

    def __init__(self, raw: Union[Raw, _Link], root: Root = None):
        super().__init__(raw, root)                    # note: target = title + fragment; fragment not desired right now
        self.title = ' '.join(self.raw.title.split())  # collapse extra spaces
        self.text = self.raw.text

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Link], index: int = 0) -> _Link:
        raw = super().normalize_raw(raw, index)
        if isinstance(raw, _Link):
            return raw  # noqa
        try:
            return raw.wikilinks[0]
        except IndexError as e:
            raw_str = str(raw).strip()
            raw_str = f'"""\n{raw_str}\n"""' if '\n' in raw_str else repr(raw_str)
            message = f'Link init attempted with non-link content - raw content={raw!r} - raw text={raw_str}'
            raise ValueError(message) from e

    # region Link low level methods

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self._str) ^ hash(self.source_site)

    def __eq__(self, other: Link) -> bool:
        if not isinstance(other, Link):
            return False
        return self._str == other._str and self.source_site == other.source_site

    def __lt__(self, other: Link) -> bool:
        return self.__cmp_tuple < other.__cmp_tuple

    def __str__(self) -> str:
        return self.show or self.raw.string

    def __repr__(self) -> str:
        if self.root and (site := self.root.site):
            parts = site.split('.')
            if parts[0] in {'www', 'wiki', 'en'}:                       # omit common prefixes
                parts = parts[1:]
            if len(parts) > 1 and parts[-1] in {'org', 'com', 'net'}:   # omit common suffixes
                parts = parts[:-1]
            site = '.'.join(parts)
            return f'<{self.__class__.__name__}:{self._str!r}@{site}>'
        return f'<{self.__class__.__name__}:{self._str!r}>'

    @cached_property
    def _str(self) -> str:
        return self._format(self.title, self.text)

    @property
    def __cmp_tuple(self):
        return self.interwiki, self.special, self._str, self.source_site

    @classmethod
    def _format(cls, title: str, text: str = None) -> str:
        return f'[[{title}|{text}]]' if text else f'[[{title}]]'

    # endregion

    @classmethod
    def from_title(cls, title: str, root: Root = None, text: str = None) -> Link:
        return cls(cls._format(title, text), root)

    @cached_property
    def show(self) -> Optional[str]:
        """The text that would be shown for this link (without fragment)"""
        text = self.text or self.title
        return text.strip() if text else None

    @cached_property
    def source_site(self) -> Optional[str]:
        return self.root.site if self.root else None

    @cached_property
    def special(self) -> bool:
        prefix = self.title.split(':', 1)[0].lower()
        return prefix in {'category', 'image', 'file', 'template'}

    # region Link target resolution methods

    @cached_property
    def to_file(self) -> bool:
        return self.title.lower().startswith(('image:', 'file:'))

    @cached_property
    def interwiki(self) -> bool:
        try:
            return bool(self.iw_key_title)
        except ValueError:
            return False

    @cached_property
    def iw_key_title(self) -> tuple[str, str]:
        if (root := self.root) and ':' in (title := self.title):
            if m := iw_community_link_match(title):
                return tuple(m.groups())  # noqa
            elif iw_map := root._interwiki_map:
                prefix, iw_title = title.split(':', maxsplit=1)
                if prefix in iw_map:
                    return prefix, iw_title
                lc_prefix = prefix.lower()
                if lc_prefix in iw_map:
                    return lc_prefix, iw_title
        raise ValueError(f'{self} is not an interwiki link')

    @cached_property
    def url(self) -> Optional[str]:
        """The fully resolved URL for this link"""
        try:
            mw_client, title = self.client_and_title
        except (NoLinkSite, NoLinkTarget):
            return None
        else:
            return mw_client.url_for_article(title)

    @cached_property
    def client_and_title(self) -> tuple[MediaWikiClient, str]:
        """The :class:`MediaWikiClient<.http.MediaWikiClient>` and title to request from that client for this link"""
        from ..http import MediaWikiClient

        if not (site := self.source_site):
            raise NoLinkSite(self)

        mw_client = MediaWikiClient(site)
        try:
            iw_key, title = self.iw_key_title
        except ValueError:
            title = self.title
        else:
            mw_client = mw_client.interwiki_client(iw_key)

        if not title:
            raise NoLinkTarget(self)

        return mw_client, title

    # endregion


class ListEntry(CompoundNode[C]):
    def __init__(self, raw: Raw, root: Root = None, preserve_comments: bool = False, _value=None):
        super().__init__(raw, root, preserve_comments)
        if _value:
            self.value = _value
            self._children = None
        elif type(self.raw) is WikiText:
            try:
                as_list = self.raw.get_lists()[0]
            except IndexError:
                self.value = as_node(self.raw, self.root, preserve_comments)
                self._children = None
            else:
                self.value = as_node(as_list.items[0], self.root, preserve_comments)
                try:
                    self._children = as_list.sublists()[0].string
                except IndexError:
                    self._children = None
        else:
            self.value = self.raw
            self._children = None

    def __repr__(self) -> str:
        if self._children:
            return f'<{self.__class__.__name__}({self.value!r}, {self.children!r})>'
        return f'<{self.__class__.__name__}({self.value!r})>'

    def __bool__(self) -> bool:
        return bool(self.value) or bool(self.children)

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if value := self.value:
            yield from _find_all(value, node_cls, recurse, **kwargs)
        for value in self:
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)

    @cached_property
    def sub_list(self) -> Optional[List[ListEntry[C]]]:
        if not self._children:
            return None
        content = '\n'.join(c[1:] for c in map(str.strip, self._children.splitlines()))
        return List(content, self.root, self.preserve_comments)

    @property
    def children(self) -> list[ListEntry[C]]:
        sub_list = self.sub_list
        if not sub_list:
            return []
        return sub_list.children

    def extend(self, list_node: List[ListEntry[C]]):
        if self._children is None:
            self.__dict__['sub_list'] = list_node
        else:
            self.sub_list.extend(list_node)

    def _extend(self, text: str, convert: bool = True):
        self.clear_cached_properties()
        # TODO: Clean this up... this creates a mess
        text = f'** {text}'
        # text = f': {text}'
        if self._children is None:
            if convert and self.value is not None:
                self._children = f'** {self.value.raw.string}\n{text}'  # noqa
                # self._children = f': {self.value.raw.string}\n{text}'
                self.value = None
                self.raw = WikiText(self._children)
            else:
                self.raw = WikiText(f'{self.raw.string}\n{text}')
                self._children = text
        else:
            self.raw = WikiText(f'{self.raw.string}\n{text}')
            self._children = f'{self._children}\n{text}'

    def pformat(self, indentation: int = 0) -> str:
        indent = (' ' * indentation)
        inside = indent + (' ' * 4)
        if self.value is not None:
            base = '\n'.join(inside + line for line in self.value.pformat().splitlines())
        else:
            base = f'{inside}None'
        children = None
        if self.children:
            nested = indent + (' ' * 8)
            children = ',\n'.join('\n'.join(nested + line for line in c.pformat().splitlines()) for c in self.children)

        if not children and base.count('\n') == 0:
            return f'{indent}<{self.__class__.__name__}({base.strip()})>'
        else:
            if children:
                content = f'{base},\n{inside}[\n{children}\n{inside}]'
            else:
                content = base
            return f'{indent}<{self.__class__.__name__}(\n{content}\n{indent})>'

    def __rich_repr__(self):
        yield self.value
        yield 'children', self.children


class List(CompoundNode[ListEntry[C]], method='get_lists'):
    raw: _List

    def __init__(self, raw: Union[Raw, _List], root: Root = None, preserve_comments: bool = False):
        super().__init__(raw, root, preserve_comments)
        self._as_mapping = None
        self.start_char = self.raw.string[0]

    @cached_property
    def children(self) -> list[ListEntry[C]]:
        return [ListEntry(val, self.root, self.preserve_comments) for val in map(str.strip, self.raw.fullitems)]

    def extend(self, list_node: List[ListEntry[C]]):
        self.children.extend(list_node.children)

    def iter_flat(self) -> Iterator[C]:
        for child in self.children:
            if val := child.value:
                yield val
            if child.sub_list:
                yield from child.sub_list.iter_flat()

    def as_mapping(self, *args, **kwargs) -> MappingNode[C]:
        if self._as_mapping is None:
            self._as_mapping = MappingNode(self.raw, self.root, self.preserve_comments, self.as_dict(*args, **kwargs))
        return self._as_mapping

    def as_dict(self, sep: str = ':', multiline=None) -> dict[Union[str, C], Optional[C]]:
        data = {}

        def node_fn(node_str: str):
            return as_node(node_str.strip(), self.root, self.preserve_comments)

        def _add_kv(key, val):
            # log.debug(f'Storing key={key!r} val={val!r}')
            if isinstance(key, String):
                data[key.value] = val
            elif isinstance(key, Link):
                data[key.show] = val
            else:
                data[key.raw.string] = val
                log.log(9, f'Unexpected type for List.as_dict {key=!r} with {val=!r} on {self.root}')

        if multiline is None:
            self._as_multiline_dict(node_fn, _add_kv)
            if not data:
                self._as_inline_dict(node_fn, _add_kv, sep)
        elif multiline:
            self._as_multiline_dict(node_fn, _add_kv)
        else:
            self._as_inline_dict(node_fn, _add_kv, sep)

        return data

    def _as_multiline_dict(self, node_fn: Callable, _add_kv: Callable):
        ctrl_pat_match = re.compile(r'^([*#:;]+)\s*(.*)$', re.DOTALL).match
        last_key = None
        last_val = None
        for line in map(str.strip, self.raw.fullitems):
            ctrl_chars, content = ctrl_pat_match(line).groups()
            # log.debug(f'Processing ctrl={ctrl_chars!r} content={content!r} last_key={last_key!r} last_val={last_val!r}')
            c = ctrl_chars[-1]
            if c == ';':  # key
                if last_key:
                    _add_kv(node_fn(last_key[1]), None)
                    last_val = None
                last_key = (line, content)
            elif c == ':':  # value
                if last_key:
                    raw = f'{last_key[0]}\n{line}'
                    last_val = ListEntry(raw, self.root, self.preserve_comments, _value=node_fn(content))
                    _add_kv(node_fn(last_key[1]), last_val)
                    last_key = None
                elif last_val:
                    last_val._extend(line[1:])
                else:
                    raise ValueError(f'Unexpected value={content!r} in a definition list')
            elif last_val:
                last_val._extend(line[1:])

        if last_key:
            _add_kv(node_fn(last_key[1]), None)

    def _as_inline_dict(self, node_fn: Callable, _add_kv: Callable, sep: str):
        ctrl_pat_match = re.compile(r'^([*#:;]+)\s*(.*)$', re.DOTALL).match
        style_pat_match = re.compile(r'^(\'{2,5}[^' + sep + r']+)' + sep + r'\s*(\'{2,5})(.*)', re.DOTALL).match
        reformatter = '{{}}{{}}{} {{}}'.format(sep)

        for line in map(str.strip, self.raw.fullitems):
            ctrl_chars, content = map(str.strip, ctrl_pat_match(line).groups())
            if m := style_pat_match(content):
                content = reformatter.format(*m.groups())

            raw_key, raw_val = content.split(sep, maxsplit=1)
            if '\n' in raw_val:
                raw_val = '\n'.join(val_line[1:] for val_line in filter(None, raw_val.splitlines()))

            key, val = map(node_fn, (raw_key, raw_val))
            _add_kv(key, val)


class TableSeparator:
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.value!r})>'

    def pformat(self, indentation: int = 0) -> str:
        indent = ' ' * indentation
        return f'{indent}<{self.__class__.__name__}[{self.value!r}]>'


class Table(CompoundNode[Union[TableSeparator, MappingNode[KT, C]]], attr='tables'):
    _rowspan_with_template = re.compile(r'(\|\s*rowspan="?\d+"?)\s*{')
    _header_ws_pat = re.compile(r'\s*<br\s*/?>\s*')
    raw: _Table
    caption: Optional[str]

    def __init__(self, raw: Union[Raw, _Table], root: Root = None, preserve_comments: bool = False):
        super().__init__(raw, root, preserve_comments)
        self.caption = self.raw.caption.strip() if self.raw.caption else None

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Table], index: int = 0) -> _Table:
        raw = cls._rowspan_with_template.sub(r'\1 | {', raw.string if isinstance(raw, WikiText) else raw)
        return super().normalize_raw(raw, index)  # noqa

    @cached_property
    def _header_row_spans(self):
        return [int(cell.attrs.get('rowspan', 1)) if cell is not None else 1 for cell in next(iter(self.raw.cells()))]

    @cached_property
    def _raw_headers(self):
        last_header_row = max(self._header_row_spans)
        sub_ws = self._header_ws_pat.sub
        return [
            [
                as_node(sub_ws(' ', cell.value).strip(), self.root, self.preserve_comments) if cell else cell
                for cell in row
            ]
            for row in self.raw.cells()[:last_header_row]
        ]

    @cached_property
    def _str_headers(self):
        str_headers = []
        for row_data in self._raw_headers:
            cell_strs = []
            for cell in row_data:
                while isinstance(cell, CompoundNode):
                    cell = cell[0]
                if isinstance(cell, String):
                    cell_strs.append(cell.value)
                elif isinstance(cell, Link):
                    cell_strs.append(cell.text)
                elif isinstance(cell, Template) and cell.lc_name == 'abbr':
                    cell_strs.append(cell.value[-1])
                elif cell is not None:
                    log.debug(f'Unexpected cell type; using data instead: {cell}')
            str_headers.append(cell_strs)
        return str_headers

    @cached_property
    def headers(self) -> list[str]:
        headers = []
        for row_span, *header_vals in zip(self._header_row_spans, *self._str_headers):
            header_vals = header_vals[:-(row_span - 1)] if row_span > 1 else header_vals
            headers.append(':'.join(map(strip_style, filter(None, header_vals))))
        return headers

    @cached_property
    def rows(self) -> list[Union[TableSeparator, MappingNode[C]]]:
        def node_fn(cell):
            if not cell:
                return cell
            return as_node(cell.value.strip(), self.root, self.preserve_comments)

        headers = self.headers
        num_header_rows = len(self._raw_headers)
        processed = []
        if raw_rows := self.raw.cells()[num_header_rows:]:
            for row in raw_rows:
                try:
                    col_span = int(row[0].attrs.get('colspan', 1))
                except AttributeError:
                    pass
                else:
                    if col_span >= len(headers):  # Some tables have an incorrect value...
                        processed.append(TableSeparator(node_fn(row[0])))
                        continue

                mapping = zip(headers, map(node_fn, row))
                processed.append(MappingNode(row, self.root, self.preserve_comments, mapping))
        elif templates := self.raw.templates:
            for template in templates:
                cells = [node_fn(arg) for arg in template.arguments if arg.positional]
                processed.append(MappingNode(template, self.root, self.preserve_comments, zip(headers, cells)))

        return processed

    @cached_property
    def children(self) -> list[Union[TableSeparator, MappingNode[C]]]:
        return self.rows

    def __rich_repr__(self):
        yield 'caption', self.caption, None
        yield 'headers', self.headers
        yield 'children', self.children


class Template(BasicNode, attr='templates'):
    raw: _Template
    name: str
    lc_name: str

    def __init__(self, raw: Union[Raw, _Template], root: Root = None, preserve_comments: bool = False):
        super().__init__(raw, root, preserve_comments)
        self.name = self.raw.name.strip()
        self.lc_name = self.name.lower()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.name!r}: {self.value!r})>'

    def pformat(self, indentation: int = 0) -> str:
        indent = ' ' * indentation
        if value := self.value:
            if isinstance(value, Node):
                value = value.pformat(indentation + 4)
                if '\n' in value:
                    value = f'\n{value}\n{indent}'
            elif isinstance(value, list):
                inside = ' ' * (indentation + 4)
                inner = indentation + 8
                value = ',\n'.join(f'{inside}{v.pformat(inner)}' for v in value)
                if '\n' in value:
                    value = f'\n{value}\n{indent}'
            else:
                value = rich_repr(value)
                if '\n' in value:
                    lines = value.splitlines()
                    lines[-1] = indent + lines[-1]
                    value = '\n'.join(lines)

            if '\n' in value:
                return f'{indent}<{self.__class__.__name__}[{self.name!r}][{value}]>'

        return f'{indent}<{self.__class__.__name__}[{self.name!r}][{value!r}]>'

    def __rich_repr__(self):
        yield self.name
        yield self.value

    @cached_property
    def handler(self) -> TemplateHandler:
        from .handlers import TemplateHandler

        return TemplateHandler.for_node(self)

    @cached_property
    def is_basic(self) -> bool:
        return self.handler.is_basic

    @cached_property
    def value(self):
        return self.handler.get_value()

    @cached_property
    def zipped(self) -> Optional[MappingNode]:
        return self.handler.zip_value(self.value)

    def __getitem__(self, item):
        if self.value is None:
            raise TypeError('Cannot index a template with no value')
        return self.value[item]

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if value := self.value:
            if isinstance(value, Node):
                yield from _find_all(value, node_cls, recurse, **kwargs)
            else:
                for node in value:
                    yield from _find_all(node, node_cls, recurse, recurse, **kwargs)


class Root(Node):
    site: OptStr
    _interwiki_map: Optional[Mapping[str, str]]

    # Children = sections
    def __init__(
        self,
        page_text: Raw,
        site: str = None,
        preserve_comments: bool = False,
        interwiki_map: Mapping[str, str] = None,
    ):
        if isinstance(page_text, str):
            page_text = WikiText(page_text.replace('\xa0', ' ').replace('\u200b', ''))
        super().__init__(page_text, None, preserve_comments)
        self.site = site
        self._interwiki_map = interwiki_map

    def __getitem__(self, title_or_index: Union[str, int]) -> Section:
        return self.sections[title_or_index]

    def __contains__(self, title_or_index: Union[str, int]) -> bool:
        return title_or_index in self.sections

    def __iter__(self) -> Iterator[Section]:
        root = self.sections
        yield root
        yield from root

    def get(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = False
    ) -> Union[Section, T]:
        return self.sections.get(title_or_index, default, case_sensitive=case_sensitive)

    def find_all(self, node_cls: Type[N], recurse: bool = True, **kwargs) -> Iterator[N]:
        """
        Find all descendant nodes of the given type.

        :param node_cls: The class of :class:`Node` to find
        :param recurse: Whether descendant nodes should be searched recursively or just the direct children of this node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        return self.sections.find_all(node_cls, recurse, **kwargs)

    @cached_property
    def sections(self) -> Section:
        sections: Iterator[_Section] = iter(self.raw.sections)
        root = Section(next(sections), self, self.preserve_comments)
        last_by_level = {0: root}
        last_level = 0
        for sec in sections:
            level = sec.level
            if last_level >= level:
                last_by_level = {k: v for k, v in last_by_level.items() if k < level or k == 0}
            last_level = level

            parent = last_by_level[max(last_by_level)]
            section = Section(sec, self, self.preserve_comments)
            parent._add_sub_section(section.title, section)
            last_by_level[level] = section
        return root


class Section(ContainerNode['Section'], method='get_sections'):
    raw: _Section
    title: str
    level: int
    children: dict[str, Section] = None  # = None is necessary to satisfy the abstract property
    _subsections: list[Section]

    def __init__(
        self, raw: Union[Raw, _Section], root: Optional[Root], preserve_comments: bool = False, _index: int = None
    ):
        super().__init__(raw, root, preserve_comments, _index)
        self.title = strip_style(self.raw.title) if self.raw.title else ''
        self.level = self.raw.level
        self.children = {}  # populated by Root.sections
        self._subsections = []

    # region Internal Methods

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Section], index: int = None) -> _Section:
        if isinstance(raw, str) and index is None:
            index = 1
        else:
            index = 0
        return super().normalize_raw(raw, index)  # noqa

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.level}: {self.title}]>'

    def __getitem__(self, title_or_index: Union[str, int]) -> Section:
        try:
            return self.children[title_or_index]
        except KeyError:
            pass
        try:
            return self._subsections[title_or_index]
        except (TypeError, IndexError):
            pass
        raise KeyError(title_or_index)

    def __contains__(self, title_or_index: Union[str, int]) -> bool:
        if title_or_index in self.children:
            return True
        if isinstance(title_or_index, int):
            return 0 <= title_or_index < len(self._subsections)
        return False

    def __iter__(self) -> Iterator[Section]:
        yield from self.children.values()

    def _formatted_title(self, raw: bool = False) -> str:
        bars = '=' * self.level
        title = self.raw.title if raw else self.title
        return f'{bars}{title}{bars}'

    def _add_sub_section(self, title: str, section: Section):
        self.children[title] = section
        self._subsections.append(section)

    def _add_pseudo_sub_section(self, title: str, nodes: Iterable[Node], delim: str = ' '):
        bars = '=' * (self.level + 1)
        raw = f'{bars}{title}{bars}\n{delim.join(n.raw.string for n in nodes)}'
        self._add_sub_section(title, self.__class__(raw, self.root, self.preserve_comments, 1))

    # endregion

    @property
    def depth(self) -> int:
        if self.children:
            return max(section.depth for section in self.children.values()) + 1
        return 0

    def get(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = False
    ) -> Union[Section, T]:
        return self._find(title_or_index, default, case_sensitive=case_sensitive)

    def find(self, title_or_index: Union[str, int], default: T = _NotSet) -> Union[Section, T]:
        """Find the subsection with the given title"""
        return self._find(title_or_index, default, case_sensitive=True)

    def _find(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = False
    ) -> Union[Section, T]:
        try:
            return self.children[title_or_index]
        except KeyError:
            pass

        if not case_sensitive and not isinstance(title_or_index, int):
            title = title_or_index.casefold()
            for name, child in self.children.items():
                if title == name.casefold():
                    return child

        for child in self.children.values():
            try:
                return child._find(title_or_index, case_sensitive=case_sensitive)
            except KeyError:
                pass

        if default is _NotSet:
            raise KeyError(f'Cannot find section={title_or_index!r} in {self} or any subsections')
        return default

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if content := self.content:
            yield from _find_all(content, node_cls, recurse, **kwargs)
        if recurse:
            for child in self:
                yield from _find_all(child, node_cls, recurse, **kwargs)

    # region Content Processing Methods

    @cached_property
    def content(self) -> Optional[AnyNode]:
        if self.level == 0:
            raw = self.raw.string.strip()  # without .string here, .tags() returns the full page's tags
            node = as_node(raw, self.root, self.preserve_comments)
            if node.__class__ is CompoundNode:
                node = self._process_compound_root_content(node)
            # else:
            #     log.debug(f'Using original section 0 content for {self.root}')
            return node

        content = self.raw.contents.strip()
        if self.children:
            content = content.partition(next(iter(self))._formatted_title(True))[0].strip()
        return as_node(content, self.root, self.preserve_comments)    # chop off the header

    def _process_compound_root_content(self, node: CompoundNode[N]) -> CompoundNode[N]:
        # Split infobox / templates from first paragraph
        non_basic = []
        remainder = []
        children = iter(node)
        found_infobox = False
        for child in children:
            if isinstance(child, String):
                # log.debug(f'Splitting section with {len(non_basic)} non-basic nodes before {short_repr(child)}')
                remainder.append(child)
                break
            elif isinstance(child, Link) and not child.title.lower().startswith('file:'):
                # log.debug(f'Splitting section with {len(non_basic)} non-basic nodes before {short_repr(child)}')
                remainder.append(child)
                break
            else:
                if isinstance(child, Template) and 'infobox' in child.lc_name:
                    found_infobox = True
                non_basic.append(child)

        remainder.extend(children)
        if found_infobox and non_basic and remainder:
            # log.debug(f'Rebuilding section 0 content for {self.root}')
            node = CompoundNode.from_nodes(non_basic, self.root, self.preserve_comments)
            node.children.append(CompoundNode.from_nodes(remainder, self.root, self.preserve_comments, ' '))
        # else:
        #     log.debug(f'Using original section 0 content for {self.root}')
        return node

    def processed(
        self,
        convert_maps: bool = True,
        fix_dl_last_none: bool = True,
        fix_nested_dl_ul_ol: bool = True,
        merge_maps: bool = True,
        fix_dl_key_as_header: bool = True,
    ) -> Optional[AnyNode]:
        """
        The content of this section, processed to work around various issues.

        :param convert_maps: Convert List objects to MappingNode objects, if possible
        :param fix_dl_last_none: If a ul/ol follows a definition list on the top level of this section's content,
          and the last value in the definition list is None, update that value to be the list that follows
        :param fix_nested_dl_ul_ol: When a dl contains a value that is a ul, and that ul contains a nested ol, fix
          the lists so that they are properly nested
        :param merge_maps: Merge consecutive MappingNode objects
        :param fix_dl_key_as_header: Some pages have sub-sections with ``;`` used to indicate a section header
          instead of surrounding the header with ``=``
        :return: CompoundNode
        """
        content = copy(self.content)
        if not isinstance(content, CompoundNode):
            return content

        if convert_maps:
            content = self._process_convert_maps(content)
        if fix_dl_last_none:
            content = self._process_fix_dl_last_none(content)
        if fix_nested_dl_ul_ol:
            content = self._process_fix_nested_dl_ul_ol(content)
        if merge_maps:
            content = self._process_merge_maps(content)
        if fix_dl_key_as_header:
            content = self._process_fix_dl_key_as_header(content)

        return content

    def _process_convert_maps(self, content: CompoundNode[N]) -> CompoundNode[N]:  # noqa
        children = []
        did_convert = False
        last = len(content) - 1
        for i, child in enumerate(content):
            if isinstance(child, List) and (len(child) > 1 or (i < last and isinstance(content[i + 1], List))):
                try:
                    as_map = child.as_mapping()
                except Exception:  # noqa
                    # log.debug(f'Was not a mapping: {short_repr(child)}', exc_info=True)
                    pass
                else:
                    if as_map:
                        did_convert = True
                        child = as_map
                    #     log.debug(f'Successfully converted to mapping: {short_repr(child)}')
                    # else:
                    #     log.debug(f'Was not a mapping: {short_repr(child)}')

            children.append(child)

        if did_convert:
            content.children.clear()
            content.children.extend(children)

        return content

    def _process_fix_dl_last_none(self, content: CompoundNode[N]) -> CompoundNode[N]:  # noqa
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

        return content

    def _process_fix_nested_dl_ul_ol(self, content: CompoundNode[N]) -> CompoundNode[N]:  # noqa
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
                    if isinstance(val, List) and val.start_char == '*':
                        last_list = val
                        last_entry = val[-1]
                    else:
                        last_list, last_entry = None, None
            elif isinstance(child, List):
                if last_list and child.start_char == '#':
                    did_fix = True
                    last_entry.extend(child)
                elif last_list and child.start_char == '*':
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

        return content

    def _process_merge_maps(self, content: CompoundNode[N]) -> CompoundNode[N]:  # noqa
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

        return content

    def _process_fix_dl_key_as_header(self, content: CompoundNode[N]) -> CompoundNode[N]:
        children = []
        did_fix = False
        title = None  # type: Optional[str]
        subsection_nodes = []
        for child in content:
            new_title = None
            if isinstance(child, List) and len(child) == 1 and child.raw.string.startswith(';'):
                title_node = child.children[0].value
                if isinstance(title_node, String):
                    new_title = title_node.value
                elif title_node.__class__ is CompoundNode and title_node.only_basic:  # noqa
                    new_title = ' '.join(str(n.show if isinstance(n, Link) else n.value) for n in title_node)  # noqa

            if new_title:
                if title:
                    did_fix = True
                    self._add_pseudo_sub_section(title, subsection_nodes)
                    subsection_nodes = []

                title = new_title
            elif title:
                subsection_nodes.append(child)
            else:
                children.append(child)

        if title:
            did_fix = True
            self._add_pseudo_sub_section(title, subsection_nodes)

        if did_fix:
            content.children.clear()
            content.children.extend(children)

        return content

    # endregion

    # region Printing / Formatting Methods

    def pformat(self, mode: str = 'reprs', indent: int = 0, recurse: bool = True) -> str:
        return '\n'.join(self._pformat(mode, indent, recurse))

    def pprint(self, mode: str = 'reprs', indent: int = 0, recurse: bool = True):
        for line in self._pformat(mode, indent, recurse):
            try:
                print(line)
            except OSError as e:
                if e.errno == 22:
                    break
                else:
                    raise

    def _pformat(self, mode: str = 'reprs', indent: int = 0, recurse: bool = True) -> Iterator[str]:
        if mode == 'raw-pretty':
            yield self.raw.pformat()
        elif mode == 'raw':
            yield self.raw.string
        else:
            indent_str = ' ' * indent
            indent += 4
            if mode == 'headers':
                yield f'{indent_str}{self._formatted_title()}'
            elif mode in {'reprs', 'content', 'processed'}:
                yield f'{indent_str}{self}'
                if mode != 'reprs':
                    content = self.content if mode == 'content' else self.processed()
                    if content is None:
                        yield 'None'
                    else:
                        yield content.pformat(indent)

        if recurse:
            for child in self.children.values():
                yield from child._pformat(mode, indent=indent, recurse=recurse)

    # endregion


def _print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except OSError as e:
        if e.errno != 22:  # occurs when writing to a closed pipe
            raise


def _find_all(node, node_cls: Type[N], recurse: bool = True, _recurse_first: bool = True, **kwargs) -> Iterator[N]:
    if isinstance(node, node_cls):
        if not kwargs or all(getattr(node, k, _NotSet) == v for k, v in kwargs.items()):
            yield node
        if recurse:
            yield from node.find_all(node_cls, recurse=recurse, **kwargs)
    elif _recurse_first:
        try:
            find_all = node.find_all
        except AttributeError:
            pass
        else:
            yield from find_all(node_cls, recurse=recurse, **kwargs)


def iw_community_link_match(title: str) -> Optional[Match]:
    try:
        match = iw_community_link_match._match
    except AttributeError:
        match = iw_community_link_match._match = re.compile(r'^(w:c:[^:]+):(.+)$').match
    return match(title)


# Down here due to circular dependency
from .parsing import as_node  # noqa

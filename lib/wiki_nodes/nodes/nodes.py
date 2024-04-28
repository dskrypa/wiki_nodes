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
from typing import TYPE_CHECKING, Iterable, Optional, Union, TypeVar, Type, Iterator, Callable, Mapping, Generic

try:
    from typing import Self
except ImportError:
    Self = TypeVar('Self')  # noqa

from wikitextparser import (
    WikiText, Section as _Section, Template as _Template, Table as _Table, Tag as _Tag, WikiLink as _Link,
    WikiList as _List
)

from ..exceptions import NoLinkSite, NoLinkTarget
from ..utils import strip_style, ClearableCachedPropertyMixin, cached_property, rich_repr
from .enums import ListType

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
# TODO: Add way for .strings() to skip particular nodes, ideally in a way that allows multiple criteria to be specified
#  for a single call.  I.e., `Tag with name='ref'` + `Section with title='References'`


class Node(ClearableCachedPropertyMixin):
    __slots__ = ('raw', 'preserve_comments', 'root', '__compressed')

    TYPES: dict[str, Type[AnyNode]] = {}
    _raw_attr: OptStr = None
    _raw_meth: OptStr = None

    def __init_subclass__(cls, attr: OptStr = None, method: OptStr = None, **kwargs):
        cls.TYPES[cls.__name__] = cls
        super().__init_subclass__(**kwargs)
        if attr:
            cls._raw_attr = attr
        if method:
            cls._raw_meth = method

    def __init__(self, raw: Raw, root: Root = None, preserve_comments: bool = False, _index: int = None):
        self.raw = self.normalize_raw(raw, _index)
        self.preserve_comments = preserve_comments
        self.root = root

    @classmethod
    def normalize_raw(cls, raw: Raw, index: int = None) -> WikiText:
        if isinstance(raw, str):
            raw = WikiText(raw)
        if (attr := cls._raw_attr) and type(raw) is WikiText:
            raw_seq = getattr(raw, attr)
        elif (method := cls._raw_meth) and type(raw) is WikiText:
            raw_seq = getattr(raw, method)()
        else:
            return raw
        if index is None:
            index = 0
        try:
            return raw_seq[index]
        except IndexError as e:
            raise ValueError(f'Invalid wiki {cls.__name__} value') from e

    def stripped(self, *args, **kwargs) -> str:
        return strip_style(self.raw.string, *args, **kwargs)

    def strings(self, strip: bool = True) -> Iterator[str]:
        value = self.raw.string
        yield value.strip() if strip else value

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

    def copy(self) -> Self:
        cls = self.__class__
        clone = cls.__new__(cls)
        clone.raw = self.raw
        clone.preserve_comments = self.preserve_comments
        clone.root = self.root
        try:
            clone.__compressed = self.__compressed
        except AttributeError:
            pass
        return clone

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
        elif mode in {'reprs', 'content'}:
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

    def strings(self, strip: bool = True) -> Iterator[str]:
        for value in self:
            yield from _strings(value, strip)


class CompoundNode(ContainerNode[C]):
    @cached_property
    def children(self) -> list[C]:
        return []

    @property
    def only_basic(self) -> bool:
        """True if all children are basic; not cached because children may change"""
        return self.__class__ is CompoundNode and all(c.is_basic for c in self.children)

    def copy(self) -> Self:
        clone = super().copy()
        try:
            clone.__dict__['children'] = [c.copy() for c in self.__dict__['children']]
        except KeyError:
            pass
        return clone

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

    def copy(self) -> MappingNode[KT, C]:
        clone = super().copy()
        clone.children = {_maybe_copy(k): _maybe_copy(v) for k, v in self.children.items()}
        return clone

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

    def strings(self, strip: bool = True) -> Iterator[str]:
        for key, value in self.children.items():
            yield from _strings(key, strip)
            yield from _strings(value, strip)


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
        return f'<{self.__class__.__name__}[{self.name}{attrs}][{self.value!r}]>'

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

    def copy(self) -> Tag:
        clone = super().copy()
        clone.name = self.name
        clone.attrs = self.attrs
        try:
            clone.__dict__['value'] = _maybe_copy(self.__dict__['value'])
        except KeyError:
            pass
        return clone

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if value := self.value:
            yield from _find_all(value, node_cls, recurse, **kwargs)

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.value, strip)

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

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield self.value.strip() if strip else self.value

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

    def copy(self) -> String:
        clone = super().copy()
        clone.value = self.value
        return clone


class Link(BasicNode):
    _iw_community_match = re.compile(r'^(w:c:[^:]+):(.+)$').match
    raw: _Link
    title: str
    text: str

    def __init__(self, raw: Union[Raw, _Link], root: Root = None):
        super().__init__(raw, root)                    # note: target = title + fragment; fragment not desired right now
        self.title = ' '.join(self.raw.title.split())  # collapse extra spaces
        self.text = self.raw.text

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Link], index: int = None) -> _Link:
        raw = super().normalize_raw(raw, index)
        if isinstance(raw, _Link):
            return raw  # noqa
        if index is None:
            index = 0
        try:
            return raw.wikilinks[index]
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

    def strings(self, strip: bool = True) -> Iterator[str]:
        if show := self.show:
            yield show.strip() if strip else show

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
            if m := self._iw_community_match(title):
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

    def copy(self) -> Link:
        clone = super().copy()
        clone.title = self.title
        clone.text = self.text
        keys = ('show', 'source_site', 'special', 'to_file', 'interwiki', 'iw_key_title', 'url', 'client_and_title')
        clone_dict, self_dict = clone.__dict__, self.__dict__
        for key in keys:
            try:
                clone_dict[key] = self_dict[key]
            except KeyError:
                pass
        return clone


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

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.value, strip)
        for value in self:
            yield from _strings(value, strip)

    @cached_property
    def sub_list(self) -> Optional[List[ListEntry[C]]]:
        if not self._children:
            return None
        content = '\n'.join(c[1:] for c in map(str.strip, self._children.splitlines()))
        return List(content, self.root, self.preserve_comments)

    @cached_property
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

    def copy(self) -> ListEntry[C]:
        clone = super().copy()
        clone.value = self.value
        clone._children = self._children
        try:
            clone.__dict__['sub_list'] = self.__dict__['sub_list'].copy()
        except (KeyError, AttributeError):
            pass
        return clone

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
        self.type = ListType(self.start_char)

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

    def copy(self) -> List[ListEntry[C]]:
        clone = super().copy()  # CompoundNode.copy handles copying children
        clone._as_mapping = self._as_mapping
        clone.start_char = self.start_char
        clone.type = self.type
        return clone


class TableSeparator:
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.value!r})>'

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value) ^ hash(self.__class__)

    def copy(self) -> TableSeparator:
        return self.__class__(self.value)

    def pformat(self, indentation: int = 0) -> str:
        indent = ' ' * indentation
        return f'{indent}<{self.__class__.__name__}[{self.value!r}]>'

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.value, strip)


class Table(CompoundNode[Union[TableSeparator, MappingNode[KT, C]]], attr='tables'):
    _rowspan_with_template = re.compile(r'(\|\s*rowspan="?\d+"?)\s*{')
    _header_ws_pat = re.compile(r'\s*<br\s*/?>\s*')
    raw: _Table
    caption: Optional[str]

    def __init__(self, raw: Union[Raw, _Table], root: Root = None, preserve_comments: bool = False):
        super().__init__(raw, root, preserve_comments)
        self.caption = self.raw.caption.strip() if self.raw.caption else None

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Table], index: int = None) -> _Table:
        raw = cls._rowspan_with_template.sub(r'\1 | {', raw.string if isinstance(raw, WikiText) else raw)
        return super().normalize_raw(raw, index)  # noqa

    @cached_property
    def _header_row_spans(self):
        first_row = next(iter(self.raw.cells()))
        if not any(cell is not None and cell.is_header for cell in first_row):
            return []
        span_strs = (cell.attrs.get('rowspan', 1) if cell is not None else 1 for cell in first_row)
        return [1 if row_span == '' else int(row_span) for row_span in span_strs]

    @cached_property
    def _raw_headers(self):
        if not (header_row_spans := self._header_row_spans):
            return []

        rows = self.raw.cells()[:max(header_row_spans)]
        sub_ws = self._header_ws_pat.sub
        root, comments = self.root, self.preserve_comments
        return [
            [as_node(sub_ws(' ', cell.value).strip(), root, comments) if cell else cell for cell in row]
            for row in rows
        ]

    @cached_property
    def _str_headers(self):
        str_headers = []
        for row_data in self._raw_headers:
            cell_strs = []
            for cell in row_data:
                if isinstance(cell, Template) and cell.lc_name == 'abbr':
                    cell_strs.append(cell.value[-1])
                elif cell is not None:
                    cell_strs.append(' '.join(_strings(cell)))
                # while isinstance(cell, CompoundNode):
                #     cell = cell[0]
                # if isinstance(cell, String):
                #     cell_strs.append(cell.value)
                # elif isinstance(cell, Link):
                #     cell_strs.append(cell.show)
                # elif isinstance(cell, Template) and cell.lc_name == 'abbr':
                #     cell_strs.append(cell.value[-1])
                # elif cell is not None:
                #     log.debug(f'Unexpected cell type; using data instead: {cell}')
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
    def children(self) -> list[Union[TableSeparator, MappingNode[C]]]:
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
                        # TODO: This really needs an example test case + unit test...
                        processed.append(TableSeparator(node_fn(row[0])))
                        continue

                mapping = zip(headers, map(node_fn, row))
                raw = '\n'.join('' if cell is None else cell.string for cell in row)
                processed.append(MappingNode(raw, self.root, self.preserve_comments, mapping))
        elif templates := self.raw.templates:
            for template in templates:
                cells = [node_fn(arg) for arg in template.arguments if arg.positional]
                processed.append(MappingNode(template, self.root, self.preserve_comments, zip(headers, cells)))

        return processed

    @cached_property
    def rows(self) -> list[Union[TableSeparator, MappingNode[C]]]:
        return self.children

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.caption, strip)
        for header in self.headers:
            yield from _strings(header, strip)
        for row in self.rows:
            for cell in row.values():
                yield from _strings(cell, strip)

    def copy(self) -> Table:
        clone = super().copy()  # CompoundNode.copy handles copying children
        clone.caption = self.caption
        clone_dict, self_dict = clone.__dict__, self.__dict__
        for key in ('_header_row_spans', '_raw_headers', '_str_headers', 'headers', 'rows'):
            try:
                clone_dict[key] = self_dict[key]
            except KeyError:
                pass
        return clone

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

    def __getitem__(self, item):
        if self.value is None:
            raise TypeError('Cannot index a template with no value')
        return self.value[item]

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

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.value, strip)

    @cached_property
    def zipped(self) -> Optional[MappingNode]:
        return self.handler.zip_value(self.value)

    def find_all(self, node_cls: Type[N], recurse: bool = False, **kwargs) -> Iterator[N]:
        if value := self.value:
            if isinstance(value, Node):
                yield from _find_all(value, node_cls, recurse, **kwargs)
            elif isinstance(value, Mapping):
                for key, val in value.items():
                    if isinstance(key, Node):
                        yield from _find_all(val, node_cls, recurse, recurse, **kwargs)
                    if isinstance(val, Node):
                        yield from _find_all(val, node_cls, recurse, recurse, **kwargs)
            elif isinstance(value, Iterable) and not isinstance(value, str):
                for node in value:
                    yield from _find_all(node, node_cls, recurse, recurse, **kwargs)

    def copy(self) -> Template:
        clone = super().copy()
        clone.name = self.name
        clone.lc_name = self.lc_name
        clone_dict, self_dict = clone.__dict__, self.__dict__
        for key in ('handler', 'is_basic', 'zipped'):
            try:
                clone_dict[key] = self_dict[key]
            except KeyError:
                pass
        try:
            clone_dict['value'] = _maybe_copy(self_dict['value'])
        except KeyError:
            pass
        return clone

    def pformat(self, indentation: int = 0, max_width: int = None) -> str:
        indent = ' ' * indentation
        vo, vc = '[]'
        if value := self.value:
            if isinstance(value, Node):
                value_str = value.pformat(indentation + 4)
                if '\n' not in value_str:  # TODO: There should be a better way to do this while avoiding a 2nd call...
                    value_str = value.pformat()
                value = value_str
            else:
                value = rich_repr(value, max_width)
                if '\n' in value:
                    lines = value.splitlines()
                    vo += lines[0]
                    vc = lines[-1] + vc
                    value = '\n'.join(indent + line for line in lines[1:-1])

            if '\n' in value:
                vo += '\n'
                vc = f'\n{indent}{vc}'

        return f'{indent}<{self.__class__.__name__}[{self.name!r}]{vo}{value}{vc}>'

    def __rich_repr__(self):
        yield self.name
        yield self.value


class Root(Node):
    site: OptStr
    _interwiki_map: Optional[Mapping[str, str]]

    def __init__(
        self,
        page_text: Raw,
        site: str = None,
        preserve_comments: bool = False,
        interwiki_map: Mapping[str, str] = None,
    ):
        if isinstance(page_text, str):
            page_text = WikiText(page_text.replace('\xa0', ' ').replace('\u200b', ''))  # nbsp, 0-width space
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

    def find_section(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = True
    ) -> Union[Section, T]:
        return self.sections.find_section(title_or_index, default, case_sensitive=case_sensitive)

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

    def strings(self, strip: bool = True) -> Iterator[str]:
        yield from _strings(self.sections, strip)

    @cached_property
    def sections(self) -> Section:
        sections: Iterator[_Section] = iter(self.raw.get_sections())
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

    def copy(self) -> Self:
        clone = super().copy()
        clone.site = self.site
        clone._interwiki_map = self._interwiki_map
        try:
            clone.__dict__['sections'] = self.__dict__['sections'].copy()
        except (KeyError, AttributeError):
            pass
        return clone


class Section(ContainerNode['Section'], method='get_sections'):
    raw: _Section
    title: str
    level: int
    parent: Optional[Section]
    children: dict[str, Section] = None  # = None is necessary to satisfy the abstract property
    _subsections: list[Section]

    def __init__(
        self,
        raw: Union[Raw, _Section],
        root: Optional[Root],
        preserve_comments: bool = False,
        parent: Optional[Section] = None,
        _index: int = None,
    ):
        super().__init__(raw, root, preserve_comments, _index)
        self.title = strip_style(self.raw.title) if self.raw.title else ''
        self.level = self.raw.level
        self.parent = parent
        self.children = {}  # populated by Root.sections
        self._subsections = []

    # region Internal Methods

    @classmethod
    def normalize_raw(cls, raw: Union[Raw, _Section], index: int = None) -> _Section:
        if index is None:
            index = 1 if isinstance(raw, str) else 0
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

    def __bool__(self) -> bool:
        return True  # Sections are more complex than just being a container since they may have content as well

    def __iter__(self) -> Iterator[Section]:
        yield from self.children.values()

    def _formatted_title(self, raw: bool = False) -> str:
        bars = '=' * self.level
        title = self.raw.title if raw else self.title
        return f'{bars}{title}{bars}'

    def _add_sub_section(self, title: str, section: Section):
        section.parent = self
        self.children[title] = section
        self._subsections.append(section)

    def _add_pseudo_sub_section(self, title: str, nodes: Iterable[Node], delim: str = ' '):
        bars = '=' * (self.level + 1)
        raw = f'{bars}{title}{bars}\n{delim.join(n.raw.string for n in nodes)}'
        self._add_sub_section(title, self.__class__(raw, self.root, self.preserve_comments, _index=1))

    # endregion

    @cached_property
    def number(self) -> int:
        try:
            return self.parent._subsections.index(self) + 1
        except AttributeError:  # self.parent is None
            return 0

    @cached_property
    def toc_number(self) -> str:
        if not self.parent or not self.parent.number:
            return str(self.number)
        return f'{self.parent.toc_number}.{self.number}'

    @property
    def depth(self) -> int:
        if self.children:
            return max(section.depth for section in self.children.values()) + 1
        return 0

    def find_section(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = True
    ) -> Union[Section, T]:
        return self._find(title_or_index, default, case_sensitive=case_sensitive)

    def find(self, title_or_index: Union[str, int], default: T = _NotSet) -> Union[Section, T]:
        """Find the subsection with the given title"""
        return self._find(title_or_index, default, case_sensitive=True)

    def _find(
        self, title_or_index: Union[str, int], default: T = _NotSet, case_sensitive: bool = True
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

    def strings(self, strip: bool = True) -> Iterator[str]:
        if title := self.title:
            yield title.strip() if strip else title

        yield from _strings(self.content, strip)
        for subsection in self:
            yield from _strings(subsection, strip)

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

    # endregion

    def copy(self) -> Section:
        clone = super().copy()
        clone.title = self.title
        clone.level = self.level
        clone.parent = self.parent
        clone.children = {}
        clone._subsections = []
        clone_dict, self_dict = clone.__dict__, self.__dict__
        for key in ('number', 'toc_number', 'content'):
            try:
                clone_dict[key] = self_dict[key]
            except KeyError:
                pass
        for section in self._subsections:
            clone._add_sub_section(section.title, section.copy())
        return clone

    # region Printing / Formatting Methods

    def pformat(self, mode: str = 'reprs', indent: int = 0, recurse: bool = True) -> str:
        return '\n'.join(self._pformat(mode, indent, recurse))

    def pprint(self, mode: str = 'reprs', indent: int = 0, recurse: bool = True, _print=print):
        for line in self._pformat(mode, indent, recurse):
            try:
                _print(line)  # Note: print is passed as an arg to allow it to be testable
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
        elif mode == 'toc':
            if self.title and self.number:
                indent_str = ' ' * indent
                yield f'{indent_str}{self.toc_number}. {self.title}'
                indent += 4
        else:
            indent_str = ' ' * indent
            indent += 4
            if mode == 'headers':
                yield f'{indent_str}{self._formatted_title()}'
            elif mode in {'reprs', 'content'}:
                yield f'{indent_str}{self}'
                if mode != 'reprs':
                    if self.content is None:
                        yield 'None'
                    else:
                        yield self.content.pformat(indent)

        if recurse:
            for child in self.children.values():
                yield from child._pformat(mode, indent=indent, recurse=recurse)

    # endregion


# region Helper functions


def _print(*args, _print_func=print, **kwargs):
    try:
        _print_func(*args, **kwargs)  # Note: print is passed as an arg to allow it to be testable
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


def _strings(value, strip: bool = True) -> Iterator[str]:
    if value is None:
        return
    elif isinstance(value, str):
        yield value.strip() if strip else value
    elif isinstance(value, Node):
        yield from value.strings(strip)
    elif isinstance(value, Mapping):
        for key, val in value.items():
            yield from _strings(key)
            yield from _strings(val)
    else:
        try:
            for val in value:
                yield from _strings(val)
        except TypeError:
            value = str(value)
            yield value.strip() if strip else value


def _maybe_copy(obj: T) -> T:
    try:
        return obj.copy()
    except AttributeError:
        return obj


# endregion


# Down here due to circular dependency
from .parsing import as_node  # noqa
from .transformers import dl_keys_to_subsections, transform_section  # noqa

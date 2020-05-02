"""
Takes the next step with WikiText parsed by :mod:`wikitextparser` to process it into nodes based on what each section
contains, and provide a more top-down approach to traversing content on a given page.

This is still a work in process - some data types are not fully handled yet, and some aspects are subject to change.

:author: Doug Skrypa
"""

import logging
import re
import sys
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import MutableMapping
from copy import copy
from typing import Iterable, Optional, Union, TypeVar, Type, Iterator, List as ListType, Dict, Callable, Tuple, Mapping

from wikitextparser import (
    WikiText, Section as _Section, Template as _Template, Table as _Table, Tag as _Tag, WikiLink as _Link,
    WikiList as _List
)

from .compat import cached_property
from .utils import strip_style, ClearableCachedPropertyMixin

__all__ = [
    'Node', 'BasicNode', 'CompoundNode', 'MappingNode', 'Tag', 'String', 'Link', 'ListEntry', 'List', 'Table',
    'Template', 'Root', 'Section', 'as_node', 'extract_links', 'TableSeparator', 'N', 'AnyNode'
]
log = logging.getLogger(__name__)

PY_LT_37 = sys.version_info.major == 3 and sys.version_info.minor < 7
ordered_dict = OrderedDict if PY_LT_37 else dict            # 3.7+ dict retains insertion order; dict repr is cleaner

N = TypeVar('N', bound='Node')
AnyNode = Union[
    'Node', 'BasicNode', 'CompoundNode', 'MappingNode', 'Tag', 'String', 'Link', 'ListEntry', 'List', 'Table',
    'Template', 'Root', 'Section'
]

INTERWIKI_COMMUNITY_LINK_MATCH = re.compile(r'^(w:c:[^:]+):(.+)$').match
SPECIAL_LINK_PREFIXES = {'category', 'image', 'file', 'template'}
_NotSet = object()


class Node(ClearableCachedPropertyMixin):
    def __init__(self, raw: Union[str, WikiText], root: Optional['Root'] = None, preserve_comments=False):
        if isinstance(raw, str):
            raw = WikiText(raw)
        self.raw = raw
        self.preserve_comments = preserve_comments
        self.root = root

    def stripped(self, *args, **kwargs) -> str:
        return strip_style(self.raw.string, *args, **kwargs)

    def __repr__(self):
        return f'<{self.__class__.__name__}()>'

    def __bool__(self):
        return bool(self.raw.string)

    def __eq__(self, other):
        if other.__class__ != self.__class__:
            return False
        return self.raw.string == other.raw.string

    @property
    def is_basic(self):
        return None

    def raw_pprint(self):
        print(self.raw.pformat())

    def pprint(self, indentation=0):
        try:
            print(self.pformat(indentation))
        except OSError as e:
            if e.errno != 22:   # occurs when writing to a closed pipe
                raise

    def pformat(self, indentation=0):
        return (' ' * indentation) + repr(self)


class BasicNode(Node):
    def __repr__(self):
        return f'<{self.__class__.__name__}({self.raw!r})>'

    def __hash__(self):
        return hash((self.__class__, self.raw.string))

    @property
    def is_basic(self):
        return True


class ContainerNode(ABC):
    @abstractmethod
    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        raise NotImplementedError


class CompoundNode(Node, ContainerNode):
    @cached_property
    def children(self) -> ListType[N]:
        return []

    def __repr__(self):
        return f'<{self.__class__.__name__}{self.children!r}>'

    def __getitem__(self, item) -> N:
        return self.children[item]

    def __setitem__(self, key, value: N):
        self.children[key] = value

    def __delitem__(self, key):
        del self.children[key]

    def __iter__(self) -> Iterator[N]:
        return iter(self.children)

    def __len__(self) -> int:
        return len(self.children)

    def __bool__(self) -> bool:
        return bool(self.children)

    @property
    def is_basic(self):
        return False

    @property
    def only_basic(self) -> bool:
        """True if all children are basic; not cached because children may change"""
        return type(self) is CompoundNode and all(c.is_basic for c in self.children)

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        """
        Find all descendent nodes of the given type, optionally with additional matching criteria.

        :param type node_cls: The class of :class:`Node` to find
        :param bool recurse: Whether descendent nodes should be searched recursively or just the direct children of this
          node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        for value in self:
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)

    def find_one(self, node_cls: Type[N], *args, **kwargs) -> Optional[N]:
        """
        :param type node_cls: The class of :class:`Node` to find
        :param args: Positional args to pass to :meth:`.find_all`
        :param kwargs: Keyword args to pass to :meth:`.find_all`
        :return: The first :class:`Node` object that matches the given criteria, or None if no matching nodes could be
          found.
        """
        return next(self.find_all(node_cls, *args, **kwargs), None)

    def pformat(self, indentation=0) -> str:
        indent = ' ' * indentation
        inside = indent + (' ' * 4)
        child_lines = ('\n'.join(inside + line for line in c.pformat().splitlines()) for c in self.children)
        children = ',\n'.join(child_lines)
        return f'{indent}<{self.__class__.__name__}[\n{children}\n{indent}]>'

    @classmethod
    def from_nodes(
            cls, nodes: Iterable[Node], root: Optional['Root'] = None, preserve_comments=False, delim: str = '\n'
    ) -> 'CompoundNode':
        node = cls(delim.join(n.raw.string for n in nodes), root, preserve_comments)
        node.children.extend(nodes)
        return node


class MappingNode(CompoundNode, MutableMapping):
    def __init__(self, raw: Union[str, WikiText], root: Optional['Root'] = None, preserve_comments=False, content=None):
        super().__init__(raw, root, preserve_comments)
        if content:
            self.children.update(content)

    @cached_property
    def children(self) -> Dict[Union[str, N], Optional[N]]:
        return ordered_dict()

    def keys(self):
        return self.children.keys()

    def pformat(self, indentation=0):
        indent = (' ' * indentation)
        inside = indent + (' ' * 4)
        child_lines = (
            '\n'.join(inside + line for line in f'{k!r}: {v.pformat() if v is not None else None}'.splitlines())
            for k, v in self.children.items()
        )
        children = ',\n'.join(child_lines)
        return f'{indent}<{self.__class__.__name__}{{\n{children}\n{indent}}}>'

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        """
        Find all descendent nodes of the given type, optionally with additional matching criteria.

        :param type node_cls: The class of :class:`Node` to find
        :param bool recurse: Whether descendent nodes should be searched recursively or just the direct children of this
          node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        for value in self.values():
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)


class Tag(BasicNode, ContainerNode):
    def __init__(self, raw: Union[str, WikiText, _Tag], root: Optional['Root'] = None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.get_tags()[0]
            except IndexError as e:
                raise ValueError('Invalid wiki tag value') from e
        self.name = self.raw.name
        self.attrs = self.raw.attrs

    def __repr__(self):
        attrs = f':{self.attrs}' if self.attrs else ''
        return f'<{self.__class__.__name__}[{self.name}{attrs}][{self.value}]>'

    @cached_property
    def value(self):
        if self.name == 'nowiki':
            return String(self.raw.contents.strip(), self.root)
        return as_node(self.raw.contents.strip(), self.root, self.preserve_comments)

    @property
    def is_basic(self):
        return self.value.is_basic

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        if value := self.value:
            yield from _find_all(value, node_cls, recurse, **kwargs)

    def __getitem__(self, item):
        return self.attrs[item]

    def get(self, item, default=None):
        return self.attrs.get(item, default)


class String(BasicNode):
    def __init__(self, raw: Union[str, WikiText], root: Optional['Root'] = None):
        super().__init__(raw, root)
        self.value = strip_style(self.raw.string)

    @cached_property
    def lower(self):
        return self.value.lower()

    def __repr__(self):
        return f'<{self.__class__.__name__}({self.raw.string.strip()!r})>'

    def __str__(self):
        return self.value

    def __add__(self, other):
        return String(self.raw.string + other.raw.string, self.root)

    def __bool__(self):
        return bool(self.value)


class Link(BasicNode):
    def __init__(self, raw: Union[str, WikiText, _Link], root: Optional['Root'] = None):
        super().__init__(raw, root)         # note: target = title + fragment; fragment not desired right now
        self._orig = self.raw.wikilinks[0]  # type: _Link
        self.title = self._orig.title       # type: str
        self.text = self._orig.text         # type: str

    def __eq__(self, other: 'Link') -> bool:
        if not isinstance(other, Link):
            return False
        return self._str == other._str and self.source_site == other.source_site

    def __hash__(self):
        return hash((self.__class__, self._str, self.source_site))

    def __lt__(self, other: 'Link') -> bool:
        return self.__cmp_tuple < other.__cmp_tuple

    def __str__(self):
        return self.show or self.raw.string

    @property
    def __cmp_tuple(self):
        return self.interwiki, self.special, self._str, self.source_site

    @classmethod
    def _format(cls, title: str, text: Optional[str] = None):
        return f'[[{title}|{text}]]' if text else f'[[{title}]]'

    @classmethod
    def from_title(cls, title: str, root: Optional['Root'] = None, text: Optional[str] = None) -> 'Link':
        return cls(cls._format(title, text), root)

    @cached_property
    def _str(self):
        return self._format(self.title, self.text)

    @cached_property
    def show(self) -> Optional[str]:
        """The text that would be shown for this link (without fragment)"""
        text = self.text or self.title
        return text.strip() if text else None

    @cached_property
    def source_site(self):
        return self.root.site if self.root else None

    @cached_property
    def special(self) -> bool:
        prefix = self.title.split(':', 1)[0].lower()
        return prefix in SPECIAL_LINK_PREFIXES

    @cached_property
    def interwiki(self) -> bool:
        try:
            return bool(self.iw_key_title)
        except ValueError:
            return False

    @cached_property
    def iw_key_title(self) -> Tuple[str, str]:
        title = self.title
        if (root := self.root) and ':' in title:
            if m := INTERWIKI_COMMUNITY_LINK_MATCH(title):
                # noinspection PyTypeChecker
                return tuple(m.groups())
            elif iw_map := root._interwiki_map:
                prefix, iw_title = title.split(':', maxsplit=1)
                if prefix in iw_map:
                    return prefix, iw_title
                lc_prefix = prefix.lower()
                if lc_prefix in iw_map:
                    return lc_prefix, iw_title
        raise ValueError(f'{self} is not an interwiki link')

    def __repr__(self):
        if self.root and self.root.site:
            parts = self.root.site.split('.')[:-1]      # omit domain
            if parts[0] in ('www', 'wiki', 'en'):       # omit common prefixes
                parts = parts[1:]
            site = '.'.join(parts)
            return f'<{self.__class__.__name__}:{self._str!r}@{site}>'
        return f'<{self.__class__.__name__}:{self._str!r}>'

    @cached_property
    def to_file(self) -> bool:
        return self.title.lower().startswith(('image:', 'file:'))


class ListEntry(CompoundNode):
    def __init__(self, raw: Union[str, WikiText], root: Optional['Root'] = None, preserve_comments=False, _value=None):
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

    def __repr__(self):
        if self._children:
            return f'<{self.__class__.__name__}({self.value!r}, {self.children!r})>'
        return f'<{self.__class__.__name__}({self.value!r})>'

    def __bool__(self):
        return bool(self.value) or bool(self.children)

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        if value := self.value:
            yield from _find_all(value, node_cls, recurse, **kwargs)
        for value in self:
            yield from _find_all(value, node_cls, recurse, recurse, **kwargs)

    @cached_property
    def sub_list(self) -> Optional['List']:
        if not self._children:
            return None
        content = '\n'.join(c[1:] for c in map(str.strip, self._children.splitlines()))
        return List(content, self.root, self.preserve_comments)

    @property
    def children(self) -> ListType['ListEntry']:
        sub_list = self.sub_list
        if not sub_list:
            return []
        return sub_list.children

    def extend(self, list_node: 'List'):
        if self._children is None:
            self.__dict__['sub_list'] = list_node
        else:
            self.sub_list.extend(list_node)

    def _extend(self, text: str, convert=True):
        self.clear_cached_properties()
        text = f'** {text}'
        if self._children is None:
            if convert and self.value is not None:
                self._children = f'** {self.value.raw.string}\n{text}'
                self.value = None
                self.raw = WikiText(self._children)
            else:
                self.raw = WikiText(f'{self.raw.string}\n{text}')
                self._children = text
        else:
            self.raw = WikiText(f'{self.raw.string}\n{text}')
            self._children = f'{self._children}\n{text}'

    def pformat(self, indentation=0) -> str:
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


class List(CompoundNode):
    def __init__(self, raw: Union[str, WikiText, _List], root: Optional['Root'] = None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.get_lists()[0]
            except IndexError as e:
                raise ValueError('Invalid wiki list value') from e
        self._as_mapping = None
        self.start_char = self.raw.string[0]

    @cached_property
    def children(self) -> ListType[ListEntry]:
        return [ListEntry(val, self.root, self.preserve_comments) for val in map(str.strip, self.raw.fullitems)]

    def extend(self, list_node: 'List'):
        self.children.extend(list_node.children)

    def iter_flat(self) -> Iterator[N]:
        for child in self.children:
            if val := child.value:
                yield val
            if child.sub_list:
                yield from child.sub_list.iter_flat()

    def as_mapping(self, *args, **kwargs) -> MappingNode:
        if self._as_mapping is None:
            self._as_mapping = MappingNode(self.raw, self.root, self.preserve_comments, self.as_dict(*args, **kwargs))
        return self._as_mapping

    def as_dict(self, sep=':', multiline=None) -> Dict[Union[str, N], Optional[N]]:
        data = ordered_dict()
        node_fn = lambda x: as_node(x.strip(), self.root, self.preserve_comments)

        def _add_kv(key, val):
            # log.debug(f'Storing key={key!r} val={val!r}')
            if isinstance(key, String):
                data[key.value] = val
            elif isinstance(key, Link):
                data[key.text] = val
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
        ctrl_pat_match = re.compile('^([*#:;]+)\s*(.*)$', re.DOTALL).match
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
        ctrl_pat_match = re.compile('^([*#:;]+)\s*(.*)$', re.DOTALL).match
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


class Table(CompoundNode):
    _rowspan_with_template = re.compile(r'(\|\s*rowspan="?\d+"?)\s*{')

    def __init__(self, raw: Union[str, WikiText, _Table], root: Optional['Root'] = None, preserve_comments=False):
        raw = self._rowspan_with_template.sub(r'\1 | {', raw.string if isinstance(raw, WikiText) else raw)
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.tables[0]
            except IndexError as e:
                raise ValueError('Invalid wiki table value') from e
        self.caption = self.raw.caption.strip() if self.raw.caption else None
        self._header_rows = None
        self._raw_headers = None

    @cached_property
    def headers(self):
        rows = self.raw.cells()
        row_spans = [int(cell.attrs.get('rowspan', 1)) if cell is not None else 1 for cell in next(iter(rows))]
        self._header_rows = max(row_spans)
        self._raw_headers = []
        str_headers = []

        for i, row in enumerate(rows):
            if i == self._header_rows:
                break
            row_data = [
                as_node(cell.value.strip(), self.root, self.preserve_comments) if cell else cell for cell in row
            ]
            self._raw_headers.append(row_data)
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

        headers = []
        for row_span, *header_vals in zip(row_spans, *str_headers):
            header_vals = header_vals[:-(row_span - 1)] if row_span > 1 else header_vals
            headers.append(':'.join(map(strip_style, filter(None, header_vals))))
        return headers

    @cached_property
    def children(self):
        headers = self.headers
        node_fn = lambda cell: as_node(cell.value.strip(), self.root, self.preserve_comments) if cell else cell
        processed = []
        for row in self.raw.cells()[self._header_rows:]:
            if int(row[0].attrs.get('colspan', 1)) >= len(headers):  # Some tables have an incorrect value...
                processed.append(TableSeparator(node_fn(row[0])))
            else:
                mapping = zip(headers, map(node_fn, row))
                processed.append(MappingNode(row, self.root, self.preserve_comments, mapping))
        return processed


class TableSeparator:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f'<{self.__class__.__name__}({self.value!r})>'

    def pformat(self, indentation=0) -> str:
        indent = ' ' * indentation
        return f'{indent}<{self.__class__.__name__}[{self.value!r}]>'


class Template(BasicNode, ContainerNode):
    _defaults = {'n/a': 'N/A'}
    _basic_names = {'n/a', 'small'}

    def __init__(self, raw: Union[str, WikiText, _Template], root: Optional['Root'] = None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.templates[0]
            except IndexError as e:
                raise ValueError('Invalid wiki template value') from e
        self.name = self.raw.name.strip()
        self.lc_name = self.name.lower()

    def __repr__(self):
        return f'<{self.__class__.__name__}({self.name!r}: {self.value!r})>'

    @cached_property
    def is_basic(self):
        if self.lc_name in self._basic_names:
            return True
        return self.value is None or isinstance(self.value, (String, Link))

    @cached_property
    def value(self):
        args = self.raw.arguments
        if not args:
            return None

        if self.lc_name == 'abbr':          # [short, long]
            return [a.value for a in args]
        elif all(arg.positional for arg in args):
            if len(args) == 1:
                raw_value = args[0].value or self._defaults.get(self.lc_name or '')
                value = as_node(raw_value, self.root, self.preserve_comments)
                if self.lc_name in ('main', 'see also') and isinstance(value, String):
                    value = Link.from_title(value.value, self.root)
                return value
            return [as_node(a.value, self.root, self.preserve_comments) for a in args]

        mapping = MappingNode(self.raw, self.root, self.preserve_comments)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = as_node(arg.value.strip(), self.root, self.preserve_comments, strict_tags=True)
        return mapping

    @cached_property
    def zipped(self):
        if not isinstance(self.value, MappingNode):
            return None
        mapping = MappingNode(self.raw, self.root, self.preserve_comments)
        keys, values = [], []
        num_search = re.compile(r'[a-z](\d+)$', re.IGNORECASE).search
        for key, value in self.value.items():
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

    def __getitem__(self, item):
        if self.value is None:
            raise TypeError('Cannot index a template with no value')
        return self.value[item]

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        if value := self.value:
            if isinstance(value, Node):
                yield from _find_all(value, node_cls, recurse, **kwargs)
            else:
                for node in value:
                    yield from _find_all(node, node_cls, recurse, recurse, **kwargs)


class Root(Node):
    # Children = sections
    def __init__(
            self, page_text: Union[str, WikiText], site: Optional[str] = None, preserve_comments=False,
            interwiki_map: Optional[Mapping[str, str]] = None
    ):
        if isinstance(page_text, str):
            page_text = WikiText(page_text.replace('\xa0', ' '))
        super().__init__(page_text, None, preserve_comments)
        self.site = site                                        # type: Optional[str]
        self._interwiki_map = interwiki_map                     # type: Optional[Mapping[str, str]]

    def __getitem__(self, item: str) -> 'Section':
        return self.sections[item]

    def __iter__(self) -> Iterator['Section']:
        root = self.sections
        yield root
        yield from root

    def find_all(self, node_cls: Type[N], recurse=True, **kwargs) -> Iterator[N]:
        """
        Find all descendent nodes of the given type.

        :param type node_cls: The class of :class:`Node` to find
        :param bool recurse: Whether descendent nodes should be searched recursively or just the direct children of this
          node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        return self.sections.find_all(node_cls, recurse, **kwargs)

    @cached_property
    def sections(self) -> 'Section':
        sections = iter(self.raw.sections)
        root = Section(next(sections), self, self.preserve_comments)
        last_by_level = {0: root}
        for sec in sections:
            parent_lvl = sec.level - 1
            while parent_lvl > 0 and parent_lvl not in last_by_level:
                parent_lvl -= 1
            parent = last_by_level[parent_lvl]
            section = Section(sec, self, self.preserve_comments)
            parent.children[section.title] = section
            last_by_level[section.level] = section
        return root


class Section(Node, ContainerNode):
    def __init__(self, raw: Union[str, WikiText, _Section], root: Optional['Root'], preserve_comments=False, _index=0):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:                                                    # _index is needed for re-constructed subsections
                self.raw = self.raw.get_sections()[_index]          # type: _Section
            except IndexError as e:
                raise ValueError('Invalid wiki section value') from e
        self.title = strip_style(self.raw.title)                        # type: str
        self.level = self.raw.level                                     # type: int
        self.children = ordered_dict()  # populated by Root.sections

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self.level}: {self.title}]>'

    def __getitem__(self, item: str) -> 'Section':
        return self.children[item]

    def __iter__(self) -> Iterator['Section']:
        return iter(self.children.values())

    def _formatted_title(self):
        bars = "=" * self.level
        return f'{bars}{self.raw.title}{bars}'

    def _add_subsection(self, title: str, nodes: Iterable[Node], delim: str = ' '):
        level = self.level + 1
        raw = f'{"=" * level}{title}{"=" * level}\n{delim.join(n.raw.string for n in nodes)}'
        self.children[title] = self.__class__(raw, self.root, self.preserve_comments, 1)

    @property
    def depth(self) -> int:
        if self.children:
            return max(c.depth for c in self.children.values()) + 1
        return 0

    def find(self, title: str, default: None = _NotSet) -> Optional['Section']:
        """Find the subsection with the given title"""
        try:
            return self.children[title]
        except KeyError:
            pass
        for child in self.children.values():
            try:
                return child.find(title)
            except KeyError:
                pass
        if default is _NotSet:
            raise KeyError(f'Cannot find section={title!r} in {self} or any subsections')
        return default

    @cached_property
    def content(self):
        if self.level == 0:                                 # without .string here, .tags() returns the full page's tags
            raw = self.raw.string.strip()
            node = as_node(raw, self.root, self.preserve_comments)
            if type(node) is CompoundNode:                          # Split infobox / templates from first paragraph
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
                        if isinstance(child, Template) and 'infobox' in child.name.lower():
                            found_infobox = True
                        non_basic.append(child)
                remainder.extend(children)
                if found_infobox and non_basic and remainder:
                    node = CompoundNode.from_nodes(non_basic, self.root, self.preserve_comments)
                    node.children.append(CompoundNode.from_nodes(remainder, self.root, self.preserve_comments, ' '))
            return node

        content = self.raw.contents.strip()
        if self.children:
            content = content.partition(next(iter(self))._formatted_title())[0].strip()
        return as_node(content, self.root, self.preserve_comments)    # chop off the header

    def processed(
            self, convert_maps=True, fix_dl_last_none=True, fix_nested_dl_ul_ol=True, merge_maps=True,
            fix_dl_key_as_header=True
    ):
        """
        The content of this section, processed to work around various issues.

        :param bool convert_maps: Convert List objects to MappingNode objects, if possible
        :param bool fix_dl_last_none: If a ul/ol follows a definition list on the top level of this section's content,
          and the last value in the definition list is None, update that value to be the list that follows
        :param bool fix_nested_dl_ul_ol: When a dl contains a value that is a ul, and that ul contains a nested ol, fix
          the lists so that they are properly nested
        :param bool merge_maps: Merge consecutive MappingNode objects
        :param bool fix_dl_key_as_header: Some pages have sub-sections with ``;`` used to indicate a section header
          instead of surrounding the header with ``=``
        :return: CompoundNode
        """
        content = copy(self.content)
        if not isinstance(content, CompoundNode):
            return content

        if convert_maps:
            children = []
            did_convert = False
            last = len(content) - 1
            for i, child in enumerate(content):
                if isinstance(child, List) and (len(child) > 1 or (i < last and isinstance(content[i + 1], List))):
                    try:
                        as_map = child.as_mapping()
                    except Exception:
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

        if fix_dl_last_none:
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

        if fix_nested_dl_ul_ol:
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

        if merge_maps:
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

        if fix_dl_key_as_header:
            children = []
            did_fix = False
            title = None            # type: Optional[str]
            subsection_nodes = []
            for child in content:
                new_title = None
                if isinstance(child, List) and len(child) == 1 and child.raw.string.startswith(';'):
                    title_node = child.children[0].value
                    if isinstance(title_node, String):
                        new_title = title_node.value
                    elif title_node.__class__ is CompoundNode and title_node.only_basic:
                        new_title = ' '.join(str(n.value) for n in title_node)

                if new_title:
                    if title:
                        did_fix = True
                        self._add_subsection(title, subsection_nodes)
                        subsection_nodes = []

                    title = new_title
                elif title:
                    subsection_nodes.append(child)
                else:
                    children.append(child)

            if title:
                did_fix = True
                self._add_subsection(title, subsection_nodes)

            if did_fix:
                content.children.clear()
                content.children.extend(children)

        return content

    def pprint(self, mode='reprs', indent=0, recurse=True):
        if mode == 'raw':
            try:
                print(self.raw.pformat())
            except OSError as e:
                if e.errno != 22:   # occurs when writing to a closed pipe
                    raise
        elif mode == 'headers':
            try:
                print(f'{" " * indent}{"=" * self.level}{self.title}{"=" * self.level}')
            except OSError as e:
                if e.errno != 22:   # occurs when writing to a closed pipe
                    raise
            indent += 4
        elif mode in ('reprs', 'content', 'processed'):
            try:
                print(f'{" " * indent}{self}')
            except OSError as e:
                if e.errno != 22:   # occurs when writing to a closed pipe
                    raise
            indent += 4
            if mode == 'content':
                self.content.pprint(indent)
            elif mode == 'processed':
                self.processed().pprint(indent)

        if recurse:
            for child in self.children.values():
                child.pprint(mode, indent=indent, recurse=recurse)

    def find_all(self, node_cls: Type[N], recurse=False, **kwargs) -> Iterator[N]:
        if content := self.content:
            yield from _find_all(content, node_cls, recurse, **kwargs)
        if recurse:
            for child in self:
                yield from _find_all(child, node_cls, recurse, **kwargs)


def _find_all(node, node_cls: Type[N], recurse=True, _recurse_first=True, **kwargs) -> Iterator[N]:
    if isinstance(node, node_cls):
        if not kwargs or all(getattr(node, k, _NotSet) == v for k, v in kwargs.items()):
            yield node
        if recurse and isinstance(node, ContainerNode):
            yield from node.find_all(node_cls, recurse, **kwargs)
    elif _recurse_first and isinstance(node, ContainerNode):
        yield from node.find_all(node_cls, recurse=recurse, **kwargs)


WTP_TYPE_METHOD_NODE_MAP = {
    'Template': 'templates',
    'Comment': 'comments',
    'ExtensionTag': 'get_tags',
    'Tag': 'get_tags',          # Requires .get_tags() to be called before being in ._type_to_spans
    'Table': 'tables',          # Requires .tables to be accessed before being in ._type_to_spans
    'WikiList': 'get_lists',    # Requires .get_lists() to be called before being in ._type_to_spans
}
WTP_ACCESS_FIRST = {'Tag', 'Table', 'WikiList'}
WTP_ATTR_TO_NODE_MAP = {
    'get_tags': Tag, 'templates': Template, 'tables': Table, 'get_lists': List, 'comments': BasicNode
}


def as_node(wiki_text: Union[str, WikiText], root: Optional[Root] = None, preserve_comments=False, strict_tags=False):
    """
    :param str|WikiText wiki_text: The content to process
    :param Root root: The root node that is an ancestor of this node
    :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
    :param bool strict_tags: If True, require tags to be either self-closing or have a matching closing tag to consider
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
        span = next(type_spans, None)
        if span and strict_tags and attr == 'tags':
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
                #     log.debug(f'  > It was the first object found')
                # else:
                #     log.debug(f'  > It came before the previously discovered first object')
                first = start
                first_attr = attr
                if first == node_start:
                    # log.debug(f'    > It is definitely the first object')
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


def extract_links(raw, root: Optional[Root] = None):
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
        if before and raw_str:
            if bm := end_match(before):
                # log.debug(f' > Found quotes at the end of before: {bm.group(2)}')
                if am := start_match(raw_str):
                    # log.debug(f' > Found quotes at the beginning of after: {am.group(1)}')
                    before = bm.group(1).strip()
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


def short_repr(text):
    text = str(text)
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')


def wiki_attr_values(wiki_text, attr, known_values=None):
    if known_values:
        try:
            return known_values[attr]
        except KeyError:
            pass
    value = getattr(wiki_text, attr)
    return value() if hasattr(value, '__call__') else value

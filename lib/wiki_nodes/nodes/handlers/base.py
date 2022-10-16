"""
Node processing handler base class.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type, Union, Optional, TypeVar, Generic

if TYPE_CHECKING:
    from .nodes import Node  # noqa

__all__ = ['NodeHandler']
log = logging.getLogger(__name__)

OptStr = Optional[str]
N = TypeVar('N', bound='Node')
H = TypeVar('H', bound='NodeHandler')


class NodeHandler(ABC, Generic[N]):
    __slots__ = ('node',)

    _cls_handler_root_map: dict[Type[N], Type[H]] = {}
    _site_name_handler_map: dict[OptStr, dict[str, Type[H]]]
    _site_prefix_handler_map: dict[OptStr, dict[str, Type[H]]]

    node_cls: Type[N]
    site: Optional[str] = None
    name: Optional[str] = None
    prefix: Optional[str] = None

    def __init_subclass__(
        cls, for_name: str = None, prefix: str = None, site: str = None, root: bool = False, **kwargs
    ):
        super().__init_subclass__(**kwargs)
        if root:
            node_cls = cls.__orig_bases__[0].__args__[0]  # noqa  # The N from subclassing NodeHandler[N]
            cls._cls_handler_root_map[node_cls] = cls
            cls._site_name_handler_map = {}
            cls._site_prefix_handler_map = {}
            return

        if site is not None:
            cls.site = site
        if for_name:
            cls.name = for_name
            cls.prefix = None
            try:
                cls._site_name_handler_map[site][for_name] = cls
            except KeyError:
                cls._site_name_handler_map[site] = {for_name: cls}
        elif prefix:
            cls.prefix = prefix
            cls.name = None
            try:
                cls._site_prefix_handler_map[site][prefix] = cls
            except KeyError:
                cls._site_prefix_handler_map[site] = {prefix: cls}
        elif ABC not in cls.__bases__:
            raise TypeError(f'Missing required keyword argument for class={cls.__name__} init: for_name or prefix')

    def __init__(self, node: N):
        self.node = node

    @classmethod
    @abstractmethod
    def get_name(cls, node: N) -> str:
        raise NotImplementedError

    @classmethod
    def for_node(cls: Type[H], node: N) -> Union[H, NodeHandler[N]]:
        if (nh_cls := cls) is NodeHandler:
            try:
                nh_cls = cls._cls_handler_root_map[node.__class__]
            except KeyError as e:
                raise TypeError(f'No node handlers have been registered for {node.__class__.__name__} nodes') from e

        try:
            site: str = node.root.site
        except AttributeError:
            sites = (None,)
        else:
            sites = _with_parent_domains(site)

        name = nh_cls.get_name(node)
        for site in sites:
            if handler := nh_cls._for_node(name, site):
                # log.warning(f'Found handler={handler.__name__} for {site=} {name=}')
                return handler(node)

        # log.warning(f'Could not find a handler for {sites=} {name=}')
        return nh_cls(node)

    @classmethod
    def _for_node(cls, name: str, site: Optional[str]) -> Optional[Type[NodeHandler[N]]]:
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


def _with_parent_domains(site: str) -> list[OptStr]:
    sites = [site]
    while site:
        try:
            site = site.split('.', 1)[1]
        except IndexError:
            break
        else:
            sites.append(site)

    sites.append(None)
    return sites

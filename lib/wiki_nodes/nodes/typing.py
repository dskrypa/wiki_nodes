"""
Helpers for checking node types.
"""

from __future__ import annotations

from typing import TypeVar, Type, TypeGuard, Any, Mapping

from .nodes import N, ContainerNode, CompoundNode

__all__ = ['is_compound_with_ele', 'is_container_with_ele']

T = TypeVar('T')


def is_compound_with_ele(obj, key, ele_type: Type[T], **kwargs) -> TypeGuard[CompoundNode[T]]:
    if obj.__class__ is not CompoundNode:
        return False
    return _element_matches(obj, key, ele_type, kwargs)


def is_container_with_ele(obj, key, ele_type: Type[T], **kwargs) -> TypeGuard[ContainerNode[T]]:
    if not isinstance(obj, ContainerNode):
        return False
    return _element_matches(obj, key, ele_type, kwargs)


def _element_matches(obj, key, ele_type: Type[N], kwargs: Mapping[str, Any]) -> bool:
    try:
        element = obj[key]
    except (KeyError, IndexError, TypeError):
        return False
    if not isinstance(element, ele_type):
        return False
    if kwargs:
        try:
            return all(getattr(element, k) == v for k, v in kwargs.items())
        except AttributeError:
            return False

    return True

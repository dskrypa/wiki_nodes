"""
Enums related to Nodes.
"""

from __future__ import annotations

from enum import Enum

__all__ = ['ListType']


class ListType(Enum):
    OL = '#'  # Ordered list
    UL = '*'  # Unordered list
    DL = ';'  # Definition list

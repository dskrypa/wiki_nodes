"""
Typing helpers.
"""

from typing import Iterable, Union, Optional, Any, Collection

StrOrStrs = Union[str, Collection[str], None]
OptStr = Optional[str]
StrIter = Iterable[str]
Bool = Union[bool, Any]

"""
Tag processing handlers.
"""

from __future__ import annotations

from ..nodes import Tag, String, Link
from ..parsing import as_node
from .base import NodeHandler

__all__ = ['TagHandler']


class TagHandler(NodeHandler[Tag], root=True):
    __slots__ = ()

    @classmethod
    def get_name(cls, node: Tag) -> str:
        return node.name

    def get_value(self):
        tag = self.node
        return as_node(tag.raw.contents.strip(), tag.root, tag.preserve_comments)


class BrHandler(TagHandler, for_name='br'):
    __slots__ = ()

    def get_value(self):
        return '\n'


class NoWikiHandler(TagHandler, for_name='nowiki'):
    __slots__ = ()

    def get_value(self):
        tag = self.node
        return String(tag.raw.contents.strip(), tag.root)


class GalleryHandler(TagHandler, for_name='gallery'):
    __slots__ = ()

    def get_value(self):
        tag = self.node
        root = tag.root
        links = []
        for line in tag.raw.contents.strip().splitlines():
            try:
                title, text = line.rsplit('|', 1)
            except (TypeError, ValueError):
                title, text = line, None
            links.append(Link.from_title(title if title.lower().startswith('file:') else f'File:{title}', root, text))
        return links

"""
Utilities for processing MediaWiki pages into a more usable form.

Notes:\n
  - :mod:`wikitextparser` handles lists, but does not handle stripping of formatting around strings
  - :mod:`mwparserfromhell` does not handle lists, but does handle stripping of formatting around strings
    - Replaced the need for this module for now by implementing :func:`strip_style<.utils.strip_style>`

:author: Doug Skrypa
"""

import logging
from typing import Optional, Union, Iterable, Set, Mapping

from wikitextparser import WikiText

from .compat import cached_property
from .nodes import Root, Template, String, CompoundNode, Tag, Link

__all__ = ['WikiPage']
log = logging.getLogger(__name__)


class WikiPage(Root):
    _ignore_category_prefixes = ()

    def __init__(
            self, title: str, site: Optional[str], content: Union[str, WikiText], categories: Iterable[str],
            preserve_comments=False, interwiki_map: Optional[Mapping[str, str]] = None
    ):
        """
        :param str title: The page title
        :param str site: The site of origin for this page
        :param str|WikiText content: The page content
        :param iterable categories: This page's categories
        :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param dict interwiki_map: Mapping of interwiki link prefix to wiki URL
        """
        super().__init__(content, site, preserve_comments=preserve_comments, interwiki_map=interwiki_map)
        self.title = title
        self._categories = categories

    def __repr__(self):
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def _sort_key(self):
        return self.is_disambiguation, self.title, self.site

    def __eq__(self, other: 'WikiPage') -> bool:
        if not isinstance(other, WikiPage):
            return False
        return self._sort_key == other._sort_key

    def __lt__(self, other: 'WikiPage') -> bool:
        return self._sort_key < other._sort_key

    @cached_property
    def categories(self) -> Set[str]:
        """The lower-case categories for this page, with ignored prefixes (if applicable) filtered out"""
        categories = {
            cat for cat in map(str.lower, self._categories) if not cat.startswith(self._ignore_category_prefixes)
        }
        return categories

    @cached_property
    def disambiguation_link(self) -> Optional[Link]:
        if any('articles needing clarification' in cat for cat in self.categories):
            return Link.from_title(f'{self.title}_(disambiguation)', self)
        return None

    @cached_property
    def is_disambiguation(self) -> bool:
        return any('disambiguation' in cat for cat in self.categories)

    @cached_property
    def is_template(self) -> bool:
        return self.title.startswith('Template:')

    @cached_property
    def as_link(self) -> Link:
        return Link.from_title(self.title, self)

    @cached_property
    def infobox(self) -> Optional[Template]:
        """
        Turns the infobox into a dict.  Values are returned as :class:`WikiText<wikitextparser.WikiText>` to allow for
        further processing of links or other data structures.  Wiki lists are converted to Python lists of WikiText
        values.
        """
        section_0_content = self.sections.content
        if isinstance(section_0_content, Template) and 'infobox' in section_0_content.name.lower():
            return section_0_content
        elif isinstance(section_0_content, CompoundNode):
            try:
                for node in self.sections.content:
                    if isinstance(node, Template) and 'infobox' in node.name.lower():
                        return node
            except Exception as e:
                log.log(9, f'Error iterating over first section content of {self}: {e}')
        return None

    @cached_property
    def intro(self) -> Union[String, CompoundNode, None]:
        """
        Neither parser provides access to the 1st paragraph directly when an infobox template precedes it - need to
        remove the infobox from the 1st section, or any other similar elements.
        """
        try:
            for node in self.sections.content:
                if isinstance(node, String):
                    return node
                elif isinstance(node, Tag) and node.name == 'div' and type(node.value) is CompoundNode:
                    return node.value
                elif type(node) is CompoundNode and node.only_basic:
                    return node
        except Exception as e:
            log.log(9, f'Error iterating over first section content of {self}: {e}')
        return None

    def links(self, unique=True, special=False, interwiki=False) -> Set[Link]:
        """
        :param bool unique: Only include links with unique titles
        :param bool special: Include special (file, image, category, etc) links
        :param bool interwiki: Include interwiki links
        :return set: The set of Link objects matching the specified filters
        """
        links = {l for l in self.find_all(Link) if (special or not l.special) and (interwiki or not l.interwiki)}
        return set({link.title: link for link in links}.values()) if unique else links

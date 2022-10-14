"""
Utilities for processing MediaWiki pages into a more usable form.

Notes:\n
  - :mod:`wikitextparser` handles lists, but does not handle stripping of formatting around strings
  - :mod:`mwparserfromhell` does not handle lists, but does handle stripping of formatting around strings
    - Replaced the need for this module for now by implementing :func:`strip_style<.utils.strip_style>`

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Union, Iterable, Mapping

from wikitextparser import WikiText

from .nodes import Root, Template, String, CompoundNode, Tag, Link
from .utils import cached_property

if TYPE_CHECKING:
    from .http import MediaWikiClient

__all__ = ['WikiPage']
log = logging.getLogger(__name__)


class WikiPage(Root):
    _ignore_category_prefixes = ()

    def __init__(
        self,
        title: str,
        site: Optional[str],
        content: Union[str, WikiText],
        categories: Iterable[str],
        preserve_comments: bool = False,
        interwiki_map: Mapping[str, str] = None,
        client: MediaWikiClient = None,
    ):
        """
        :param title: The page title
        :param site: The site of origin for this page
        :param content: The page content
        :param categories: This page's categories
        :param preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param interwiki_map: Mapping of interwiki link prefix to wiki URL
        :param client: The MediaWikiClient from which this page originated
        """
        super().__init__(content, site, preserve_comments=preserve_comments, interwiki_map=interwiki_map)
        self.title = title
        self._categories = categories
        self._client = client

    def __repr__(self) -> str:
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def _sort_key(self) -> tuple[bool, str, Optional[str]]:
        return self.is_disambiguation, self.title, self.site

    def __eq__(self, other: WikiPage) -> bool:
        if not isinstance(other, WikiPage):
            return False
        return self._sort_key == other._sort_key

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.site) ^ hash(self.title) ^ hash(self.raw.string)

    def __lt__(self, other: WikiPage) -> bool:
        return self._sort_key < other._sort_key

    @cached_property
    def categories(self) -> set[str]:
        """The lower-case categories for this page, with ignored prefixes (if applicable) filtered out"""
        return {cat for cat in map(str.lower, self._categories) if not cat.startswith(self._ignore_category_prefixes)}

    @cached_property
    def similar_name_link(self) -> Optional[Link]:
        content = self.sections.content
        if content.__class__ is CompoundNode and isinstance(content[0], Template) and content[0].name == 'about':
            return Link.from_title(content[0][2].value, self)
        return None

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
    def url(self) -> str:
        if self._client is not None:
            return self._client.url_for_article(self.title)
        raise AttributeError(f'Unable to determine URL when not initialized via MediaWikiClient')

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

    def intro(self, strip_refs: bool = False) -> Union[String, CompoundNode, None]:
        """
        Neither parser provides access to the 1st paragraph directly when an infobox template precedes it - need to
        remove the infobox from the 1st section, or any other similar elements.
        """
        error = False
        intro = None
        try:
            # for i, node in enumerate(self.sections.content):
            for node in self.sections.content:
                # log.info(f'Processing node#{i}: {node.__class__.__name__}')
                if isinstance(node, String) and not node.value.startswith('{{DISPLAYTITLE:'):
                    # log.debug(f'Found intro in node#{i}')
                    intro = node
                    break
                elif isinstance(node, Tag) and node.name == 'div' and type(node.value) is CompoundNode:
                    # log.debug(f'Found intro in node#{i}')
                    intro = node.value
                    break
                elif isinstance(node, Tag) and node.name == 'p' and node.attrs.get('id') == 'firstHeading':
                    intro = node.value
                    break
                elif type(node) is CompoundNode and allowed_in_intro(node):
                    # log.debug(f'Found intro in node#{i}')
                    intro = node
                    break
                # else:
                #     log.debug(f'The intro is not node#{i} - it is a {node.__class__.__name__}')
                #     if type(node) is CompoundNode:
                #         import json
                #         from collections import Counter
                #         types = Counter(n.__class__.__name__ for n in node)
                #         log.debug(f' > Node contents: {json.dumps(types, sort_keys=True, indent=4)}')
        except Exception:  # noqa
            error = True
            log.log(9, f'Error iterating over first section content of {self}:', exc_info=True)

        if intro is None and not error and self.infobox:
            found_infobox = False
            try:
                for node in self.sections.content:
                    if node is self.infobox:
                        found_infobox = True
                    elif found_infobox and type(node) is CompoundNode and starts_with_basic(node):
                        intro = node
                        break
            except Exception:  # noqa
                log.log(9, f'Error iterating over first section content of {self}:', exc_info=True)

        if strip_refs and intro.__class__ is CompoundNode:
            nodes = [node for node in intro if not (isinstance(node, Tag) and node.name == 'ref')]
            if nodes != intro.children:
                log.debug(f'Removed {len(intro.children) - len(nodes)} ref nodes from intro for {self}')
                intro.children = nodes

        return intro

    def links(self, unique: bool = True, special: bool = False, interwiki: bool = False) -> set[Link]:
        """
        :param unique: Only include links with unique titles
        :param special: Include special (file, image, category, etc) links
        :param interwiki: Include interwiki links
        :return: The set of Link objects matching the specified filters
        """
        links = {ln for ln in self.find_all(Link) if (special or not ln.special) and (interwiki or not ln.interwiki)}
        return set({link.title: link for link in links}.values()) if unique else links


def allowed_in_intro(node: CompoundNode) -> bool:
    return node.only_basic or all(n.is_basic or (isinstance(n, Tag) and n.name == 'ref') for n in node)


def starts_with_basic(node: CompoundNode) -> bool:
    if first := next(iter(node), None):
        return first.is_basic
    return False

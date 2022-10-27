#!/usr/bin/env python

from functools import cached_property
from pathlib import Path

from cli_command_parser import Command, Option, Flag, Positional, TriFlag, SubCommand, ParamGroup, main, inputs

from wiki_nodes.__version__ import __author_email__, __version__  # noqa
from wiki_nodes.nodes.nodes import Node


class WikiPageViewer(Command, description='View a Wiki page', option_name_mode='-'):
    url: str
    sub_cmd = SubCommand()
    debug = Flag('-d', help='Show debug logging')

    def _init_command_(self):
        import logging

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s')
        else:
            logging.basicConfig(level=logging.INFO, format='%(message)s')

    @cached_property
    def page(self):
        from wiki_nodes import MediaWikiClient, WikiPage

        url = self.url
        if not url.startswith(('http:', 'https:')):
            path = Path(url)
            if path.exists():
                return WikiPage(path.stem, None, path.read_text('utf-8'))

        return MediaWikiClient.page_for_article(url)


class View(WikiPageViewer, help='View a wiki page'):
    MODES = ('raw', 'raw-pretty', 'headers', 'reprs', 'content', 'processed', 'toc')
    url = Positional(help='A Wiki page URL')
    with ParamGroup('Output Options'):
        mode = Option('-m', choices=MODES, default='raw', help='Page display mode')
    with ParamGroup('Selection Options'):
        section = Option('-s', help='The section to view')
        index = Option('-i', type=int, nargs=(1, 2), help='Index or slice within the selected node/section to view')
        type = Option('-t', type=inputs.ChoiceMap(Node.TYPES, case_sensitive=False), help='Filter output to the specified node type')
        recursive = TriFlag('-r', alt_short='-R', alt_prefix='not', help='Whether find_all nodes should be called recursively')

    def main(self):
        for node in self.get_nodes():
            node.pprint(self.mode)

    def get_nodes(self):
        from wiki_nodes import Section

        if self.section:
            nodes = self.page.find_all(Section, title=self.section)
        else:
            nodes = (self.page.sections,)

        if self.index:
            if len(self.index) > 1:
                index = slice(*self.index)
                nodes = [n for node in nodes for n in node.processed()[index]]
            else:
                index = self.index[0]
                nodes = [node.processed()[index] for node in nodes]

        if node_type := self.type:
            nodes = [n for node in nodes for n in node.find_all(node_type, recurse=self.recursive)]

        return nodes


class Meta(WikiPageViewer, help='View metadata about a given wiki page'):
    url = Positional(help='A Wiki page URL')
    categories = Flag('-c', help='Show page categories')

    def main(self):
        self.print_title()

    def print_title(self):
        from wiki_nodes.http import MediaWikiClient

        client = MediaWikiClient(self.url, nopath=True)
        print(client.article_url_to_title(self.url))
        if self.categories:
            self._print_categories()

    def _print_categories(self):
        print(f'Categories for {self.page.title}:\n' + '\n'.join(sorted(self.page.categories)))


class Save(WikiPageViewer, help='Save a given wiki page'):
    url = Positional(help='A Wiki page URL')
    output: Path = Option('-o', type=inputs.Path(type='file|dir'), required=True, help='Output path')

    def main(self):
        text = self.page.raw.string
        if self.output.is_dir() or not self.output.suffix:
            path = self.output.joinpath(f'{self.page.title}.wiki')
            if path.exists():
                print(f'Warning: {path.as_posix()} already exists!')
        else:
            path = self.output

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf=8') as f:
            print(f'Saving {self.page.title} to {self.output.as_posix()}')
            f.write(text)


if __name__ == '__main__':
    main()

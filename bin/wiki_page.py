#!/usr/bin/env python

from cli_command_parser import Command, Option, Flag, Positional, TriFlag, main

from wiki_nodes.__version__ import __author_email__, __version__  # noqa

MODES = ('raw', 'headers', 'reprs', 'content', 'processed', 'title')


class WikiPageViewer(Command, description='View a Wiki page', option_name_mode='-'):
    url = Positional(help='A Wiki page URL')
    mode = Option('-m', choices=MODES, default='raw', help='Page display mode')
    recursive = TriFlag('-r', alt_short='-R', alt_prefix='not', help='Whether nodes should be printed recursively')
    section = Option('-s', help='The section to view')
    index = Option('-i', type=int, nargs=(1, 2), help='Index or slice within the selected node/section to view')
    debug = Flag('-d', help='Show debug logging')

    def _init_command_(self):
        import logging

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s')
        else:
            logging.basicConfig(level=logging.INFO, format='%(message)s')

    def main(self):
        if self.mode == 'title':
            self.print_title()
        else:
            self.print_page()

    def print_page(self):
        from wiki_nodes import MediaWikiClient, Section

        page = MediaWikiClient.page_for_article(self.url)
        if self.section:
            nodes = page.find_all(Section, title=self.section)
        else:
            nodes = (page.sections,)

        if self.index:
            if len(self.index) > 1:
                index = slice(*self.index)
                nodes = [n for node in nodes for n in node.processed()[index]]
            else:
                index = self.index[0]
                nodes = [node.processed()[index] for node in nodes]

        kwargs = {'recurse': self.recursive} if self.recursive is not None else {}
        for node in nodes:
            node.pprint(self.mode, **kwargs)

    def print_title(self):
        from wiki_nodes.http import MediaWikiClient

        client = MediaWikiClient(self.url, nopath=True)
        print(client.article_url_to_title(self.url))


if __name__ == '__main__':
    main()

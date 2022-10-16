#!/usr/bin/env python

from cli_command_parser import Command, Option, Flag, Positional, main, inputs

from wiki_nodes.__version__ import __author_email__, __version__  # noqa

MODES = ('raw', 'headers', 'reprs', 'content', 'processed', 'title')


class WikiPageViewer(Command, description='View a Wiki page'):
    url = Positional(help='A Wiki page URL')
    mode = Option('-m', choices=MODES, default='raw', help='Page display mode')
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

        for node in nodes:
            self.print_node(node)

    def print_node(self, node):
        from wiki_nodes.nodes import Section

        indent = 0
        if self.mode == 'raw':
            node.raw_pprint()
        elif self.mode == 'headers':
            try:
                print(f'{"=" * node.level}{node.title}{"=" * node.level}')  # noqa
            except AttributeError:
                raise ValueError(f'Invalid mode={self.mode!r} for the selected {node=}')
            indent += 4
        elif self.mode in ('reprs', 'content', 'processed'):
            if self.mode == 'content':
                getattr(node, 'content', node).pprint(indent)
            elif self.mode == 'processed':
                try:
                    node.processed().pprint(indent)  # noqa
                except AttributeError:
                    raise ValueError(f'Invalid mode={self.mode!r} for the selected {node=}')

        if isinstance(node, Section):
            for child in node.children.values():
                child.pprint(self.mode, indent=indent, recurse=True)

    def print_title(self):
        from wiki_nodes.http import MediaWikiClient

        client = MediaWikiClient(self.url, nopath=True)
        print(client.article_url_to_title(self.url))


if __name__ == '__main__':
    main()

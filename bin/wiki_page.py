#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from argparse import ArgumentParser

sys.path.insert(0, PROJECT_ROOT.as_posix())
from wiki_nodes.__version__ import __author_email__, __version__
from wiki_nodes.http import MediaWikiClient

log = logging.getLogger(__name__)
MODES = ('raw', 'headers', 'reprs', 'content', 'processed', 'title')


def main():
    parser = ArgumentParser(description='View a Wiki page')
    parser.add_argument('url', help='A Wiki page URL')
    parser.add_argument('--mode', '-m', choices=MODES, default='raw', help='Page display mode')
    parser.add_argument('--debug', '-d', action='store_true', help='Show debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')

    if args.mode == 'title':
        client = MediaWikiClient(args.url, nopath=True)
        print(client.article_url_to_title(args.url))
    else:
        page = MediaWikiClient.page_for_article(args.url)
        page.sections.pprint(args.mode)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()

#!/usr/bin/env python

from pathlib import Path

import logging
from argparse import ArgumentParser
from itertools import chain

from wiki_nodes.__version__ import __author_email__, __version__  # noqa
from wiki_nodes.http import MediaWikiClient

log = logging.getLogger(__name__)


def main():
    parser = ArgumentParser(description='Save image files from a Wiki page')
    parser.add_argument('url', help='A Wiki page URL from which files should be saved')
    parser.add_argument('output', help='Directory in which files should be saved')
    parser.add_argument('--debug', '-d', action='store_true', help='Show debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')

    out_dir = Path(args.output).expanduser().resolve()
    if not out_dir.exists():
        out_dir.mkdir(parents=True)
    if not out_dir.is_dir():
        raise ValueError('The output argument must be a directory')

    client = MediaWikiClient(args.url, nopath=True)
    title_image_titles_map = client.get_page_image_titles(client.article_url_to_title(args.url))
    for title, url in client.get_image_urls(chain.from_iterable(title_image_titles_map.values())).items():
        out_file = out_dir.joinpath(title.split(':', 1)[1])
        data = client.get_image(url)
        log.info(f'Saving {out_file}')
        with out_file.open('wb') as f:
            f.write(data)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()

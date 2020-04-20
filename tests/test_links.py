#!/usr/bin/env python

import logging
import sys
from pathlib import Path
from unittest import main, TestCase
from unittest.mock import MagicMock, patch

sys.path.append(Path(__file__).parents[1].as_posix())
from wiki_nodes import MediaWikiClient, Link

log = logging.getLogger(__name__)


class LinkHandlingTestCase(TestCase):
    @patch('wiki_nodes.http.MediaWikiClient.interwiki_map', {'w': 'https://community.fandom.com/wiki/$1'})
    def test_interwiki_client(self, *mocks):
        root = MagicMock(site='kpop.fandom.com', _interwiki_map={'w': 'https://community.fandom.com/wiki/$1'})
        link = Link('[[w:c:kindie:test|Test]]', root)
        self.assertTrue(link.interwiki)
        self.assertEqual(link.iw_key_title, ('w:c:kindie', 'test'))

        client = MediaWikiClient(root.site)
        self.assertEqual(len(client.interwiki_map), 1)          # sanity check that patch worked as intended
        iw_client = client.interwiki_client('w:c:kindie')
        self.assertEqual(iw_client.host, 'kindie.fandom.com')


if __name__ == '__main__':
    main(exit=False, verbosity=2)

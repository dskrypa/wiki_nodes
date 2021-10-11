from os import environ

from .nodes import *
if environ.get('WIKI_NODES_NEW_PARSER', '0') == '1':
    from .parsing_new import as_node  # noqa
else:
    from .parsing import as_node  # noqa

del environ

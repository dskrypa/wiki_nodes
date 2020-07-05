#!/usr/bin/env python

from pathlib import Path
from setuptools import setup

project_root = Path(__file__).resolve().parent

with project_root.joinpath('readme.rst').open('r', encoding='utf-8') as f:
    long_description = f.read()

about = {}
with project_root.joinpath('wiki_nodes', '__version__.py').open('r', encoding='utf-8') as f:
    exec(f.read(), about)


setup(
    name=about['__title__'],
    version=about['__version__'],
    author=about['__author__'],
    author_email=about['__author_email__'],
    description=about['__description__'],
    long_description=long_description,
    url=about['__url__'],
    project_urls={'Source': about['__url__']},
    packages=['wiki_nodes'],
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8'     # Due to use of walrus operator
    ],
    python_requires='~=3.8',
    install_requires=[
        'requests_client @ git+git://github.com/dskrypa/requests_client',
        'db_cache @ git+git://github.com/dskrypa/db_cache',
        'wikitextparser',
        'requests'
    ],
    extras_require={'dev': ['pre-commit', 'ipython']},
)

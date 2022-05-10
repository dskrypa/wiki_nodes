#!/usr/bin/env python

from pathlib import Path
from setuptools import setup, find_packages

project_root = Path(__file__).resolve().parent
long_description = project_root.joinpath('readme.rst').read_text('utf-8')

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
    packages=find_packages(include='wiki_nodes*'),
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
    ],
    python_requires='~=3.9',
    install_requires=[
        'requests_client@ git+https://github.com/dskrypa/requests_client',
        'db_cache@ git+https://github.com/dskrypa/db_cache',
        'wikitextparser',
        'requests'
    ],
    extras_require={'dev': ['pre-commit', 'ipython']},
)

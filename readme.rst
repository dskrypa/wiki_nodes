Wiki Nodes
==========

Takes the next step with WikiText parsed by :mod:`wikitextparser` to process it into nodes based on what each section
contains, and provide a more top-down approach to traversing content on a given page.

This is still a work in process - some data types are not fully handled yet, and some aspects are subject to change.

Installation
------------

If installing on Linux, you should run the following first::

    $ sudo apt-get install python3-dev


Regardless of OS, setuptools is required::

    $ pip3 install setuptools


All of the other requirements are handled in setup.py, which will be run when you install like this::

    $ pip3 install git+git://github.com/dskrypa/wiki_nodes

"""
:author: Doug Skrypa
"""

__all__ = [
    'WikiError', 'WikiResponseError', 'PageMissingError', 'InvalidWikiError',
    'BadLinkError', 'NoLinkTarget', 'NoLinkSite', 'SiteDoesNotExist',
]


class WikiError(Exception):
    """Base exception for other wiki_nodes exceptions"""


class WikiResponseError(WikiError):
    """Exception to be raised when a wiki responds with an error"""


class PageMissingError(WikiError):
    """Exception to be raised if the requested page does not exist"""

    def __init__(self, title, host, extra=None):
        self.title = title
        self.host = host
        self.extra = extra

    def __str__(self):
        if self.extra:
            return f'No page found for {self.title!r} in {self.host} {self.extra}'
        return f'No page found for {self.title!r} in {self.host}'


class InvalidWikiError(WikiError):
    """Exception to be raised if the requested site does not exist"""


# region Link Exceptions


class BadLinkError(WikiError):
    """A link was missing a key field to be useful"""
    _problem = 'One or more key fields is missing'

    def __init__(self, link):
        self.link = link

    def __str__(self):
        return f'{self.__class__.__name__}: {self._problem} for link={self.link}'


class NoLinkTarget(BadLinkError):
    _problem = 'No link target title found'


class NoLinkSite(BadLinkError):
    _problem = 'No source site found'


class SiteDoesNotExist(BadLinkError):
    _problem = 'Site does not exist'


# endregion

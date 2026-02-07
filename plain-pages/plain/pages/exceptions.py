__all__ = ["PageNotFoundError", "RedirectPageError"]


class PageNotFoundError(Exception):
    pass


class RedirectPageError(Exception):
    pass

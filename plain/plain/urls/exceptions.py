from plain.http import NotFoundError404


class Resolver404(NotFoundError404):
    pass


class NoReverseMatch(Exception):
    pass

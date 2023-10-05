class DependencyError(Exception):
    pass


class UnknownVersionError(DependencyError):
    pass


class UnknownContentTypeError(DependencyError):
    pass


class VersionMismatchError(DependencyError):
    pass

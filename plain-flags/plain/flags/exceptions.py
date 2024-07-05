class FlagError(Exception):
    pass


class FlagDisabled(FlagError):
    pass


class FlagImportError(FlagError):
    pass

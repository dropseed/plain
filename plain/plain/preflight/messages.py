# Levels
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50


class CheckMessage:
    def __init__(self, level, msg, hint=None, obj=None, id=None):
        if not isinstance(level, int):
            raise TypeError("The first argument should be level.")
        self.level = level
        self.msg = msg
        self.hint = hint
        self.obj = obj
        self.id = id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and all(
            getattr(self, attr) == getattr(other, attr)
            for attr in ["level", "msg", "hint", "obj", "id"]
        )

    def __str__(self):
        try:
            from plain import models

            ModelBase = models.base.ModelBase
            using_db = True
        except ImportError:
            using_db = False
            ModelBase = object

        if self.obj is None:
            obj = "?"
        elif using_db and isinstance(self.obj, ModelBase):
            # We need to hardcode ModelBase and Field cases because its __str__
            # method doesn't return "applabel.modellabel" and cannot be changed.
            obj = self.obj._meta.label
        else:
            obj = str(self.obj)
        id = "(%s) " % self.id if self.id else ""
        hint = "\n\tHINT: %s" % self.hint if self.hint else ""
        return f"{obj}: {id}{self.msg}{hint}"

    def __repr__(self):
        return "<{}: level={!r}, msg={!r}, hint={!r}, obj={!r}, id={!r}>".format(
            self.__class__.__name__,
            self.level,
            self.msg,
            self.hint,
            self.obj,
            self.id,
        )

    def is_serious(self, level=ERROR):
        return self.level >= level

    def is_silenced(self):
        from plain.runtime import settings

        return self.id in settings.SILENCED_PREFLIGHT_CHECKS


class Debug(CheckMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(DEBUG, *args, **kwargs)


class Info(CheckMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(INFO, *args, **kwargs)


class Warning(CheckMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(WARNING, *args, **kwargs)


class Error(CheckMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(ERROR, *args, **kwargs)


class Critical(CheckMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(CRITICAL, *args, **kwargs)

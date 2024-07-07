from functools import partial

from plain.models.utils import make_model_tuple
from plain.signals.dispatch import Signal

class_prepared = Signal()


class ModelSignal(Signal):
    """
    Signal subclass that allows the sender to be lazily specified as a string
    of the `package_label.ModelName` form.
    """

    def _lazy_method(self, method, packages, receiver, sender, **kwargs):
        from plain.models.options import Options

        # This partial takes a single optional argument named "sender".
        partial_method = partial(method, receiver, **kwargs)
        if isinstance(sender, str):
            packages = packages or Options.default_packages
            packages.lazy_model_operation(partial_method, make_model_tuple(sender))
        else:
            return partial_method(sender)

    def connect(
        self, receiver, sender=None, weak=True, dispatch_uid=None, packages=None
    ):
        self._lazy_method(
            super().connect,
            packages,
            receiver,
            sender,
            weak=weak,
            dispatch_uid=dispatch_uid,
        )

    def disconnect(self, receiver=None, sender=None, dispatch_uid=None, packages=None):
        return self._lazy_method(
            super().disconnect, packages, receiver, sender, dispatch_uid=dispatch_uid
        )


pre_init = ModelSignal(use_caching=True)
post_init = ModelSignal(use_caching=True)

pre_save = ModelSignal(use_caching=True)
post_save = ModelSignal(use_caching=True)

pre_delete = ModelSignal(use_caching=True)
post_delete = ModelSignal(use_caching=True)

m2m_changed = ModelSignal(use_caching=True)

pre_migrate = Signal()
post_migrate = Signal()

from . import settings


class StaffToolbar:
    def __init__(self, *, request):
        # Callable or list of StaffToolbarLink
        self.links = settings.STAFFTOOLBAR_LINKS

        if callable(self.links):
            self.links = self.links(request)

        self.container_class = settings.STAFFTOOLBAR_CONTAINER_CLASS

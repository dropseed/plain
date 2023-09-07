from bolt.runtime import settings


class StaffToolbar:
    def __init__(self, request):
        self.links = settings.STAFFTOOLBAR_LINKS
        self.version = "dev"
        self.metadata = {
            "Request ID": request.unique_id,
        }

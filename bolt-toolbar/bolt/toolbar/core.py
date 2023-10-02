class Toolbar:
    def __init__(self, request):
        self.request = request
        self.version = "dev"
        self.metadata = {
            "Request ID": request.unique_id,
        }

    def should_render(self):
        if hasattr(self.request, "impersonator"):
            return self.request.impersonator.is_staff

        if self.request.user:
            return self.request.user.is_staff

        return False

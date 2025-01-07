class CsrfExemptViewMixin:
    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.request.csrf_exempt = True

from django.urls import reverse_lazy


class StaffToolbarLink:
    def __init__(self, *, text, url):
        self.text = text

        if not url.startswith("/") and not url.startswith("http"):
            self.url = reverse_lazy(url)
        else:
            self.url = url

import re

from plain import models


def _get_client_ip(request):
    if x_forwarded_for := request.headers.get("X-Forwarded-For"):
        return x_forwarded_for.split(",")[0].strip()
    else:
        return request.META.get("REMOTE_ADDR")


class Redirect(models.Model):
    from_pattern = models.CharField(max_length=255, unique=True)
    to_pattern = models.CharField(max_length=255)
    http_status = models.IntegerField(
        default=301
    )  # Default to permanent - could be choices?
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    order = models.IntegerField(default=0)
    enabled = models.BooleanField(default=True)
    is_regex = models.BooleanField(default=False)

    # query params?
    # logged in or not? auth not required necessarily...
    # headers?

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self):
        return f"{self.from_pattern}"

    def matches_request(self, request):
        """
        Decide whether a request matches this Redirect,
        automatically checking whether the pattern is path based or full URL based.
        """

        if self.from_pattern.startswith("http"):
            # Full url with query params
            url = request.build_absolute_uri()
        else:
            # Doesn't include query params or host
            url = request.path

        if self.is_regex:
            return re.match(self.from_pattern, url)
        else:
            return url == self.from_pattern

    def get_redirect_url(self, request):
        if not self.is_regex:
            return self.to_pattern

        # Replace any regex groups in the to_pattern
        if self.from_pattern.startswith("http"):
            url = request.build_absolute_uri()
        else:
            url = request.path

        return re.sub(self.from_pattern, self.to_pattern, url)


class RedirectLog(models.Model):
    redirect = models.ForeignKey(Redirect, on_delete=models.CASCADE)

    # The actuals that were used to redirect
    from_url = models.URLField()
    to_url = models.URLField()
    http_status = models.IntegerField(default=301)

    # Request metadata
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=512)
    referer = models.CharField(blank=True, max_length=512)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def from_redirect(cls, redirect, request):
        from_url = request.build_absolute_uri()
        to_url = redirect.get_redirect_url(request)

        if not to_url.startswith("http"):
            to_url = request.build_absolute_uri(to_url)

        if from_url == to_url:
            raise ValueError("Redirecting to the same URL")

        return cls.objects.create(
            redirect=redirect,
            from_url=from_url,
            to_url=to_url,
            http_status=redirect.http_status,
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            referer=request.headers.get("Referer"),
        )


class NotFoundLog(models.Model):
    url = models.URLField()

    # Request metadata
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=512)
    referer = models.CharField(blank=True, max_length=512)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def from_request(cls, request):
        return cls.objects.create(
            url=request.build_absolute_uri(),
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            referer=request.headers.get("Referer"),
        )

def auth(request):
    """
    Return context variables required by apps that use Django's authentication
    system.

    If there is no 'user' attribute in the request, use AnonymousUser (from
    django.contrib.auth).
    """
    if hasattr(request, "user"):
        user = request.user
    else:
        from django.contrib.auth.models import AnonymousUser

        user = AnonymousUser()

    return {
        "user": user,
    }

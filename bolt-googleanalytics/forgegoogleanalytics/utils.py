def user_id_from_request(request):
    # Analytics will be tied to the impersonator if we are one
    user = getattr(request, "impersonator", request.user)
    if user.is_authenticated:
        return user_id(user)
    return None


def user_id(user):
    return user.pk

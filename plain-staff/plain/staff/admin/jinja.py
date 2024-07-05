from .views.registry import registry


def get_admin_model_detail_url(obj):
    return registry.get_model_detail_url(obj)


filters = {
    "get_admin_model_detail_url": get_admin_model_detail_url,
}

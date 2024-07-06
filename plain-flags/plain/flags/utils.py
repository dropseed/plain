from typing import Any

from plain import models


def coerce_key(key: Any) -> str:
    """
    Converts a flag key to a string for storage in the DB
    (special handling of model instances)
    """
    if isinstance(key, str):
        return key

    if isinstance(key, models.Model):
        return f"{key._meta.package_label}.{key._meta.model_name}:{key.pk}"

    return str(key)

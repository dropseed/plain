class GlobalID:
    """A global identifier for a model instance."""

    @staticmethod
    def from_instance(instance):
        return f"gid://{instance._meta.package_label}/{instance._meta.model_name}/{instance.pk}"

    @staticmethod
    def to_instance(s):
        if not s.startswith("gid://"):
            raise ValueError("Invalid GlobalID string")
        package, model, pk = s[6:].split("/")
        from bolt.packages import packages

        model = packages.get_model(package, model)
        return model.objects.get(pk=pk)

    @staticmethod
    def is_gid(x):
        if not isinstance(x, str):
            return False
        return x.startswith("gid://")

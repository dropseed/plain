# Register a model to the relevant packages registry
def register_model(model_class):
    model_class._meta.packages_registry.register_model(
        model_class._meta.package_label, model_class
    )
    return model_class

import importlib


def forgepackage_installed(name: str) -> bool:
    try:
        importlib.import_module(f"forge{name}")
        return True
    except ImportError as e:
        return False

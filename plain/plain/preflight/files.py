from pathlib import Path

from plain.runtime import settings

from . import Error, register


@register
def check_setting_file_upload_temp_dir(package_configs, **kwargs):
    setting = getattr(settings, "FILE_UPLOAD_TEMP_DIR", None)
    if setting and not Path(setting).is_dir():
        return [
            Error(
                f"The FILE_UPLOAD_TEMP_DIR setting refers to the nonexistent "
                f"directory '{setting}'.",
                id="files.E001",
            ),
        ]
    return []

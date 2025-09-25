from pathlib import Path

from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult


@register_check("files.upload_temp_dir")
class CheckSettingFileUploadTempDir(PreflightCheck):
    """Validates that the FILE_UPLOAD_TEMP_DIR setting points to an existing directory."""

    def run(self):
        setting = settings.FILE_UPLOAD_TEMP_DIR
        if setting and not Path(setting).is_dir():
            return [
                PreflightResult(
                    f"The FILE_UPLOAD_TEMP_DIR setting refers to the nonexistent "
                    f"directory '{setting}'.",
                    id="files.upload_temp_dir_nonexistent",
                )
            ]
        return []

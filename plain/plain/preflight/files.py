from __future__ import annotations

from pathlib import Path

from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult


@register_check("files.upload_temp_dir")
class CheckSettingFileUploadTempDir(PreflightCheck):
    """Validates that the FILE_UPLOAD_TEMP_DIR setting points to an existing directory."""

    def run(self) -> list[PreflightResult]:
        setting = settings.FILE_UPLOAD_TEMP_DIR
        if setting and not Path(setting).is_dir():
            return [
                PreflightResult(
                    fix=f"FILE_UPLOAD_TEMP_DIR points to nonexistent directory '{setting}'. Create the directory or update the setting.",
                    id="files.upload_temp_dir_nonexistent",
                )
            ]
        return []

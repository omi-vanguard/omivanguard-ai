"""
Omi Vanguard AI
Configuration Manager
Version: 2.1.0

Centralized configuration for Excel and Google Sheets operations.
"""

from __future__ import annotations

import os
import tempfile

from pathlib import Path
from typing import Any, Optional

try:
    from .models import EngineConfig
    from .errors import ConfigurationError

except ImportError:
    from models import EngineConfig
    from errors import ConfigurationError


# =========================================================
# ENVIRONMENT PARSING
# =========================================================

def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip().lower()

    if value in {"true", "1", "yes", "on"}:
        return True

    if value in {"false", "0", "no", "off"}:
        return False

    raise ConfigurationError(
        f"Invalid boolean environment variable: {name}"
    )


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be an integer."
        ) from exc


def _get_string(name: str, default: str) -> str:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip()


# =========================================================
# CONFIGURATION VALIDATION
# =========================================================

def validate_config(config: EngineConfig) -> EngineConfig:
    if not isinstance(config, EngineConfig):
        raise ConfigurationError(
            "Configuration must be an EngineConfig instance."
        )

    if config.max_file_size_mb <= 0:
        raise ConfigurationError(
            "max_file_size_mb must be greater than zero."
        )

    if config.timeout_seconds <= 0:
        raise ConfigurationError(
            "timeout_seconds must be greater than zero."
        )

    if not config.default_date_format:
        raise ConfigurationError(
            "default_date_format cannot be empty."
        )

    if not config.default_encoding:
        raise ConfigurationError(
            "default_encoding cannot be empty."
        )

    if not isinstance(config.options, dict):
        raise ConfigurationError(
            "options must be a dictionary."
        )

    if (
        config.temporary_directory is not None
        and not isinstance(
            config.temporary_directory,
            (str, Path),
        )
    ):
        raise ConfigurationError(
            "temporary_directory must be a path or None."
        )

    return config


# =========================================================
# CONFIGURATION LOADER
# =========================================================

def load_config(
    overrides: Optional[dict[str, Any]] = None,
) -> EngineConfig:
    """
    Load configuration from environment variables.

    Optional overrides take priority over environment values.
    """

    config = EngineConfig(
        preserve_original=_get_bool(
            "OMI_PRESERVE_ORIGINAL", True
        ),

        create_backup=_get_bool(
            "OMI_CREATE_BACKUP", True
        ),

        verify_output=_get_bool(
            "OMI_VERIFY_OUTPUT", True
        ),

        allow_macros=_get_bool(
            "OMI_ALLOW_MACROS", False
        ),

        read_only=_get_bool(
            "OMI_READ_ONLY", False
        ),

        data_only=_get_bool(
            "OMI_DATA_ONLY", False
        ),

        max_file_size_mb=_get_int(
            "OMI_MAX_FILE_SIZE_MB", 500
        ),

        timeout_seconds=_get_int(
            "OMI_TIMEOUT_SECONDS", 300
        ),

        default_date_format=_get_string(
            "OMI_DEFAULT_DATE_FORMAT", "yyyy-mm-dd"
        ),

        default_encoding=_get_string(
            "OMI_DEFAULT_ENCODING", "utf-8"
        ),

        enable_operation_history=_get_bool(
            "OMI_ENABLE_OPERATION_HISTORY", True
        ),

        enable_rollback=_get_bool(
            "OMI_ENABLE_ROLLBACK", True
        ),

        strict_validation=_get_bool(
            "OMI_STRICT_VALIDATION", True
        ),

        temporary_directory=os.getenv(
            "OMI_TEMPORARY_DIRECTORY"
        ),

        options={},
    )

    # Apply explicitly supplied overrides.
    if overrides:
        if not isinstance(overrides, dict):
            raise ConfigurationError(
                "Configuration overrides must be a dictionary."
            )

        allowed_fields = {
            "preserve_original",
            "create_backup",
            "verify_output",
            "allow_macros",
            "read_only",
            "data_only",
            "max_file_size_mb",
            "timeout_seconds",
            "default_date_format",
            "default_encoding",
            "enable_operation_history",
            "enable_rollback",
            "strict_validation",
            "temporary_directory",
            "options",
        }

        unknown_fields = set(overrides) - allowed_fields

        if unknown_fields:
            raise ConfigurationError(
                f"Unknown configuration options: "
                f"{sorted(unknown_fields)}"
            )

        for key, value in overrides.items():
            setattr(config, key, value)

    return validate_config(config)


# =========================================================
# TEMPORARY DIRECTORY
# =========================================================

def get_temporary_directory(
    config: Optional[EngineConfig] = None,
) -> Path:
    """
    Return the configured temporary directory.

    Creates the directory if it does not exist.
    """

    config = config or load_config()
    validate_config(config)

    if config.temporary_directory:
        directory = Path(
            config.temporary_directory
        ).expanduser()

    else:
        directory = (
            Path(tempfile.gettempdir())
            / "omi_vanguard"
        )

    try:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    except OSError as exc:
        raise ConfigurationError(
            f"Unable to prepare temporary directory: {exc}"
        ) from exc

    return directory


# =========================================================
# DEFAULT CONFIGURATION
# =========================================================

DEFAULT_CONFIG = load_config()

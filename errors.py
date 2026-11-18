"""Centralized exceptions for Omi Vanguard Excel Engine."""


class OmiExcelError(Exception):
    """Base exception for all engine errors."""


class WorkbookError(OmiExcelError):
    """Workbook operation failed."""


class WorksheetError(OmiExcelError):
    """Worksheet operation failed."""


class CellError(OmiExcelError):
    """Cell operation failed."""


class FormulaError(OmiExcelError):
    """Formula operation failed."""


class FormattingError(OmiExcelError):
    """Formatting operation failed."""


class DataProcessingError(OmiExcelError):
    """Data processing operation failed."""


class ChartError(OmiExcelError):
    """Chart operation failed."""


class ValidationError(OmiExcelError):
    """Input or output validation failed."""


class SecurityError(OmiExcelError):
    """Security policy violation."""


class IntegrationError(OmiExcelError):
    """External integration failed."""


class UnsupportedFeatureError(OmiExcelError):
    """Requested feature is not supported by the active backend."""


class ConfigurationError(OmiExcelError):
    """Engine configuration is invalid."""


class RecoveryError(OmiExcelError):
    """Backup, rollback, or recovery operation failed."""

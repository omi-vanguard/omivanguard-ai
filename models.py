"""Core data models for Omi Vanguard AI Spreadsheet Engine.

Shared models for Microsoft Excel and Google Sheets.
Supports task execution, workbook operations, validation,
analysis, integrations, recovery and audit history.
"""

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import base64


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_plain_data(value: Any) -> Any:
    """Convert supported Python values and models into JSON-safe data."""

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }

    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_plain_data(getattr(value, item.name))
            for item in fields(value)
        }

    if isinstance(value, dict):
        return {
            str(key): to_plain_data(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [to_plain_data(item) for item in value]

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise TypeError(
        f"Unsupported serialization type: {type(value).__name__}"
    )


# ============================================================
# ENUMS
# ============================================================

class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    PARTIAL = "partial"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SpreadsheetPlatform(str, Enum):
    EXCEL = "excel"
    GOOGLE_SHEETS = "google_sheets"


class FileFormat(str, Enum):
    XLSX = "xlsx"
    XLSM = "xlsm"
    XLS = "xls"
    XLSB = "xlsb"
    CSV = "csv"
    TSV = "tsv"
    ODS = "ods"
    UNKNOWN = "unknown"


class FeatureSupport(str, Enum):
    NATIVE = "native"
    INTEGRATION = "integration_required"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class OperationType(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    FORMAT = "format"
    ANALYZE = "analyze"
    IMPORT = "import"
    EXPORT = "export"
    AUTOMATE = "automate"
    OTHER = "other"


# ============================================================
# VALIDATION AND DIAGNOSTICS
# ============================================================

@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    location: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now)

    @property
    def errors(self):
        return [
            issue for issue in self.issues
            if issue.severity in (Severity.ERROR, Severity.CRITICAL)
        ]

    @property
    def warnings(self):
        return [
            issue for issue in self.issues
            if issue.severity == Severity.WARNING
        ]


@dataclass
class DiagnosticReport:
    platform: SpreadsheetPlatform
    success: bool
    checks: Dict[str, Any] = field(default_factory=dict)
    issues: List[ValidationIssue] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)


# ============================================================
# WORKBOOK AND WORKSHEET
# ============================================================

@dataclass
class WorkbookMetadata:
    title: Optional[str] = None
    subject: Optional[str] = None
    creator: Optional[str] = None
    description: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    category: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    custom_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SheetReport:
    name: str
    index: int
    max_row: int = 0
    max_column: int = 0
    state: str = "visible"
    has_data: bool = False
    tables: List[str] = field(default_factory=list)
    chart_count: int = 0
    formula_count: int = 0
    merged_ranges: List[str] = field(default_factory=list)
    protected: bool = False


@dataclass
class WorkbookReport:
    file_path: str
    file_format: FileFormat
    sheet_count: int
    sheets: List[SheetReport] = field(default_factory=list)
    file_size: int = 0
    metadata: WorkbookMetadata = field(default_factory=WorkbookMetadata)
    is_macro_enabled: bool = False
    is_protected: bool = False
    calculation_mode: Optional[str] = None
    defined_names: List[str] = field(default_factory=list)
    external_links_count: int = 0
    warnings: List[str] = field(default_factory=list)
    inspected_at: str = field(default_factory=utc_now)


@dataclass
class WorksheetInfo:
    name: str
    index: int
    state: str = "visible"
    row_count: int = 0
    column_count: int = 0
    tab_color: Optional[str] = None
    protected: bool = False
    right_to_left: bool = False


# ============================================================
# CELLS AND RANGES
# ============================================================

@dataclass
class CellAddress:
    sheet_name: str
    coordinate: str
    row: Optional[int] = None
    column: Optional[int] = None


@dataclass
class CellData:
    address: CellAddress
    value: Any = None
    formula: Optional[str] = None
    data_type: Optional[str] = None
    number_format: Optional[str] = None
    style: Dict[str, Any] = field(default_factory=dict)
    hyperlink: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class RangeData:
    sheet_name: str
    cell_range: str
    values: List[List[Any]] = field(default_factory=list)
    formulas: List[List[Optional[str]]] = field(default_factory=list)
    row_count: int = 0
    column_count: int = 0


@dataclass
class MergedRangeInfo:
    sheet_name: str
    cell_range: str


# ============================================================
# FORMULAS AND CALCULATION
# ============================================================

@dataclass
class FormulaInfo:
    formula: str
    sheet_name: str
    cell: str
    cached_value: Any = None
    calculation_engine: Optional[str] = None
    is_valid: Optional[bool] = None
    dependencies: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    is_array_formula: bool = False
    is_dynamic_array: bool = False


@dataclass
class CalculationResult:
    success: bool
    formula: str
    value: Any = None
    error: Optional[str] = None
    engine: Optional[str] = None
    calculated_at: str = field(default_factory=utc_now)


@dataclass
class FormulaDependency:
    source_sheet: str
    source_cell: str
    dependent_sheet: str
    dependent_cell: str


@dataclass
class CalculationSettings:
    mode: str = "automatic"
    iterate: bool = False
    iterate_count: int = 100
    iterate_delta: float = 0.001
    full_recalculation: bool = False


# ============================================================
# TABLES, CHARTS AND PIVOT TABLES
# ============================================================

@dataclass
class TableInfo:
    name: str
    sheet_name: str
    cell_range: str
    columns: List[str] = field(default_factory=list)
    style_name: Optional[str] = None
    totals_row: bool = False
    autofilter_enabled: bool = True


@dataclass
class ChartInfo:
    name: str
    chart_type: str
    sheet_name: str
    data_range: str
    anchor: Optional[str] = None
    title: Optional[str] = None
    categories_range: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PivotField:
    name: str
    orientation: str
    position: Optional[int] = None
    aggregation: Optional[str] = None
    number_format: Optional[str] = None


@dataclass
class PivotTableInfo:
    name: str
    source_sheet: str
    source_range: str
    destination_sheet: str
    destination_cell: str
    row_fields: List[str] = field(default_factory=list)
    column_fields: List[str] = field(default_factory=list)
    value_fields: List[PivotField] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    cache_id: Optional[str] = None
    slicers: List[str] = field(default_factory=list)
    refresh_status: Optional[str] = None


@dataclass
class SlicerInfo:
    name: str
    pivot_table_name: str
    field_name: str
    selected_items: List[str] = field(default_factory=list)


# ============================================================
# FORMATTING AND VALIDATION RULES
# ============================================================

@dataclass
class FormattingOptions:
    font: Dict[str, Any] = field(default_factory=dict)
    fill: Dict[str, Any] = field(default_factory=dict)
    border: Dict[str, Any] = field(default_factory=dict)
    alignment: Dict[str, Any] = field(default_factory=dict)
    number_format: Optional[str] = None
    protection: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConditionalFormatRule:
    rule_type: str
    formula: Optional[str] = None
    operator: Optional[str] = None
    style: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataValidationRule:
    validation_type: str
    operator: Optional[str] = None
    formula1: Optional[str] = None
    formula2: Optional[str] = None
    allow_blank: bool = True
    error_message: Optional[str] = None
    prompt_message: Optional[str] = None


# ============================================================
# DATA PROCESSING AND ANALYSIS
# ============================================================

@dataclass
class DataAnalysisResult:
    success: bool
    source_sheet: str
    source_range: str
    row_count: int = 0
    column_count: int = 0
    statistics: Dict[str, Any] = field(default_factory=dict)
    insights: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class DataCleaningReport:
    rows_examined: int = 0
    duplicates_found: int = 0
    duplicates_removed: int = 0
    empty_cells_found: int = 0
    values_changed: int = 0
    issues: List[str] = field(default_factory=list)


@dataclass
class ImportExportResult:
    success: bool
    source_path: Optional[str] = None
    output_path: Optional[str] = None
    source_format: Optional[FileFormat] = None
    output_format: Optional[FileFormat] = None
    rows_processed: int = 0
    warnings: List[str] = field(default_factory=list)


@dataclass
class DataConnectionInfo:
    name: str
    connection_type: str
    source: Optional[str] = None
    refresh_enabled: bool = False
    last_refreshed: Optional[str] = None
    status: Status = Status.PENDING
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryInfo:
    name: str
    source: Optional[str] = None
    transformation_steps: List[Dict[str, Any]] = field(default_factory=list)
    output_sheet: Optional[str] = None
    refresh_status: Status = Status.PENDING


@dataclass
class ForecastResult:
    success: bool
    method: str
    predictions: List[Any] = field(default_factory=list)
    confidence_intervals: List[Any] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ============================================================
# AI TASK PLANNING AND EXECUTION
# ============================================================

@dataclass
class OperationResult:
    success: bool
    operation: str
    message: str = ""
    output_path: Optional[str] = None
    data: Any = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    operation_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: str = field(default_factory=utc_now)


@dataclass
class TaskStep:
    step_id: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: Status = Status.PENDING
    result: Optional[OperationResult] = None
    dependencies: List[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 0


@dataclass
class TaskPlan:
    task_id: str
    description: str
    steps: List[TaskStep] = field(default_factory=list)
    status: Status = Status.PENDING
    created_at: str = field(default_factory=utc_now)
    completed_at: Optional[str] = None
    requires_confirmation: bool = False


@dataclass
class TaskExecutionReport:
    task_id: str
    status: Status
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    results: List[OperationResult] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ============================================================
# BACKUP, RECOVERY, UNDO AND REDO
# ============================================================

@dataclass
class BackupInfo:
    backup_id: str
    original_path: str
    backup_path: str
    created_at: str = field(default_factory=utc_now)
    checksum: Optional[str] = None
    verified: bool = False
    size_bytes: Optional[int] = None


@dataclass
class RestorePoint:
    restore_point_id: str
    backup_id: str
    description: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class HistoryEntry:
    operation_id: str
    operation: str
    description: str
    timestamp: str = field(default_factory=utc_now)
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    status: Status = Status.SUCCESS
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UndoRedoRecord:
    operation_id: str
    action: str
    before_state: Dict[str, Any] = field(default_factory=dict)
    after_state: Dict[str, Any] = field(default_factory=dict)
    reversible: bool = True
    timestamp: str = field(default_factory=utc_now)


@dataclass
class FileIntegrityReport:
    file_path: str
    valid: bool
    checksum: Optional[str] = None
    file_size: Optional[int] = None
    issues: List[str] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now)


# ============================================================
# SECURITY AND PERMISSIONS
# ============================================================

@dataclass
class PermissionInfo:
    principal: str
    role: str
    can_read: bool = True
    can_write: bool = False
    can_share: bool = False
    can_delete: bool = False


@dataclass
class ProtectionInfo:
    protected: bool = False
    protection_type: Optional[str] = None
    allowed_operations: List[str] = field(default_factory=list)
    password_protected: bool = False


@dataclass
class AuditRecord:
    event_id: str
    actor: str
    action: str
    resource: str
    timestamp: str = field(default_factory=utc_now)
    outcome: Status = Status.SUCCESS
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# PLATFORM INTEGRATIONS AND COMPATIBILITY
# ============================================================

@dataclass
class IntegrationStatus:
    name: str
    available: bool
    platform: SpreadsheetPlatform
    version: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    message: Optional[str] = None


@dataclass
class FeatureCapability:
    feature_name: str
    platform: SpreadsheetPlatform
    support: FeatureSupport
    backend: Optional[str] = None
    requirements: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


@dataclass
class CompatibilityReport:
    platform: SpreadsheetPlatform
    application_version: Optional[str] = None
    supported_features: List[str] = field(default_factory=list)
    partially_supported_features: List[str] = field(default_factory=list)
    unsupported_features: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class EngineConfig:
    preserve_original: bool = True
    create_backup: bool = True
    verify_output: bool = True
    allow_macros: bool = False
    read_only: bool = False
    data_only: bool = False
    max_file_size_mb: int = 500
    timeout_seconds: int = 300
    default_date_format: str = "yyyy-mm-dd"
    default_encoding: str = "utf-8"
    enable_operation_history: bool = True
    enable_rollback: bool = True
    strict_validation: bool = True
    temporary_directory: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)

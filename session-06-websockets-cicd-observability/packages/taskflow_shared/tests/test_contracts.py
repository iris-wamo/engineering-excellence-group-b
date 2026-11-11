"""Tests for contracts, enums, and constants in taskflow_shared."""

from datetime import UTC, datetime

from taskflow_shared.contracts import HEADER_IMPORT_ID, RawImportRecord
from taskflow_shared.enums import ImportStatus


def test_import_status_enum_values() -> None:
    assert ImportStatus.PENDING == "PENDING"
    assert ImportStatus.SUCCESS == "SUCCESS"
    assert ImportStatus.FAILED == "FAILED"


def test_header_import_id_constant() -> None:
    assert HEADER_IMPORT_ID == "X-Import-ID"


def test_raw_import_record_contract() -> None:
    now = datetime.now(UTC)
    record = RawImportRecord(
        import_id="6701a2b3c4d5e6f7a8b9c0d1",
        status=ImportStatus.SUCCESS,
        error_details=None,
        created_at=now,
        updated_at=now,
    )
    assert record.import_id == "6701a2b3c4d5e6f7a8b9c0d1"
    assert record.status == "SUCCESS"
    assert record.error_details is None


def test_batch_import_record_contract() -> None:
    from taskflow_shared.contracts import BatchImportRecord

    batch = BatchImportRecord(total=5, succeeded=4, failed=1)
    assert batch.total == 5
    assert batch.succeeded == 4
    assert batch.failed == 1

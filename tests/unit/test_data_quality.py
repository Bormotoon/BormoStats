from __future__ import annotations

import json
from datetime import UTC, date, datetime

from workers.app.utils.data_quality import DataQualityIssue


def test_issue_meta_is_json_serializable_with_dates() -> None:
    issue = DataQualityIssue(
        check="missing_days",
        summary="no rows",
        failures=1,
        samples=[{"day": date(2026, 10, 4), "updated_at": datetime(2026, 10, 4, tzinfo=UTC)}],
    )
    meta = issue.as_meta()
    assert meta["samples"] == [{"day": "2026-10-04", "updated_at": "2026-10-04T00:00:00+00:00"}]
    json.dumps(meta)

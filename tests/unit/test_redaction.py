from __future__ import annotations

from collectors.common.redaction import redact_mapping


def test_redact_mapping_masks_dashed_header_names() -> None:
    headers = {
        "Client-Id": "2354670",
        "Api-Key": "4f0e02fb-0000-0000-0000-50bf5ebce649",
        "Authorization": "eyJhbGciOiJFUzI1NiJ9.payload.signature",
        "Content-Type": "application/json",
    }

    redacted = redact_mapping(headers)

    assert redacted["Api-Key"] == "4f0e***e649"
    assert redacted["Authorization"].startswith("eyJh***")
    assert "payload" not in redacted["Authorization"]
    assert redacted["Content-Type"] == "application/json"

"""Tests for NHTSA JSON complaint client parsing."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from signalwarn.nhtsa import NHTSAClient, _parse_date, _record_to_complaint


def test_record_to_complaint_reads_nested_products():
    """Live complaintsByVehicle nests make/model/year under products[]."""
    record = {
        "odiNumber": 11767936,
        "manufacturer": "Kia America, Inc.",
        "crash": False,
        "fire": False,
        "numberOfInjuries": 0,
        "numberOfDeaths": 0,
        "dateOfIncident": "09/18/2026",
        "dateComplaintFiled": "09/30/2026",
        "vin": "5XYRG4LC0MG",
        "components": "POWER TRAIN",
        "summary": "Transmission hesitation while merging.",
        "make": None,
        "model": None,
        "modelYear": None,
        "products": [
            {
                "type": "Vehicle",
                "productYear": "2021",
                "productMake": "KIA",
                "productModel": "SORENTO",
                "manufacturer": "Kia America, Inc.",
            }
        ],
    }
    c = _record_to_complaint(record)
    assert c is not None
    assert c.odi_number == "11767936"
    assert c.make == "KIA"
    assert c.model == "SORENTO"
    assert c.model_year == 2021
    assert c.date_complaint_filed == date(2026, 9, 30)
    assert c.date_of_incident == date(2026, 9, 18)
    assert c.component_raw == "POWER TRAIN"
    assert c.manufacturer == "Kia America, Inc."


def test_record_to_complaint_prefers_top_level_fields():
    """Top-level make/model/year still win when present (backward compatible)."""
    record = {
        "odiNumber": "10001",
        "make": "FORD",
        "model": "F-150",
        "modelYear": 2023,
        "manufacturer": "Ford Motor Company",
        "components": "ENGINE",
        "dateComplaintFiled": "2024-09-15T00:00:00.000Z",
        "products": [
            {
                "type": "Vehicle",
                "productYear": "2018",
                "productMake": "KIA",
                "productModel": "SORENTO",
            }
        ],
    }
    c = _record_to_complaint(record)
    assert c is not None
    assert c.make == "FORD"
    assert c.model == "F-150"
    assert c.model_year == 2023
    assert c.date_complaint_filed == date(2024, 9, 15)


def test_record_to_complaint_returns_none_without_vehicle_identity():
    assert _record_to_complaint({"odiNumber": "1"}) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("09/30/2026", date(2026, 9, 30)),
        ("2024-09-15T00:00:00.000Z", date(2024, 9, 15)),
        ("20240115", date(2024, 1, 15)),
        (None, None),
        ("", None),
    ],
)
def test_parse_date_formats(raw, expected):
    assert _parse_date(raw) == expected


def test_complaints_for_vehicle_treats_400_empty_as_no_results():
    client = NHTSAClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "count": 0,
        "message": "Results returned successfully",
        "results": [],
    }
    client._client.get = MagicMock(return_value=mock_resp)

    assert client.complaints_for_vehicle("CHEVROLET", "SILVERADO", 2018) == []
    mock_resp.raise_for_status.assert_not_called()
    client.close()


def test_complaints_for_vehicle_still_raises_on_real_errors():
    client = NHTSAClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=MagicMock(),
        response=mock_resp,
    )
    client._client.get = MagicMock(return_value=mock_resp)

    with pytest.raises(httpx.HTTPStatusError):
        client.complaints_for_vehicle("FORD", "F-150", 2020)
    client.close()

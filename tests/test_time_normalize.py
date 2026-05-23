from datetime import date, datetime

import pytest

from src.transform.time_normalize import (
    normalize_region,
    parse_kma_hourly_timestamp,
    parse_trade_date,
    parse_trade_hour,
)


class TestParseTradeDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("20260523", date(2026, 5, 23)),
            ("2026-05-23", date(2026, 5, 23)),
            (date(2026, 5, 23), date(2026, 5, 23)),
            (datetime(2026, 5, 23, 14, 0), date(2026, 5, 23)),
        ],
    )
    def test_accepted_formats(self, raw, expected):
        assert parse_trade_date(raw) == expected

    @pytest.mark.parametrize("bad", ["", "not-a-date", "2026/05/23"])
    def test_rejects(self, bad):
        with pytest.raises(ValueError):
            parse_trade_date(bad)


class TestParseTradeHour:
    @pytest.mark.parametrize(
        "raw,expected",
        [("6", 6), ("06", 6), (6, 6), (24, 24), (1, 1)],
    )
    def test_accepted(self, raw, expected):
        assert parse_trade_hour(raw) == expected

    @pytest.mark.parametrize("bad", [0, 25, -1, "", None])
    def test_rejects(self, bad):
        with pytest.raises(ValueError):
            parse_trade_hour(bad)


class TestNormalizeRegion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("육지", "land"),
            ("LAND", "land"),
            ("제주", "jeju"),
            ("Jeju", "jeju"),
            (None, "land"),
            ("1", "land"),
            ("2", "jeju"),
        ],
    )
    def test_basic_mapping(self, raw, expected):
        assert normalize_region(raw) == expected

    def test_unknown_passes_through(self):
        # Unknown labels survive (lowercased) so they show up in queries instead of being silently dropped.
        assert normalize_region("foo") == "foo"


class TestParseKmaHourlyTimestamp:
    def test_dash_format(self):
        assert parse_kma_hourly_timestamp("2026-05-23 14:00") == datetime(2026, 5, 23, 14, 0)

    def test_compact_format(self):
        assert parse_kma_hourly_timestamp("202605231400") == datetime(2026, 5, 23, 14, 0)

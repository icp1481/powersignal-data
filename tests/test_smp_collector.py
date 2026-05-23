from datetime import date

import httpx
import respx
from sqlalchemy import select

from src.collectors.smp import SmpCollector
from src.storage.db import session_scope
from src.storage.models import IngestionRun, SmpHourly


def _payload(items: list[dict]) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {"items": {"item": items}, "pageNo": 1, "numOfRows": len(items)},
        }
    }


def test_smp_collector_persists_rows_per_region():
    items = [
        {"tradeDt": "20260523", "tradeHh": 1, "region": "육지", "smp": "110.5", "demandFcst": 60000},
        {"tradeDt": "20260523", "tradeHh": 1, "region": "제주", "smp": "120.0", "demandFcst": 1500},
        {"tradeDt": "20260523", "tradeHh": 2, "region": "육지", "smp": "108.2", "demandFcst": 58000},
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(host="apis.data.go.kr").mock(
            return_value=httpx.Response(200, json=_payload(items))
        )
        with SmpCollector() as c:
            inserted = c.run()

    assert inserted == 3
    with session_scope() as s:
        rows = s.execute(select(SmpHourly).order_by(SmpHourly.trade_hour, SmpHourly.region)).scalars().all()
        assert len(rows) == 3
        land_hour1 = next(r for r in rows if r.trade_hour == 1 and r.region == "land")
        assert land_hour1.trade_date == date(2026, 5, 23)
        assert land_hour1.smp_krw_per_kwh == 110.5
        assert land_hour1.demand_forecast_mw == 60000

        # ingestion_run row created
        runs = s.execute(select(IngestionRun)).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].rows_inserted == 3


def test_smp_collector_is_idempotent_via_upsert():
    items = [
        {"tradeDt": "20260523", "tradeHh": 1, "region": "육지", "smp": "100", "demandFcst": 50000},
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(host="apis.data.go.kr").mock(
            return_value=httpx.Response(200, json=_payload(items))
        )
        with SmpCollector() as c:
            c.run()
        # update value, run again
        items[0]["smp"] = "105"
        router.get(host="apis.data.go.kr").mock(
            return_value=httpx.Response(200, json=_payload(items))
        )
        with SmpCollector() as c:
            c.run()

    with session_scope() as s:
        rows = s.execute(select(SmpHourly)).scalars().all()
        assert len(rows) == 1  # upsert, not duplicate
        assert rows[0].smp_krw_per_kwh == 105.0


def test_smp_collector_skips_combined_region_row_with_warning():
    """If the portal returns a row that bundles both regions in one payload, we skip it
    (and expect fetch() to be updated to split). This guards against silent data corruption."""
    items = [{"tradeDt": "20260523", "tradeHh": 1, "landSmp": 100, "jejuSmp": 110}]
    with respx.mock(assert_all_called=False) as router:
        router.get(host="apis.data.go.kr").mock(
            return_value=httpx.Response(200, json=_payload(items))
        )
        with SmpCollector() as c:
            inserted = c.run()
    assert inserted == 0

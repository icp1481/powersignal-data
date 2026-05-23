"""Client-level tests: pagination, error coding, raw persistence.

Uses respx to mock httpx. No real network."""
from __future__ import annotations

import httpx
import pytest
import respx

from src.clients.data_go_kr import (
    DataGoKrClient,
    DataGoKrError,
    DataGoKrRateLimitError,
)


def _ok(items: list[dict]) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {
                "pageNo": 1,
                "numOfRows": len(items),
                "totalCount": len(items),
                "items": {"item": items},
            },
        }
    }


def _err(code: str, msg: str) -> dict:
    return {"response": {"header": {"resultCode": code, "resultMsg": msg}}}


URL = "https://example.test/api/foo"


def test_get_returns_parsed_body_and_persists_raw(tmp_path):
    with respx.mock(assert_all_called=True) as router:
        router.get(URL).mock(
            return_value=httpx.Response(200, json=_ok([{"k": "v"}]))
        )
        with DataGoKrClient(service_key="K", raw_dir=tmp_path) as c:
            body = c.get(URL, {"pageNo": 1, "numOfRows": 10}, dataset_id="D1")
    assert body["response"]["header"]["resultCode"] == "00"
    # raw file should have been written under D1/<yyyymmdd>/...
    raw_files = list((tmp_path / "D1").rglob("*.json"))
    assert len(raw_files) == 1


def test_pagination_stops_on_short_page(tmp_path):
    with respx.mock(assert_all_called=False) as router:
        page1 = httpx.Response(
            200, json=_ok([{"i": i} for i in range(10)])
        )
        page2 = httpx.Response(200, json=_ok([{"i": 10}]))  # short → terminator
        route = router.get(URL).mock(side_effect=[page1, page2])

        with DataGoKrClient(service_key="K", raw_dir=tmp_path) as c:
            items = list(
                c.paginate(
                    URL,
                    {"pageNo": 1, "numOfRows": 10},
                    dataset_id="D1",
                )
            )
    assert len(items) == 11
    assert route.call_count == 2


def test_pagination_handles_single_dict_item(tmp_path):
    """Portal sometimes returns items.item as a dict, not a list."""
    body = _ok([{"only": "one"}])
    body["response"]["body"]["items"] = {"item": {"only": "one"}}  # collapse to single dict
    with respx.mock() as router:
        router.get(URL).mock(return_value=httpx.Response(200, json=body))
        with DataGoKrClient(service_key="K", raw_dir=tmp_path) as c:
            items = list(c.paginate(URL, {"pageNo": 1, "numOfRows": 10}, dataset_id="D1"))
    assert items == [{"only": "one"}]


def test_portal_error_22_raises_rate_limit(tmp_path):
    with respx.mock() as router:
        router.get(URL).mock(
            return_value=httpx.Response(200, json=_err("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS"))
        )
        with DataGoKrClient(service_key="K", raw_dir=tmp_path) as c:
            with pytest.raises(DataGoKrRateLimitError):
                c.get(URL, {}, dataset_id="D1")


def test_portal_non_retryable_error_raises_immediately(tmp_path):
    with respx.mock() as router:
        # Code "30" is a non-retryable error like SERVICE_KEY_IS_NOT_REGISTERED
        route = router.get(URL).mock(
            return_value=httpx.Response(200, json=_err("30", "SERVICE_KEY_IS_NOT_REGISTERED"))
        )
        with DataGoKrClient(service_key="K", raw_dir=tmp_path) as c:
            with pytest.raises(DataGoKrError):
                c.get(URL, {}, dataset_id="D1")
        # No retry — exactly one call.
        assert route.call_count == 1


def test_service_key_is_appended_raw_not_double_encoded(tmp_path):
    """The portal expects the key as already-URL-encoded; httpx must not re-encode."""
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json=_ok([]))

    with respx.mock() as router:
        router.get(URL).mock(side_effect=handler)
        with DataGoKrClient(service_key="abc%2Fdef==", raw_dir=tmp_path) as c:
            c.get(URL, {"foo": "bar"}, dataset_id="D1")

    assert "ServiceKey=abc%2Fdef==" in captured[0]
    assert "foo=bar" in captured[0]

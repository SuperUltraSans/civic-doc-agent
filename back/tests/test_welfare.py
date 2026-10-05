"""복지 연계: 상황 태그, API 응답 파싱, 사본 검색, evaluate 지역 필터."""

from app.agent.nodes.evaluate import filter_region_items, plan_retry
from app.tools.welfare import _parse_serv_list, _snapshot_candidates, searched_count, situation_tags

XML = """<?xml version="1.0" encoding="UTF-8"?>
<wantedList><resultCode>0</resultCode><totalCount>2</totalCount>
<servList><servId>WLF0001</servId><servNm>긴급복지 생계지원</servNm><servDgst>위기 가구 생계비 지원</servDgst>
<servDtlLink>https://www.bokjiro.go.kr/x</servDtlLink><ctpvNm>경상남도</ctpvNm><sggNm>김해시</sggNm></servList>
<servList><servId>WLF0002</servId><servNm>노인 돌봄</servNm><servDgst>요약</servDgst></servList>
</wantedList>"""


def test_parse_serv_list():
    local = _parse_serv_list(XML, "local")
    assert [r["id"] for r in local] == ["WLF0001", "WLF0002"]
    assert local[0]["region"] == "김해시" and local[0]["url"] == "https://www.bokjiro.go.kr/x"
    assert local[1]["url"] == "https://www.bokjiro.go.kr"
    assert all(r["region"] == "" for r in _parse_serv_list(XML, "national"))


def test_situation_tags():
    doc = {"docType": "health_insurance_bill", "fields": {"amount": 32500, "arrears": 21000}}
    assert situation_tags(doc, {})[:4] == ["체납", "분할납부", "긴급지원", "생계"]
    assert "노인" in situation_tags({"docType": "local_tax_bill", "fields": {}}, {"ageGroup": "70s"})
    assert situation_tags({"docType": "unknown", "fields": {}}, {}) == ["노인", "저소득"]


def test_snapshot_only_central_or_same_region():
    rows = _snapshot_candidates(["체납"], "김해시")
    assert rows and all(r["region"] in ("", "김해시", "경상남도") for r in rows)


def test_filter_region_items():
    welfare = {
        "items": [
            {"name": "a", "region": "김해시"},
            {"name": "b", "region": "창원시"},
            {"name": "c", "region": "경상남도"},
            {"name": "d", "region": ""},
            {"name": "m", "region": "", "fixed": True},
        ],
        "usedProfile": True,
        "fallbackUsed": False,
    }
    kept, removed = filter_region_items(welfare, "김해시")
    assert [i["name"] for i in kept["items"]] == ["a", "c", "d", "m"] and removed == 1
    kept, removed = filter_region_items(welfare, None)
    assert [i["name"] for i in kept["items"]] == ["d", "m"] and removed == 3
    assert searched_count(welfare) == 4


def test_evaluate_retry_rules():
    plan = [
        {"tool": "check_impersonation", "reason": "r", "required": True},
        {"tool": "search_welfare", "reason": "r", "required": False},
    ]
    empty_welfare = {"items": [{"name": "m", "fixed": True}], "usedProfile": True, "fallbackUsed": False}
    retry, ignore_region, notes = plan_retry({"plan": plan, "tool_results": {"welfare": empty_welfare}})
    assert retry == ["check_impersonation", "search_welfare"] and ignore_region is True
    assert any("지역 조건 제외" in n for n in notes)
    retry, ignore_region, _ = plan_retry({"plan": plan, "tool_results": {"impersonation": {}, "welfare": {**empty_welfare, "usedProfile": False}}})
    assert retry == [] and ignore_region is False

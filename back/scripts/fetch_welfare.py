"""복지 데이터 사본 만들기 → data/welfare_snapshot.csv (지시서 5.7절 (3) 대체 경로).

공공데이터포털 한국사회보장정보원 복지서비스 목록 API(중앙부처·지자체)를 받아 CSV로 저장한다.
서버는 시작할 때 CSV가 바뀌었으면 SQLite로 다시 읽는다.

※ 엔드포인트·요청 변수·응답 필드는 공공데이터포털 명세로 확인 후 필요하면 고친다
   (app/tools/welfare.py 의 NATIONAL_LIST_URL / LOCAL_LIST_URL 과 함께).

    DATA_GO_KR_SERVICE_KEY=... python scripts/fetch_welfare.py [--sido 경상남도] [--pages 10]
"""

from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.tools.welfare import LOCAL_LIST_URL, NATIONAL_LIST_URL  # noqa: E402

# 상황 태그 사전: 이름·요약에 이 말이 있으면 태그를 붙인다 (welfare.situation_tags 와 같은 말을 쓴다)
TAG_WORDS = {
    "체납": ["체납", "미납", "연체"],
    "분할납부": ["분할", "분납", "나누어"],
    "긴급지원": ["긴급", "위기"],
    "생계": ["생계", "생활비"],
    "건강보험": ["건강보험"],
    "보험료": ["보험료"],
    "지방세": ["지방세", "재산세", "주민세"],
    "과태료": ["과태료"],
    "노인": ["노인", "어르신", "65세", "고령"],
    "기초연금": ["기초연금"],
    "저소득": ["저소득", "기초생활", "차상위", "수급"],
    "의료": ["의료", "병원", "진료"],
    "돌봄": ["돌봄", "요양"],
    "주거": ["주거", "임대", "주택"],
    "에너지": ["에너지", "난방", "냉방"],
}
COLUMNS = ["serv_id", "name", "summary", "target", "ctpv", "sgg", "tags", "url", "source", "kind"]


def tags_for(text: str) -> str:
    return ";".join(tag for tag, words in TAG_WORDS.items() if any(w in text for w in words))


def parse(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    rows = []
    for item in root.iter("servList"):
        if (item.findtext("servNm") or "").strip():
            rows.append({k: (item.findtext(k) or "").strip() for k in ("servId", "servNm", "servDgst", "servDtlLink", "ctpvNm", "sggNm", "jurMnofNm", "trgterIndvdlArray")})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sido", default="경상남도")
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--rows", type=int, default=100)
    parser.add_argument("--out", default=str(ROOT / "data" / "welfare_snapshot.csv"))
    args = parser.parse_args()
    key = get_settings().secret(get_settings().data_go_kr_service_key)
    if not key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY 가 필요합니다")

    out: dict[str, dict[str, str]] = {}
    with httpx.Client(timeout=20) as client:
        for kind, url, extra in (
            ("central", NATIONAL_LIST_URL, {"callTp": "L", "srchKeyCode": "003"}),
            ("local", LOCAL_LIST_URL, {"ctpvNm": args.sido}),
        ):
            for page in range(1, args.pages + 1):
                resp = client.get(url, params={"serviceKey": key, "pageNo": page, "numOfRows": args.rows, **extra})
                resp.raise_for_status()
                items = parse(resp.text)
                if not items:
                    break
                for it in items:
                    text = f"{it['servNm']} {it['servDgst']}"
                    out[it["servId"] or it["servNm"]] = {
                        "serv_id": it["servId"] or it["servNm"],
                        "name": it["servNm"],
                        "summary": it["servDgst"],
                        "target": it["trgterIndvdlArray"],
                        "ctpv": it["ctpvNm"] if kind == "local" else "",
                        "sgg": it["sggNm"] if kind == "local" else "",
                        "tags": tags_for(text),
                        "url": it["servDtlLink"] or "https://www.bokjiro.go.kr",
                        "source": f"한국사회보장정보원 복지서비스 API ({it['jurMnofNm'] or kind})",
                        "kind": kind,
                    }
                print(f"{kind} page {page}: {len(items)}건")
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out.values())
    print(f"saved {len(out)} rows → {args.out}")


if __name__ == "__main__":
    main()

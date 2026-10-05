"""사칭 수법 자료 정리 → data/scam_patterns.jsonl (지시서 5.8절, 6.2절).

공개 예방 자료(KISA 보호나라, 경찰청, 금융감독원 등)에서 수법 단위로 정리한 CSV를 받아
한 항목 = 수법 1개 + 신호어 + 사용자 문장 + 출처 로 검증·정규화해 jsonl로 쓴다.
CSV 없이 실행하면 기존 jsonl을 검사만 한다.

CSV 열: id, pattern, signals(; 로 구분), userMessage, source, sourceUrl

    python scripts/build_scam_corpus.py [--csv raw_patterns.csv] [--check]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.textutil import is_assertive  # noqa: E402

OUT = ROOT / "data" / "scam_patterns.jsonl"
REQUIRED = ("id", "pattern", "signals", "userMessage", "source", "sourceUrl")
MAX_USER_MESSAGE = 40  # 고령자에게 그대로 보여주는 문장은 짧게


def validate(items: list[dict]) -> list[str]:
    problems = []
    ids = Counter(i.get("id") for i in items)
    for item in items:
        iid = item.get("id", "?")
        for key in REQUIRED:
            if not item.get(key):
                problems.append(f"{iid}: {key} 비어 있음")
        if ids[iid] > 1:
            problems.append(f"{iid}: id 중복")
        msg = item.get("userMessage", "")
        if len(msg) > MAX_USER_MESSAGE:
            problems.append(f"{iid}: userMessage {len(msg)}자 (>{MAX_USER_MESSAGE})")
        if is_assertive(msg):
            problems.append(f"{iid}: userMessage 단정 표현")
        if any(ch.isdigit() for ch in msg):
            problems.append(f"{iid}: userMessage에 숫자")
    return problems


def from_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [
            {
                "id": r["id"].strip(),
                "pattern": r["pattern"].strip(),
                "signals": [s.strip() for s in r["signals"].split(";") if s.strip()],
                "userMessage": r["userMessage"].strip(),
                "source": r["source"].strip(),
                "sourceUrl": r["sourceUrl"].strip(),
            }
            for r in csv.DictReader(f)
        ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--check", action="store_true", help="검사만 하고 쓰지 않음")
    args = parser.parse_args()
    if args.csv:
        items = from_csv(args.csv)
    else:
        items = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]
    problems = validate(items)
    by_source = Counter(i.get("source", "?") for i in items)
    print(f"{len(items)}개 수법, 출처별: {dict(by_source)}")
    if problems:
        print("문제:\n  " + "\n  ".join(problems))
        raise SystemExit(1)
    if args.csv and not args.check:
        OUT.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
        print(f"saved → {OUT}")


if __name__ == "__main__":
    main()

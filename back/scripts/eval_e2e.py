"""전체 흐름(E2E) 측정 — 촬영 이미지 입력부터 종료 이벤트까지 (지시서 7.4, 9.2, 9.4절).

samples/ 의 이미지를 실제 API(POST /analyze → 지역 질문 즉시 답 → GET /events)로 하나씩 넣고
종료 이벤트가 정답 JSON의 기대(다시 찍기 / 결과)와 같은지, 걸린 시간, 할 일·사칭 판정을 기록한다.
지역 질문은 바로 답하므로 사람을 기다린 시간은 측정에 들어가지 않는다.

**수치는 측정값을 그대로 쓴다. 조정하지 않는다.** 목표(평균 30초 이내)에 못 미치면 그대로 적는다.

    python scripts/eval_e2e.py [--samples samples] [--out docs] [--repeat 1]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")  # 측정 중 요청 수 제한에 걸리지 않게

from record_run_log import parse_sse  # noqa: E402

from app.agent.nodes.verify_explanation import find_violations  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.client import describe_line, describe_targets  # noqa: E402
from app.timeutil import now  # noqa: E402

TARGET_SECONDS = 30.0
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


async def run_one(client: httpx.AsyncClient, image: Path, answer: str) -> dict[str, Any]:
    from app.sessions.manager import get_manager

    started = time.perf_counter()
    r = await client.post("/api/analyze", files={"image": (image.name, image.read_bytes(), IMAGE_TYPES[image.suffix.lower()])})
    r.raise_for_status()
    sid = r.json()["sessionId"]
    session = get_manager().sessions[sid]
    while not (session.pending_question or session.finished):
        await asyncio.sleep(0.02)
    asked = session.pending_question is not None
    if asked:
        await client.post(f"/api/analyze/{sid}/answer", json={"field": "region", "value": answer})
    events = parse_sse((await client.get(f"/api/analyze/{sid}/events")).text)
    seconds = (session.finished_at - session.created_at) if session.finished_at else time.perf_counter() - started
    final = events[-1]
    row: dict[str, Any] = {"terminal": final["event"], "seconds": round(seconds, 2), "asked": asked}
    if final["event"] == "result":
        result = final["data"]
        tools = result.get("tools") or {}
        imp = tools.get("impersonation") or {}
        row.update(
            {
                "docType": result["document"]["docType"],
                "todos": [t["title"] for t in result["todos"]],
                "callTels": sorted({a["tel"] for t in result["todos"] for a in t["actions"] if a["type"] == "call"}),
                "impersonation": imp.get("status"),
                "redFlags": len(imp.get("redFlags") or []),
                "welfareItems": len((tools.get("welfare") or {}).get("items") or []),
                "explanationViolations": find_violations(result["explanation"], result["document"]),
                "summaryTemplate": result["explanation"]["summaryTemplate"],
                "notDoneSteps": [f"{s['id']}:{s['status']}" for s in result["steps"] if s["status"] != "done"],
            }
        )
    elif final["event"] == "need_retake":
        row["retake"] = final["data"].get("message")
    else:
        row["error"] = final["data"].get("code")
    return row


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default=str(ROOT / "samples"))
    parser.add_argument("--out", default=str(ROOT / "docs"))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--answer", default="김해시", help="지역 질문에 줄 답")
    parser.add_argument("--only", default="", help="쉼표로 구분한 샘플 이름(확장자 제외)만 실행")
    parser.add_argument("--allow-fake", action="store_true", help="파이프라인 점검용 (수치는 의미 없음)")
    args = parser.parse_args()
    s = get_settings()
    if (s.llm_provider == "fake" or s.agent_mode != "live") and not args.allow_fake:
        raise SystemExit("실제 동작 측정은 AGENT_MODE=live + 실제 공급자에서만 합니다 (--allow-fake 는 점검용)")

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    samples = []
    for answer_path in sorted(Path(args.samples).glob("*.json")):
        if only and answer_path.stem not in only:
            continue
        image = next((answer_path.with_suffix(ext) for ext in IMAGE_TYPES if answer_path.with_suffix(ext).exists()), None)
        if image is not None:
            samples.append((image, json.loads(answer_path.read_text(encoding="utf-8"))))

    from app.main import create_app

    app = create_app()
    rows: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local", timeout=300) as client:
            for i in range(args.repeat):
                for image, expected in samples:
                    expect = "need_retake" if (not expected.get("legible", True) or expected.get("docType") == "unknown") else "result"
                    try:
                        row = await run_one(client, image, args.answer)
                    except Exception as exc:  # 측정 중 실패도 그대로 기록
                        row = {"terminal": "exception", "seconds": None, "error": type(exc).__name__}
                    row = {"sample": image.name, "run": i + 1, "expected": expect, "ok": row["terminal"] == expect, **row}
                    rows.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)

    times = [r["seconds"] for r in rows if isinstance(r.get("seconds"), (int, float))]
    result_times = [r["seconds"] for r in rows if r["terminal"] == "result" and isinstance(r.get("seconds"), (int, float))]
    avg = round(sum(times) / len(times), 2) if times else None
    summary = {
        "measuredAt": now().isoformat(timespec="seconds"),
        "provider": s.llm_provider,
        "models": describe_targets(),
        "runs": len(rows),
        "terminalAccuracy": sum(r["ok"] for r in rows) / len(rows) if rows else None,
        "avgSeconds": avg,
        "maxSeconds": round(max(times), 2) if times else None,
        "avgSecondsResultOnly": round(sum(result_times) / len(result_times), 2) if result_times else None,
        "rows": rows,
    }

    def cell(v: Any) -> str:
        if isinstance(v, list):
            return ", ".join(map(str, v)) or "-"
        return "-" if v in (None, "") else str(v).replace("|", "/")

    md = [
        f"# 전체 흐름(E2E) 측정 ({summary['measuredAt']})",
        "",
        f"- 공급자/모델: {describe_line()}",
        f"- 실행: 샘플 {len(samples)}장 × {args.repeat}회 = {len(rows)}건 (합성 샘플 {sum(1 for _, e in samples if e.get('synthetic'))}장)",
        "- 시간: POST /api/analyze 수신부터 종료 이벤트(result / need_retake / error)까지 서버 기준. 지역 질문은 즉시 답함(사람 대기 시간 제외)",
        "- 복지: 공공데이터 API 키 없음 → 사본(welfare_snapshot) 경로 / 실시간 검색 키 없음 → 시드 표·캐시만 사용",
        "",
        "| 항목 | 목표 | 측정값 | 달성 |",
        "|---|---|---|---|",
        f"| 평균 처리 시간 (전체 흐름) | 30초 이내 | {avg}초 | {'예' if avg is not None and avg <= TARGET_SECONDS else '아니오'} |",
        f"| 최대 처리 시간 | — | {summary['maxSeconds']}초 | — |",
        f"| 평균 처리 시간 (result 건만) | — | {summary['avgSecondsResultOnly']}초 | — |",
        f"| 종료 이벤트 일치 (결과 / 다시 찍기) | — | {sum(r['ok'] for r in rows)}/{len(rows)} | — |",
        "",
        "| 샘플 | 회차 | 기대 | 종료 | 시간(초) | 질문 | 사칭 판정 | 할 일 | 전화 버튼 번호 | 완료 아닌 단계 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {r['sample']} | {r['run']} | {r['expected']} | {r['terminal']}{'' if r['ok'] else ' ✗'} | {cell(r.get('seconds'))} | "
            f"{'예' if r.get('asked') else '-'} | {cell(r.get('impersonation'))} | {cell(r.get('todos'))} | {cell(r.get('callTels'))} | "
            f"{cell(r.get('notDoneSteps') or r.get('retake') or r.get('error'))} |"
            for r in rows
        ],
        "",
        "※ 측정값을 조정하지 않았다. 목표 미달 시 원인과 개선 방향을 보고서에 함께 적는다.",
    ]
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    stamp = now().strftime("%Y%m%d-%H%M")
    (out / f"eval_e2e_{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"eval_e2e_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    asyncio.run(main())

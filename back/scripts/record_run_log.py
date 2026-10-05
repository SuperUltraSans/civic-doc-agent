"""대표 시나리오 1건의 전체 실행 로그 저장 → docs/sample_run_log.json (지시서 10장).

현재 환경 변수의 공급자(LLM_PROVIDER)로 샘플 이미지 1장을 API에 넣고, SSE 이벤트 전체와 최종 결과의
steps·plan 을 저장한다. 개인정보 없는 가상 샘플만 쓴다. 파일에 공급자·모드를 함께 적어
fake/scripted 로 만든 로그가 실제 동작 로그로 오해되지 않게 한다.

    LLM_PROVIDER=bedrock ... python scripts/record_run_log.py --image samples/hib_arrears.jpg --answer 김해시
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.timeutil import now_iso  # noqa: E402


def parse_sse(text: str) -> list[dict]:
    events, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            events.append({"event": name, "data": json.loads(line[5:].strip())})
            name = None
    return events


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=str(ROOT / "samples" / "hib_arrears.jpg"))
    parser.add_argument("--scenario", default=None, help="fake/scripted 에서 고를 시나리오")
    parser.add_argument("--answer", default="김해시", help="지역 질문에 줄 답 (건너뛰기는 빈 문자열)")
    parser.add_argument("--out", default=str(ROOT / "docs" / "sample_run_log.json"))
    args = parser.parse_args()

    from app.main import create_app
    from app.sessions.manager import get_manager

    app = create_app()
    s = get_settings()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local", timeout=180) as client:
            image = Path(args.image)
            data = {"scenario": args.scenario} if args.scenario else {}
            r = await client.post("/api/analyze", files={"image": (image.name, image.read_bytes(), "image/jpeg")}, data=data)
            r.raise_for_status()
            sid = r.json()["sessionId"]
            session = get_manager().sessions[sid]
            while not (session.pending_question or session.finished):
                await asyncio.sleep(0.05)
            if session.pending_question:
                await client.post(f"/api/analyze/{sid}/answer", json={"field": "region", "value": args.answer or None})
            events = parse_sse((await client.get(f"/api/analyze/{sid}/events")).text)

    final = events[-1]
    result = final["data"] if final["event"] == "result" else None
    log = {
        "recordedAt": now_iso(),
        "agentMode": s.agent_mode,
        "llmProvider": s.llm_provider,
        "models": {"vision": s.model_vision, "reason": s.model_reason, "fast": s.model_fast},
        "note": (
            "실제 모델 실행 로그" if s.llm_provider != "fake" and s.agent_mode == "live"
            else "⚠ fake 공급자 또는 scripted 모드로 만든 예시 로그 — 실제 동작 로그로 교체할 것"
        ),
        "sample": image.name,
        "terminalEvent": final["event"],
        "plan": result["plan"] if result else None,
        "steps": result["steps"] if result else None,
        "todos": result["todos"] if result else None,
        "events": events,
    }
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved → {out} ({len(events)} events, {final['event']})")


if __name__ == "__main__":
    asyncio.run(main())

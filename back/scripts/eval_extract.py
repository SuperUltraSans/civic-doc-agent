"""추출 정확도·처리 시간 평가 (지시서 9.3절).

samples/ 의 이미지를 실제 모델로 처리해 정답 JSON과 필드별로 비교한다.
실제 서비스와 같은 경로(preprocess → extract → validate → 필요 시 재추출 → validate)를 탄다.

출력: 필드별 정확도, 전체 정확도, 문서 1장당 평균·최대 처리 시간, 다시 찍기 판정 정확도.
**수치는 측정값을 그대로 쓴다. 조정하지 않는다.** 목표(핵심 정보 90% 이상, 평균 30초 이내)에 못 미치면 그대로 적는다.

    LLM_PROVIDER=anthropic MODEL_VISION=... python scripts/eval_extract.py [--samples samples] [--out docs]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.nodes.extract import extract  # noqa: E402
from app.agent.nodes.preprocess import preprocess  # noqa: E402
from app.agent.nodes.validate import validate  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.client import describe_targets  # noqa: E402
from app.timeutil import now  # noqa: E402
from app.tools.impersonation import normalize_phone  # noqa: E402

FIELDS = ("docType", "amount", "dueDate", "billingMonth", "arrears", "phone", "url")
KEY_FIELDS = ("docType", "amount", "dueDate")  # 핵심 정보 (신청서 목표 기준)
TARGET_ACCURACY = 0.90
TARGET_SECONDS = 30.0


def norm(field: str, value: Any) -> Any:
    if value in (None, ""):
        return None
    if field == "phone":
        return normalize_phone(str(value))
    if field == "url":
        return str(value).strip().lower().rstrip("/")  # 적힌 그대로 옮겼는지 (http:// 여부도 판정에 쓰이므로 유지)
    return value


async def run_one(image: Path) -> tuple[dict[str, Any], float]:
    state: dict[str, Any] = {"session_id": None, "image_bytes": image.read_bytes(), "profile": {}, "steps": []}
    started = time.perf_counter()
    state.update(await preprocess(state))
    if state.get("retake"):  # 사진 품질 사전 점검에서 바로 다시 찍기 (LLM 호출 없음)
        return state, time.perf_counter() - started
    state.update(await extract(state))
    update = await validate(state)
    state.update(update)
    if state.get("recheck_fields"):
        state.update(await extract(state))
        state.update(await validate(state))
    return state, time.perf_counter() - started


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default=str(ROOT / "samples"))
    parser.add_argument("--out", default=str(ROOT / "docs"))
    parser.add_argument("--allow-fake", action="store_true", help="파이프라인 점검용 (수치는 의미 없음)")
    args = parser.parse_args()
    settings = get_settings()
    if settings.llm_provider == "fake" and not args.allow_fake:
        raise SystemExit("LLM_PROVIDER=fake 로는 정확도를 잴 수 없습니다 (--allow-fake 는 점검용)")

    rows: list[dict[str, Any]] = []
    for answer_path in sorted(Path(args.samples).glob("*.json")):
        image = next((answer_path.with_suffix(ext) for ext in (".jpg", ".jpeg", ".png", ".webp") if answer_path.with_suffix(ext).exists()), None)
        if image is None:
            continue
        expected = json.loads(answer_path.read_text(encoding="utf-8"))
        try:
            state, seconds = await run_one(image)
            error = None
        except Exception as exc:  # 측정 중 실패도 그대로 기록
            state, seconds, error = {}, float("nan"), type(exc).__name__
        expect_retake = not expected.get("legible", True) or expected.get("docType") == "unknown"
        got_retake = bool(state.get("retake")) or error is not None
        row: dict[str, Any] = {"sample": image.name, "seconds": round(seconds, 2), "error": error, "synthetic": expected.get("synthetic", False)}
        row["retakeCorrect"] = expect_retake == got_retake
        if not expect_retake:
            doc = state.get("document") or {}
            got = {"docType": doc.get("docType"), **(doc.get("fields") or {})}
            want = {"docType": expected.get("docType"), **(expected.get("fields") or {})}
            row["fields"] = {f: norm(f, got.get(f)) == norm(f, want.get(f)) for f in FIELDS}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    scored = [r for r in rows if "fields" in r]
    per_field = {f: (sum(r["fields"][f] for r in scored) / len(scored) if scored else None) for f in FIELDS}
    key_total = sum(r["fields"][f] for r in scored for f in KEY_FIELDS)
    key_acc = key_total / (len(scored) * len(KEY_FIELDS)) if scored else None
    all_acc = sum(sum(r["fields"].values()) for r in scored) / (len(scored) * len(FIELDS)) if scored else None
    times = [r["seconds"] for r in rows if r["seconds"] == r["seconds"]]
    retake_acc = sum(r["retakeCorrect"] for r in rows) / len(rows) if rows else None
    summary = {
        "measuredAt": now().isoformat(timespec="seconds"),
        "provider": settings.llm_provider,
        "modelVision": describe_targets()["vision"],
        "samples": len(rows),
        "syntheticSamples": sum(1 for r in rows if r["synthetic"]),
        "perFieldAccuracy": per_field,
        "keyFieldAccuracy": key_acc,
        "allFieldAccuracy": all_acc,
        "avgSeconds": round(sum(times) / len(times), 2) if times else None,
        "maxSeconds": round(max(times), 2) if times else None,
        "retakeAccuracy": retake_acc,
        "rows": rows,
    }

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v * 100:.1f}%"

    md = [
        f"# 추출 정확도·시간 측정 ({summary['measuredAt']})",
        "",
        f"- 공급자/모델 (문서 읽기): {describe_targets()['vision']['provider']} / {describe_targets()['vision']['model']}",
        f"- 샘플: {summary['samples']}장 (합성 {summary['syntheticSamples']}장)",
        "",
        "| 항목 | 목표 | 측정값 | 달성 |",
        "|---|---|---|---|",
        f"| 핵심 정보 정확도 (docType·amount·dueDate) | 90% 이상 | {pct(key_acc)} | {'예' if key_acc is not None and key_acc >= TARGET_ACCURACY else '아니오'} |",
        f"| 평균 처리 시간 (추출 단계) | 30초 이내 | {summary['avgSeconds']}초 | {'예' if summary['avgSeconds'] is not None and summary['avgSeconds'] <= TARGET_SECONDS else '아니오'} |",
        f"| 최대 처리 시간 | — | {summary['maxSeconds']}초 | — |",
        f"| 전체 필드 정확도 | — | {pct(all_acc)} | — |",
        f"| 다시 찍기 판정 정확도 | — | {pct(retake_acc)} | — |",
        "",
        "| 필드 | 정확도 |",
        "|---|---|",
        *[f"| {f} | {pct(v)} |" for f, v in per_field.items()],
        "",
        "※ 측정값을 조정하지 않았다. 목표 미달 시 원인과 개선 방향을 보고서에 함께 적는다.",
    ]
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    stamp = now().strftime("%Y%m%d-%H%M")
    (out / f"eval_extract_{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"eval_extract_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    asyncio.run(main())

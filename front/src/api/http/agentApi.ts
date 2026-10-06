// 실제 백엔드 연동 (백엔드 구현지시서 3장).
//   POST /api/analyze (multipart: image, profile, scenario) → { sessionId }
//   GET  /api/analyze/{sessionId}/events (SSE)
//   POST /api/analyze/{sessionId}/answer { field, value }
//   POST /api/simplify { docId } → Explanation
import { getScenario } from '../../lib/scenario';
import {
  ERRORS,
  isApiError,
  type AgentApi,
  type AgentStep,
  type AnalysisResult,
  type AnalyzeHandlers,
  type AnalyzeSession,
  type ApiError,
  type Explanation,
  type InfoQuestion,
  type PlanItem,
  type RetakeRequest,
  type UserProfile,
} from '../types';
import { SseParser } from './sse';

// 비우면 앱과 같은 경로 아래의 /api (개발: /api, 엣지 배포: /civic-doc-agent/api)
const BASE = (import.meta.env.VITE_API_BASE_URL || import.meta.env.BASE_URL).replace(/\/+$/, '');
/** 이 시간 동안 아무 바이트도 오지 않으면 연결이 끊긴 것으로 본다 (백엔드는 15초마다 ping) */
const IDLE_TIMEOUT_MS = 45_000;

async function readApiError(res: Response): Promise<ApiError> {
  try {
    const body: unknown = await res.json();
    if (isApiError(body)) return body;
  } catch {
    // 본문이 JSON 이 아니면 상태 코드로 판단
  }
  // 415: 앱이 거절한 형식, 413: 엣지(nginx)가 막은 너무 큰 파일
  if (res.status === 415 || res.status === 413) return ERRORS.unsupported_image;
  if (res.status === 502 || res.status === 503 || res.status === 504) return ERRORS.network;
  return ERRORS.server;
}

function analyze(image: Blob, profile: UserProfile, handlers: AnalyzeHandlers): AnalyzeSession {
  const controller = new AbortController();
  let ended = false; // 종료 이벤트를 받았거나 취소됨 → 더 이상 콜백을 부르지 않는다
  let sessionId: string | null = null;
  let idleTimer: number | undefined;

  const stop = () => {
    ended = true;
    window.clearTimeout(idleTimer);
    controller.abort();
  };
  const fail = (error: ApiError) => {
    if (ended) return;
    stop();
    handlers.onError(error);
  };
  const touch = () => {
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(() => fail(ERRORS.network), IDLE_TIMEOUT_MS);
  };

  const dispatch = (event: string, raw: string) => {
    if (ended) return;
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    switch (event) {
      case 'step':
        handlers.onStep(data as AgentStep);
        break;
      case 'plan':
        handlers.onPlan(data as PlanItem[]);
        break;
      case 'need_info':
        handlers.onNeedInfo(data as InfoQuestion);
        break;
      case 'need_retake':
        stop();
        handlers.onNeedRetake(data as RetakeRequest);
        break;
      case 'result':
        stop();
        handlers.onResult(data as AnalysisResult);
        break;
      case 'error':
        stop();
        handlers.onError(isApiError(data) ? data : ERRORS.server);
        break;
      default:
        break;
    }
  };

  const run = async () => {
    const form = new FormData();
    form.append('image', image, 'photo.jpg');
    form.append('profile', JSON.stringify(profile));
    form.append('scenario', getScenario()); // AGENT_MODE=scripted·fake 공급자에서만 쓰인다
    let res: Response;
    try {
      touch();
      res = await fetch(`${BASE}/api/analyze`, { method: 'POST', body: form, signal: controller.signal });
    } catch {
      fail(ERRORS.network);
      return;
    }
    if (!res.ok) {
      fail(await readApiError(res));
      return;
    }
    try {
      sessionId = ((await res.json()) as { sessionId: string }).sessionId;
    } catch {
      fail(ERRORS.server);
      return;
    }

    let stream: Response;
    try {
      stream = await fetch(`${BASE}/api/analyze/${encodeURIComponent(sessionId)}/events`, {
        headers: { Accept: 'text/event-stream' },
        cache: 'no-store',
        signal: controller.signal,
      });
    } catch {
      fail(ERRORS.network);
      return;
    }
    if (!stream.ok || !stream.body) {
      fail(await readApiError(stream));
      return;
    }
    const reader = stream.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        touch();
        for (const message of parser.feed(value)) dispatch(message.event, message.data);
        if (ended) break;
      }
    } catch {
      // 연결 끊김 또는 취소
    } finally {
      reader.cancel().catch(() => {});
    }
    // 종료 이벤트 없이 스트림이 끝났으면 연결이 끊긴 것
    fail(ERRORS.network);
  };

  void run();

  return {
    answer(field, value) {
      if (ended || !sessionId) return;
      fetch(`${BASE}/api/analyze/${encodeURIComponent(sessionId)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field, value }),
        signal: controller.signal,
      })
        .then(async (res) => {
          if (!res.ok) fail(await readApiError(res));
        })
        .catch(() => fail(ERRORS.network));
    },
    cancel() {
      stop();
    },
  };
}

async function simplify(docId: string): Promise<Explanation> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/simplify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ docId }),
    });
  } catch {
    throw ERRORS.network;
  }
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as Explanation;
}

export const httpAgentApi: AgentApi = { analyze, simplify };

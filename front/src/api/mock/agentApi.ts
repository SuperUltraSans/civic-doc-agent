// 목업 API (구현지시서 6.1절). 시나리오 이벤트를 지연 시간을 두고 순서대로 재생한다.
// 업로드된 이미지 내용은 보지 않는다 — 어떤 사진을 넣어도 선택된 시나리오가 재생된다.
import { getScenario } from '../../lib/scenario';
import { readSession, writeSession } from '../../lib/storage';
import { uid } from '../../lib/uid';
import type { AgentApi, AgentStep, AnalyzeHandlers, AnalyzeSession, Explanation, UserProfile } from '../types';
import { ERRORS } from '../types';
import { SCENARIO_BUILDERS } from './scenarios';

const FAST = import.meta.env.VITE_MOCK_SPEED === 'fast';

/** 단계당 지연: 기본 0.8~2초(실제와 비슷하게), fast 0.2초 */
function stepDelay(): number {
  return FAST ? 200 : 800 + Math.random() * 1200;
}

// "더 쉽게 설명해 주세요"용 level 2 설명 (docId 기준).
// 실제 백엔드는 서버 메모리에 30분 보관하므로 결과 화면을 새로고침해도 쓸 수 있다.
// 목업도 같게 동작하도록 sessionStorage 에 둔다 (설명 문장뿐, 이미지·연락처 없음).
const LEVEL2_KEY = 'ilgeo.v1.mock.level2';

function readLevel2(): Record<string, Explanation> {
  try {
    return JSON.parse(readSession(LEVEL2_KEY) ?? '{}') as Record<string, Explanation>;
  } catch {
    return {};
  }
}

function saveLevel2(docId: string, explanation: Explanation): void {
  writeSession(LEVEL2_KEY, JSON.stringify({ ...readLevel2(), [docId]: explanation }));
}

class Cancelled extends Error {}

function analyze(_image: Blob, profile: UserProfile, handlers: AnalyzeHandlers): AnalyzeSession {
  const scenario = SCENARIO_BUILDERS[getScenario()]();
  const timers = new Set<number>();
  let cancelled = false;
  let pendingAnswer: ((value: string | null) => void) | null = null;

  const sleep = (ms: number) =>
    new Promise<void>((resolve, reject) => {
      if (cancelled) {
        reject(new Cancelled());
        return;
      }
      const id = window.setTimeout(() => {
        timers.delete(id);
        if (cancelled) reject(new Cancelled());
        else resolve();
      }, ms);
      timers.add(id);
    });

  const play = async () => {
    const steps: AgentStep[] = [];
    let region: string | null = profile.region && profile.region !== '기타' ? profile.region : null;
    await sleep(300);
    for (const event of scenario.events) {
      if (cancelled) return;
      switch (event.kind) {
        case 'step':
          steps.push(event.step);
          handlers.onStep(event.step);
          if (event.wait) await sleep(stepDelay());
          break;
        case 'plan':
          handlers.onPlan(event.plan);
          await sleep(FAST ? 100 : 500);
          break;
        case 'question': {
          // 프로필에 이미 지역이 있으면 묻지 않는다 (요청 시 profile 을 함께 보냄)
          if (profile.region) break;
          const answer = await new Promise<string | null>((resolve) => {
            pendingAnswer = resolve;
            handlers.onNeedInfo(event.question);
          });
          pendingAnswer = null;
          if (cancelled) return;
          region = answer && answer !== '기타' ? answer : null;
          await sleep(300);
          break;
        }
        case 'retake':
          handlers.onNeedRetake(event.request);
          return;
        case 'error':
          handlers.onError(event.error);
          return;
        case 'result': {
          const result = event.build({ docId: uid(), region, steps });
          if (scenario.level2) saveLevel2(result.docId, scenario.level2);
          handlers.onResult(result);
          return;
        }
      }
    }
  };

  play().catch((err: unknown) => {
    if (err instanceof Cancelled || cancelled) return;
    handlers.onError(ERRORS.server);
  });

  return {
    answer(_field, value) {
      pendingAnswer?.(value);
    },
    cancel() {
      cancelled = true;
      timers.forEach((id) => window.clearTimeout(id));
      timers.clear();
      pendingAnswer?.(null);
    },
  };
}

function simplify(docId: string): Promise<Explanation> {
  return new Promise((resolve, reject) => {
    window.setTimeout(
      () => {
        const level2 = readLevel2()[docId];
        if (level2) resolve(level2);
        else reject({ code: 'server', message: '시간이 지나서 다시 설명할 수 없어요. 문서를 다시 찍어 주세요' });
      },
      FAST ? 200 : 1200,
    );
  });
}

export const mockAgentApi: AgentApi = { analyze, simplify };

// 목업 시나리오 데이터 (구현지시서 6.2절).
// 백엔드 AGENT_MODE=scripted 와 같은 시나리오 키·단계 문구·결과 모양을 쓴다 (back/app/agent/scripted.py).
// 날짜는 실행 시점 기준 상대값으로 만든다. 이름·번호·주소는 모두 가상값이고, 가짜 주소는 .example 도메인을 쓴다.
import type {
  AgentStep,
  AnalysisResult,
  ApiError,
  ExtractedDocument,
  Explanation,
  InfoQuestion,
  PlanItem,
  RetakeRequest,
  WelfareItem,
} from '../types';
import { ERRORS } from '../types';
import type { ScenarioKey } from '../../lib/scenario';
import { todayYmd } from '../../lib/format';
import { REGION_OPTIONS } from '../../lib/regions';

// ── 재생 단위 ──
export type MockEvent =
  | { kind: 'step'; step: AgentStep; wait?: boolean } // wait: 이 단계 뒤에 지연을 둔다
  | { kind: 'plan'; plan: PlanItem[] }
  | { kind: 'question'; question: InfoQuestion } // answer() 까지 멈춘다
  | { kind: 'retake'; request: RetakeRequest }
  | { kind: 'error'; error: ApiError }
  | { kind: 'result'; build: (ctx: ResultContext) => AnalysisResult };

export interface ResultContext {
  docId: string;
  region: string | null; // 지역 답변 또는 저장된 프로필 (null = 건너뛰기·모름)
  steps: AgentStep[];
}

export interface Scenario {
  /** 이 시나리오가 지역 질문을 할 수 있는지 (프로필에 지역이 있으면 묻지 않는다) */
  asksRegion: boolean;
  events: MockEvent[];
  /** "더 쉽게 설명해 주세요" 결과 (level 2) */
  level2?: Explanation;
}

// ── 날짜 ──
function addDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return todayYmd(d);
}

function prevMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// ── 공통 문구 ──
const REGION_QUESTION: InfoQuestion = {
  field: 'region',
  question: '어느 지역에 사세요?',
  options: [...REGION_OPTIONS],
};

const TERMS = {
  납기내금액: { term: '납기 내 금액', plain: '정해진 날까지 내면 되는 돈', source: 'dictionary' },
  체납액: { term: '체납액', plain: '낼 날짜가 지났는데 아직 안 낸 돈', source: 'dictionary' },
  분할납부: { term: '분할납부', plain: '한 번에 다 내지 않고 여러 번 나눠서 내는 것', source: 'dictionary' },
  환급금: { term: '환급금', plain: '더 낸 돈을 돌려받는 것', source: 'dictionary' },
  단축주소: { term: '단축 주소', plain: '긴 인터넷 주소를 짧게 줄인 것. 어디로 연결되는지 보이지 않아요', source: 'dictionary' },
  스미싱: { term: '스미싱', plain: '문자 속 주소를 누르게 해서 돈이나 개인정보를 빼가는 사기', source: 'dictionary' },
  재산세: { term: '재산세', plain: '집이나 땅을 가진 사람이 내는 세금', source: 'dictionary' },
  전자납부번호: { term: '전자납부번호', plain: '은행이나 인터넷에서 낼 때 쓰는 이 고지서만의 번호', source: 'dictionary' },
} as const satisfies Record<string, Explanation['terms'][number]>;

const MEMBERSHIP: WelfareItem = {
  name: '복지멤버십(맞춤형 급여 안내)',
  summary: '한 번 가입해 두면 받을 수 있을지 모르는 복지 제도를 찾아서 알려 줘요. 주민센터나 복지로에서 신청할 수 있어요.',
  reason: '앞으로 해당될 수 있는 제도를 놓치지 않도록 함께 안내해요.',
  url: 'https://www.bokjiro.go.kr',
};

function step(id: string, label: string, status: AgentStep['status'], extra: Partial<AgentStep> = {}, wait = false): MockEvent {
  return { kind: 'step', step: { id, label, status, ...extra }, wait };
}

/** running → (지연) → done */
function runStep(id: string, label: string, doneLabel: string, extra: Partial<AgentStep> = {}): MockEvent[] {
  return [step(id, label, 'running', { doneLabel, ...extra }, true), step(id, label, 'done', { doneLabel, ...extra })];
}

function readAndValidate(classifyLabel: string, docType: string): MockEvent[] {
  return [
    ...runStep('read_text', '사진에서 글자를 읽고 있어요', '글자를 읽었어요', { detail: '[목업] 재생 모드' }),
    step('classify', classifyLabel, 'done', { detail: `문서 종류 분류: ${docType}` }),
    ...runStep('validate', '금액과 날짜를 확인하고 있어요', '금액과 날짜를 다시 확인했어요', { detail: '[목업] 형식 검사 통과' }),
  ];
}

function explainAndPlan(plan: PlanItem[], situation: string): MockEvent[] {
  const explain = { doneLabel: '쉬운 말로 정리했어요', tool: 'lookup_terms' as const };
  const planStep = { doneLabel: '확인할 일을 정했어요' };
  return [
    step('explain', '쉬운 말로 바꾸고 있어요', 'running', explain),
    step('plan', '무엇을 확인할지 정하고 있어요', 'running', planStep, true),
    step('explain', '쉬운 말로 바꾸고 있어요', 'done', { ...explain, detail: '[목업]' }),
    step('plan', '무엇을 확인할지 정하고 있어요', 'done', { ...planStep, detail: `[목업] 상황: ${situation}` }),
    { kind: 'plan', plan },
  ];
}

const EVALUATE = [
  ...runStep('evaluate', '찾은 내용이 맞는지 확인하고 있어요', '찾은 내용이 맞는지 한 번 더 확인했어요', { detail: '[목업]' }),
  // 결과 검토: 실제 동작에서는 계획 모델이 도구 결과를 보고 추가 도구(공식 번호 다시 찾기, 복지 더 찾기)를 고른다
  ...runStep('review', '찾은 결과를 보고 더 확인할 것이 있는지 살피고 있어요', '찾은 결과를 보고 더 확인할 것을 정했어요', {
    detail: '[목업] 판단: 필요한 확인을 모두 마쳤어요 | 추가 확인 없음',
  }),
];
const COMPOSE: MockEvent[] = [
  step('compose', '해야 할 일을 정리하고 있어요', 'running', { doneLabel: '해야 할 일을 정리했어요' }),
  step('compose', '해야 할 일을 정리하고 있어요', 'done', { doneLabel: '해야 할 일을 정리했어요', detail: '[목업]' }),
];

/** 같은 id 는 마지막 상태로, 처음 나온 순서대로 (백엔드 finalize_steps 와 같음) */
export function finalizeSteps(steps: AgentStep[]): AgentStep[] {
  const order: string[] = [];
  const last = new Map<string, AgentStep>();
  for (const s of steps) {
    if (!last.has(s.id)) order.push(s.id);
    last.set(s.id, s);
  }
  return order.map((id) => last.get(id)!);
}

function result(
  ctx: ResultContext,
  document: ExtractedDocument,
  explanation: Explanation,
  plan: PlanItem[],
  tools: AnalysisResult['tools'],
  todos: Array<Omit<AnalysisResult['todos'][number], 'id' | 'docId'> & { key: string }>,
): AnalysisResult {
  return {
    docId: ctx.docId,
    document,
    explanation,
    plan,
    tools,
    todos: todos.map(({ key, ...t }) => ({ ...t, id: `${ctx.docId}-${key}`, docId: ctx.docId })),
    steps: finalizeSteps(ctx.steps),
    createdAt: new Date().toISOString(),
  };
}

// ── arrears (기본): 체납이 있는 건강보험료 고지서. 지역 질문 1회 ──
function arrears(): Scenario {
  const dueDate = addDays(5);
  const document: ExtractedDocument = {
    docType: 'health_insurance_bill',
    docTypeLabel: '건강보험료 고지서',
    issuer: '국민건강보험공단',
    fields: { amount: 32500, dueDate, billingMonth: prevMonth(), arrears: 21000, phone: '1577-1000' },
  };
  const plan: PlanItem[] = [
    { tool: 'check_impersonation', reason: '문서에 연락처가 있어 공식 정보와 비교해요', required: true },
    { tool: 'manage_deadline', reason: '문서에 내야 하는 날짜가 있어 기한을 정리해요', required: true },
    { tool: 'search_welfare', reason: '밀린 보험료가 있어 나눠 내기나 지원 제도를 찾아봐요', required: false },
  ];
  const call = { type: 'call', label: '공단에 전화하기', tel: '1577-1000' } as const;
  return {
    asksRegion: true,
    events: [
      ...readAndValidate('건강보험료 고지서예요', 'health_insurance_bill'),
      ...explainAndPlan(plan, '밀린 금액이 포함된 건강보험료 고지서예요'),
      { kind: 'question', question: REGION_QUESTION },
      ...runStep('impersonation', '연락처가 공단 번호가 맞는지 확인하고 있어요', '연락처를 공단 공식 번호와 비교했어요', {
        tool: 'check_impersonation',
        detail: '[목업] seed table hit: 국민건강보험공단 | 판정 match',
      }),
      ...runStep('deadline', '내야 하는 날짜를 확인하고 있어요', '내야 하는 날짜를 확인했어요', { tool: 'manage_deadline' }),
      ...runStep('welfare', '도움 받을 수 있는 제도를 찾고 있어요', '도움 받을 수 있는 제도를 찾았어요', { tool: 'search_welfare', detail: '[목업]' }),
      ...EVALUATE,
      ...COMPOSE,
      {
        kind: 'result',
        build: (ctx) =>
          result(
            ctx,
            document,
            {
              level: 1,
              summaryTemplate: '{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내라는 안내예요.',
              consequences: ['기한이 지나면 돈이 더 붙을 수 있어요.', '밀린 돈은 나눠 낼 수 있는지 물어볼 수 있어요.'],
              terms: [TERMS.납기내금액, TERMS.체납액, { term: '고지 대상 월', plain: '어느 달 몫의 보험료인지', source: 'llm' }],
            },
            plan,
            {
              impersonation: {
                status: 'match',
                checkedValue: '1577-1000',
                officialPhone: '1577-1000',
                officialSource: '국민건강보험공단 공식 홈페이지(nhis.or.kr)',
                redFlags: [],
              },
              deadline: { dueDate, amount: 32500, calendarTitle: '건강보험료 내는 날 (읽어드림)' },
              welfare: {
                items: [
                  {
                    name: '건강보험료 분할납부',
                    summary: '밀린 건강보험료를 한 번에 내기 어려우면 여러 번에 나눠 낼 수 있도록 신청하는 제도예요.',
                    reason: '밀린 보험료가 있어 해당될 수 있어요.',
                    url: 'https://www.nhis.or.kr',
                  },
                  {
                    name: '긴급복지지원',
                    summary: '갑작스러운 위기로 생계가 어려워졌을 때 생계비·의료비 등을 빠르게 지원하는 제도예요.',
                    reason: '생활이 갑자기 어려워졌다면 해당될 수 있어요.',
                    url: 'https://www.bokjiro.go.kr',
                  },
                  MEMBERSHIP,
                ],
                usedProfile: ctx.region !== null,
                fallbackUsed: false,
              },
            },
            // 할 일은 백엔드 5.10절 규칙과 같게 만든다 (내기 / 나눠 내기 문의 / 제도 알아보기)
            [
              {
                key: 'pay',
                title: '건강보험료 내기',
                amount: 32500,
                dueDate,
                actions: [call, { type: 'calendar', label: '달력에 추가하기', title: '건강보험료 내는 날 (읽어드림)', date: dueDate }],
              },
              { key: 'installment', title: '나눠서 낼 수 있는지 물어보기', actions: [call] },
              {
                key: 'welfare',
                title: '도움 받을 수 있는 제도 알아보기',
                actions: [{ type: 'link', label: '홈페이지에서 확인하기', url: 'https://www.nhis.or.kr' }],
              },
            ],
          ),
      },
    ],
    level2: {
      level: 2,
      summaryTemplate: '{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내세요.',
      consequences: ['늦으면 돈이 더 붙어요.', '밀린 돈은 나눠 낼 수 있어요. 물어보세요.'],
      terms: [TERMS.납기내금액, TERMS.체납액, TERMS.분할납부],
    },
  };
}

// ── smishing: 공단 사칭 의심 문자 (단축 주소, 다른 번호) ──
function smishing(): Scenario {
  const document: ExtractedDocument = {
    docType: 'suspicious_message',
    docTypeLabel: '사칭 의심 문자',
    issuer: '국민건강보험공단',
    fields: { amount: 38200, phone: '010-1234-5678', url: 'http://short.example/nhis-refund' },
  };
  const plan: PlanItem[] = [{ tool: 'check_impersonation', reason: '문서에 연락처가 있어 공식 정보와 비교해요', required: true }];
  return {
    asksRegion: false,
    events: [
      ...readAndValidate('사칭 의심 문자예요', 'suspicious_message'),
      ...explainAndPlan(plan, '공단을 사칭한 것으로 의심되는 환급 문자예요'),
      ...runStep('impersonation', '연락처가 공단 번호가 맞는지 확인하고 있어요', '연락처를 공단 공식 번호와 비교했어요', {
        tool: 'check_impersonation',
        detail: '[목업] 근거: rule:mobile, rule:shortener, kisa-002 | 판정 mismatch',
      }),
      ...EVALUATE,
      ...COMPOSE,
      {
        kind: 'result',
        build: (ctx) =>
          result(
            ctx,
            document,
            {
              level: 1,
              summaryTemplate: '{issuer}에서 보냈다고 하는 문자예요.',
              consequences: ['문자 속 주소를 누르면 돈이나 개인정보를 잃을 수 있어요.'],
              terms: [TERMS.환급금, TERMS.단축주소, TERMS.스미싱],
            },
            plan,
            {
              impersonation: {
                status: 'mismatch',
                checkedValue: '010-1234-5678 / http://short.example/nhis-refund',
                officialPhone: '1577-1000',
                officialSource: '국민건강보험공단 공식 홈페이지(nhis.or.kr)',
                redFlags: [
                  '기관이라면서 휴대전화 번호로 연락하라고 해요',
                  '적힌 번호가 공식 번호와 달라요',
                  '짧게 줄인 인터넷 주소가 있어요',
                  '돈을 돌려준다며 인터넷 주소를 누르게 해요',
                ],
              },
            },
            [
              {
                key: 'verify',
                title: '공식 번호로 진짜인지 확인하기',
                actions: [{ type: 'call', label: '공단에 전화하기', tel: '1577-1000' }],
              },
            ],
          ),
      },
    ],
    level2: {
      level: 2,
      summaryTemplate: '{issuer}라고 적힌 문자예요.',
      consequences: ['주소를 누르지 마세요.'],
      terms: [TERMS.단축주소, TERMS.스미싱],
    },
  };
}

// ── local_tax: 체납 없는 지방세 고지서. 질문 없이 진행, 복지 도구 미선택 ──
function localTax(): Scenario {
  const dueDate = addDays(12);
  const document: ExtractedDocument = {
    docType: 'local_tax_bill',
    docTypeLabel: '지방세 고지서',
    issuer: '김해시',
    fields: { amount: 86400, dueDate },
  };
  const plan: PlanItem[] = [{ tool: 'manage_deadline', reason: '문서에 내야 하는 날짜가 있어 기한을 정리해요', required: true }];
  return {
    asksRegion: false,
    events: [
      ...readAndValidate('지방세 고지서예요', 'local_tax_bill'),
      ...explainAndPlan(plan, '체납 없는 지방세 고지서예요'),
      ...runStep('deadline', '내야 하는 날짜를 확인하고 있어요', '내야 하는 날짜를 확인했어요', { tool: 'manage_deadline' }),
      ...EVALUATE,
      ...COMPOSE,
      {
        kind: 'result',
        build: (ctx) =>
          result(
            ctx,
            document,
            {
              level: 1,
              summaryTemplate: '{issuer}에서 보낸 지방세 {amount}을 {dueDate}까지 내라는 안내예요.',
              consequences: ['기한이 지나면 돈이 더 붙을 수 있어요.'],
              terms: [TERMS.납기내금액, TERMS.재산세, TERMS.전자납부번호],
            },
            plan,
            { deadline: { dueDate, amount: 86400, calendarTitle: '지방세 내는 날 (읽어드림)' } },
            [
              {
                key: 'pay',
                title: '지방세 내기',
                amount: 86400,
                dueDate,
                actions: [{ type: 'calendar', label: '달력에 추가하기', title: '지방세 내는 날 (읽어드림)', date: dueDate }],
              },
            ],
          ),
      },
    ],
    level2: {
      level: 2,
      summaryTemplate: '지방세 {amount}을 {dueDate}까지 내세요.',
      consequences: ['늦으면 돈이 더 붙어요.'],
      terms: [TERMS.납기내금액, TERMS.재산세],
    },
  };
}

// ── blurry: 흐린 사진 → 다시 찍기 안내 ──
function blurry(): Scenario {
  return {
    asksRegion: false,
    events: [
      ...runStep('read_text', '사진에서 글자를 읽고 있어요', '글자를 읽었어요', { detail: '[목업] legible=false' }),
      step('validate', '금액과 날짜를 확인하고 있어요', 'failed', {
        doneLabel: '금액과 날짜를 다시 확인했어요',
        detail: '[목업] legible=false → 다시 찍기 안내',
      }),
      {
        kind: 'retake',
        request: { message: '글씨가 잘 안 보여요', tips: ['밝은 곳에서 찍어 주세요', '종이를 평평하게 펴 주세요', '종이 전체가 보이게 찍어 주세요'] },
      },
    ],
  };
}

// ── error: 처리 중 연결 끊김 ──
function error(): Scenario {
  return {
    asksRegion: false,
    events: [
      step('read_text', '사진에서 글자를 읽고 있어요', 'running', { doneLabel: '글자를 읽었어요' }, true),
      step('read_text', '사진에서 글자를 읽고 있어요', 'failed', { doneLabel: '글자를 읽었어요', detail: '[목업] 연결 끊김' }),
      { kind: 'error', error: ERRORS.network },
    ],
  };
}

export const SCENARIO_BUILDERS: Record<ScenarioKey, () => Scenario> = {
  arrears,
  blurry,
  smishing,
  local_tax: localTax,
  error,
};

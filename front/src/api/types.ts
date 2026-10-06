// 데이터 계약 — 프론트 구현지시서 5장, 백엔드 구현지시서 3장과 1:1 대응.
// 화면 코드는 이 타입만 쓴다. 백엔드와 계약이 바뀌면 이 파일과 http/agentApi.ts 만 고친다.

// ── 5.1 문서와 추출 결과 ──
export type DocType =
  | 'health_insurance_bill' // 건강보험료 고지서
  | 'local_tax_bill' // 지방세 고지서
  | 'fine_notice' // 과태료 고지서
  | 'basic_pension_notice' // 기초연금 안내문
  | 'suspicious_message' // 사칭 의심 문자
  | 'unknown';

export interface ExtractedDocument {
  docType: DocType;
  docTypeLabel: string; // 화면 표시용: "건강보험료 고지서"
  issuer: string; // "국민건강보험공단"
  fields: {
    amount?: number; // 원 단위 정수
    dueDate?: string; // 'YYYY-MM-DD'
    billingMonth?: string; // 'YYYY-MM'
    arrears?: number; // 체납액
    phone?: string; // 문서에 적힌 연락처
    url?: string; // 문서에 적힌 주소
  };
}

// ── 5.2 설명 ──
export interface Explanation {
  level: 1 | 2; // 1: 기본, 2: 더 쉬운 설명
  summaryTemplate: string; // "{billingMonth}분 건강보험료 {amount}을 {dueDate}까지 내라는 안내예요."
  consequences: string[]; // 안 하면 생기는 일 (문서 근거 범위 내)
  terms: Array<{
    term: string; // "납기 내 금액"
    plain: string; // "기한 안에 내면 되는 돈"
    source: 'dictionary' | 'llm'; // llm이면 화면에 "참고용 설명" 표시
  }>;
}

// ── 5.3 에이전트 단계와 계획 ──
export type StepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'failed';

export type ToolName = 'check_impersonation' | 'manage_deadline' | 'search_welfare' | 'lookup_terms';

export interface AgentStep {
  id: string;
  label: string; // 사용자용 쉬운 말
  doneLabel?: string; // 완료 시 문구
  status: StepStatus;
  tool?: ToolName; // 확인 과정 보기용
  detail?: string; // 확인 과정 보기용 기술 설명
}

export interface PlanItem {
  tool: ToolName;
  reason: string; // 플래너가 이 도구를 고른 이유
  required: boolean; // 필수 규칙으로 강제된 경우 true
}

// ── 5.4 도구 결과 ──
export interface ImpersonationResult {
  status: 'match' | 'mismatch' | 'unknown';
  checkedValue: string; // 비교한 번호 또는 주소
  officialPhone?: string; // 기관 공식 번호
  officialSource?: string; // 공식 정보 출처 설명
  redFlags: string[]; // "짧게 줄인 인터넷 주소가 있어요" 등
}

export interface DeadlineResult {
  dueDate: string; // 'YYYY-MM-DD'
  amount?: number;
  calendarTitle: string; // 달력에 들어갈 제목
}

export interface WelfareItem {
  name: string; // 제도 이름
  summary: string; // 한두 문장 설명
  reason: string; // 이 사용자에게 안내한 이유
  url: string; // 신청·확인 페이지
}

export interface WelfareResult {
  items: WelfareItem[];
  usedProfile: boolean; // 지역·연령대 정보를 반영했는지
  fallbackUsed: boolean; // API 대신 사본 데이터를 썼는지 (확인 과정 보기에 표시)
}

// ── 5.5 할 일과 실행 버튼 ──
export type TodoAction =
  | { type: 'call'; label: string; tel: string } // "공단에 전화하기"
  | { type: 'link'; label: string; url: string } // "복지로에서 확인하기"
  | { type: 'calendar'; label: string; title: string; date: string };

export interface TodoItem {
  id: string;
  docId: string;
  title: string; // "건강보험료 내기"
  amount?: number;
  dueDate?: string;
  actions: TodoAction[];
  status: 'todo' | 'done';
  createdAt: string; // ISO
  doneAt?: string;
}

// ── 5.6 최종 결과 ──
export interface AnalysisResult {
  docId: string;
  document: ExtractedDocument;
  explanation: Explanation;
  plan: PlanItem[];
  tools: {
    impersonation?: ImpersonationResult;
    deadline?: DeadlineResult;
    welfare?: WelfareResult;
  };
  todos: Omit<TodoItem, 'status' | 'createdAt' | 'doneAt'>[];
  steps: AgentStep[]; // 최종 단계 기록 (확인 과정 보기)
  createdAt: string;
}

// ── 5.7 진행 중 이벤트와 사용자 정보 ──
export interface UserProfile {
  region?: string; // 시·군·구 이름만
  ageGroup?: '60s' | '70s' | '80plus';
}

export interface InfoQuestion {
  field: keyof UserProfile;
  question: string; // "어느 지역에 사세요?"
  options: Array<{ label: string; value: string }>;
}

export interface RetakeRequest {
  message: string; // "글씨가 잘 안 보여요"
  tips: string[]; // ["밝은 곳에서 찍어 주세요", ...]
}

export interface ApiError {
  code: 'network' | 'timeout' | 'server' | 'unsupported_image';
  message: string; // 사용자용 문장
}

// ── 5.8 API 인터페이스 ──
export interface AnalyzeHandlers {
  onStep(step: AgentStep): void; // 같은 id로 여러 번 올 수 있음 (running → done)
  onPlan(plan: PlanItem[]): void;
  onNeedInfo(q: InfoQuestion): void; // 응답 전까지 진행 멈춤
  onNeedRetake(r: RetakeRequest): void; // 세션 종료
  onResult(r: AnalysisResult): void; // 세션 종료
  onError(e: ApiError): void; // 세션 종료
}

export interface AnalyzeSession {
  answer(field: keyof UserProfile, value: string | null): void; // null = 건너뛰기
  cancel(): void;
}

export interface AgentApi {
  analyze(image: Blob, profile: UserProfile, handlers: AnalyzeHandlers): AnalyzeSession;
  simplify(docId: string): Promise<Explanation>; // "더 쉽게 설명해 주세요". 실패하면 ApiError 로 reject
}

// ── 보조 ──
const API_ERROR_CODES: ReadonlyArray<ApiError['code']> = ['network', 'timeout', 'server', 'unsupported_image'];

export function isApiError(value: unknown): value is ApiError {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.message === 'string' && API_ERROR_CODES.includes(v.code as ApiError['code']);
}

export const ERRORS = {
  network: { code: 'network', message: '연결이 잠시 끊겼어요' },
  timeout: { code: 'timeout', message: '확인이 오래 걸리고 있어요. 다시 해 볼까요?' },
  server: { code: 'server', message: '문제가 생겼어요. 다시 해 볼까요?' },
  unsupported_image: { code: 'unsupported_image', message: '이 사진은 열 수 없어요. 카메라로 다시 찍어 주세요' },
} as const satisfies Record<ApiError['code'], ApiError>;

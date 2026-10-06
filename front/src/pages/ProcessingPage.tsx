// 처리 중 (구현지시서 8.4절, 디자인 지시서 6.3절).
// 한 화면이 running / question / retake / error 네 상태를 가진다. 진행 중인 세션이 끊기지 않도록
// 질문·다시 찍기 안내를 별도 라우트로 나누지 않는다.
import { CameraIcon, CheckCircleIcon } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  agentApi,
  type AgentStep,
  type AnalyzeSession,
  type ApiError,
  type InfoQuestion,
  type PlanItem,
  type RetakeRequest,
  type ToolName,
} from '../api';
import { BigButton, TextButton } from '../components/BigButton';
import { Collapsible } from '../components/Collapsible';
import { Page } from '../components/Page';
import { StepList } from '../components/StepList';
import { useCapture } from '../context/CaptureContext';
import { useHistory } from '../context/HistoryContext';
import { useProfile } from '../context/ProfileContext';
import { useTodos } from '../context/TodoContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { usePhotoPicker } from '../hooks/usePhotoPicker';
import styles from './ProcessingPage.module.css';

type ProcessingView =
  | { kind: 'running' }
  | { kind: 'question'; question: InfoQuestion }
  | { kind: 'retake'; request: RetakeRequest }
  | { kind: 'error'; error: ApiError };

/** 계획된 도구 → 단계 id (백엔드 run_tools 의 단계 id 와 같음) */
const TOOL_STEP_IDS: Partial<Record<ToolName, string>> = {
  check_impersonation: 'impersonation',
  manage_deadline: 'deadline',
  search_welfare: 'welfare',
};

/** 계획 단계에서 미리 보여 주는 예정 문구 (Planning 이 화면에 드러나는 지점) */
const PENDING_LABELS: Partial<Record<ToolName, string>> = {
  check_impersonation: '연락처가 공식 번호가 맞는지 확인할게요',
  manage_deadline: '내야 하는 날짜를 확인할게요',
  search_welfare: '도움 받을 수 있는 제도를 찾을게요',
};

function upsertStep(steps: AgentStep[], step: AgentStep): AgentStep[] {
  const index = steps.findIndex((s) => s.id === step.id);
  if (index === -1) return [...steps, step];
  const next = steps.slice();
  next[index] = step;
  return next;
}

function addPlannedSteps(steps: AgentStep[], plan: PlanItem[]): AgentStep[] {
  let next = steps;
  for (const item of plan) {
    const id = TOOL_STEP_IDS[item.tool];
    const label = PENDING_LABELS[item.tool];
    if (!id || !label || next.some((s) => s.id === id)) continue;
    next = [...next, { id, label, status: 'pending', tool: item.tool }];
  }
  return next;
}

export function ProcessingPage() {
  const capture = useCapture();
  const { profile, setField } = useProfile();
  const history = useHistory();
  const { addFromResult } = useTodos();
  const navigate = useNavigate();
  const picker = usePhotoPicker({ replace: true });

  const [view, setView] = useState<ProcessingView>({ kind: 'running' });
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [attempt, setAttempt] = useState(0);
  const heading = usePageHeading(view.kind);

  const session = useRef<AnalyzeSession | null>(null);
  // 효과 안에서 최신 값을 읽기 위한 참조 (세션을 다시 시작하지 않게)
  const latest = useRef({ image: capture.image, profile, history, addFromResult, clear: capture.clear, navigate });
  latest.current = { image: capture.image, profile, history, addFromResult, clear: capture.clear, navigate };

  // 이미지 없이 들어오면 촬영 화면으로 돌려보낸다
  useEffect(() => {
    if (!latest.current.image) navigate('/capture', { replace: true });
  }, [navigate]);

  useEffect(() => {
    const image = latest.current.image;
    if (!image) return;
    let current: AnalyzeSession | null = null;
    // 개발 모드(StrictMode)의 즉시 재실행에서 세션이 두 번 만들어지지 않도록 한 박자 늦춰 시작한다
    const timer = window.setTimeout(() => {
      setSteps([]);
      setView({ kind: 'running' });
      current = agentApi.analyze(image, latest.current.profile, {
        onStep: (step) => {
          setSteps((prev) => upsertStep(prev, step));
          // 질문 대기 시간이 지나 서버가 건너뛰고 진행하면 다시 진행 화면으로
          setView((v) => (v.kind === 'question' ? { kind: 'running' } : v));
        },
        onPlan: (plan) => setSteps((prev) => addPlannedSteps(prev, plan)),
        onNeedInfo: (question) => setView({ kind: 'question', question }),
        onNeedRetake: (request) => setView({ kind: 'retake', request }),
        onError: (error) => setView({ kind: 'error', error }),
        onResult: (result) => {
          const l = latest.current;
          l.history.save(result);
          l.addFromResult(result);
          // 뒤로 가기로 처리 중 화면에 돌아오지 않게 replace
          l.navigate(`/result/${result.docId}`, { replace: true });
          l.clear(); // 처리가 끝나면 이미지를 비운다
        },
      });
      session.current = current;
    }, 0);
    return () => {
      window.clearTimeout(timer);
      current?.cancel();
      session.current = null;
    };
  }, [attempt]);

  const stop = () => {
    session.current?.cancel();
    capture.clear();
    navigate('/', { replace: true });
  };

  const answer = (value: string | null) => {
    if (view.kind !== 'question') return;
    const { field } = view.question;
    if (value !== null) setField(field, value); // 다음에는 묻지 않도록 저장 (Memory)
    session.current?.answer(field, value);
    setView({ kind: 'running' });
  };

  if (view.kind === 'question') {
    const { question } = view;
    return (
      <Page animateKey="question">
        <h1 ref={heading} tabIndex={-1} className="title">
          {question.question}
        </h1>
        <p className={`sub ${styles.lead}`}>도움 받을 수 있는 제도를 찾는 데만 써요. 한 번만 물어볼게요.</p>
        <div className={`stack ${styles.options}`}>
          {question.options.map((option) => (
            <BigButton key={option.value} variant="secondary" onClick={() => answer(option.value)}>
              {option.label}
            </BigButton>
          ))}
        </div>
        <p className={styles.skip}>
          <TextButton onClick={() => answer(null)}>잘 모르겠어요, 건너뛸게요</TextButton>
        </p>
        <Collapsible title="지금까지 확인한 것" small className={styles.sofar}>
          <StepList steps={steps} live={false} />
        </Collapsible>
      </Page>
    );
  }

  if (view.kind === 'retake') {
    return (
      <Page animateKey="retake">
        <h1 ref={heading} tabIndex={-1} className="title">
          {view.request.message}
        </h1>
        <ul className={styles.tips}>
          {view.request.tips.map((tip) => (
            <li key={tip} className={styles.tip}>
              <CheckCircleIcon weight="bold" className={styles.tipIcon} aria-hidden="true" />
              <span>{tip}</span>
            </li>
          ))}
        </ul>
        <div className={`stack ${styles.actions}`}>
          <BigButton icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
            {picker.busy ? '사진을 준비하고 있어요' : '다시 찍기'}
          </BigButton>
        </div>
        {picker.inputs}
      </Page>
    );
  }

  if (view.kind === 'error') {
    const unsupported = view.error.code === 'unsupported_image';
    return (
      <Page animateKey="error">
        <h1 ref={heading} tabIndex={-1} className="title">
          {view.error.message}
        </h1>
        <p className={`sub ${styles.lead}`}>{unsupported ? '다른 사진으로 다시 해 볼 수 있어요' : '같은 사진으로 다시 해 볼 수 있어요'}</p>
        <div className={`stack ${styles.actions}`}>
          {unsupported ? (
            <BigButton icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
              {picker.busy ? '사진을 준비하고 있어요' : '다시 찍기'}
            </BigButton>
          ) : (
            <BigButton onClick={() => setAttempt((a) => a + 1)}>다시 해 보기</BigButton>
          )}
          <BigButton variant="secondary" onClick={stop}>
            처음으로
          </BigButton>
        </div>
        {picker.inputs}
      </Page>
    );
  }

  return (
    <Page animateKey="running">
      <h1 ref={heading} tabIndex={-1} className="title">
        문서를 확인하고 있어요
      </h1>
      <div className={styles.steps}>
        <StepList steps={steps} />
      </div>
      <p className={`small sub ${styles.wait}`}>보통 15초 정도 걸려요</p>
      <div className={`stack ${styles.actions}`}>
        <BigButton variant="secondary" onClick={stop}>
          그만하기
        </BigButton>
      </div>
    </Page>
  );
}

// 처리 단계 목록 — 종이 서식의 체크 칸 (디자인 지시서 5.6절). aria-live="polite".
import type { AgentStep } from '../api/types';
import styles from './StepList.module.css';

const SR_STATUS: Record<AgentStep['status'], string> = {
  done: '끝남',
  running: '지금 하는 중',
  pending: '할 예정',
  failed: '하지 못함',
  skipped: '건너뜀',
};

function stepText(step: AgentStep): string {
  if (step.status === 'done') return step.doneLabel ?? step.label;
  return step.label;
}

function Box({ status }: { status: AgentStep['status'] }) {
  return (
    <span className={`${styles.box} ${styles[status]}`} aria-hidden="true">
      {status === 'done' && (
        <svg viewBox="0 0 20 20" className={styles.check}>
          <path d="M4 10.5 8.5 15 16 5.5" />
        </svg>
      )}
      {status === 'running' && <span className={styles.dot} />}
      {(status === 'failed' || status === 'skipped') && <span className={styles.dash}>–</span>}
    </span>
  );
}

export function StepList({ steps, live = true }: { steps: AgentStep[]; live?: boolean }) {
  return (
    <ol className={styles.list} aria-live={live ? 'polite' : undefined}>
      {steps.map((step) => (
        <li key={step.id} className={`${styles.item} ${styles[`text_${step.status}`]}`}>
          <Box status={step.status} />
          <span className={styles.text}>
            <span className="sr-only">{SR_STATUS[step.status]}: </span>
            {stepText(step)}
            {step.status === 'running' && <span className={styles.runningText}> (확인하는 중)</span>}
            {step.status === 'failed' && <span className={styles.reason}>확인하지 못했어요</span>}
            {step.status === 'skipped' && <span className={styles.reason}>건너뛰었어요</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

// 할 일 카드 (구현지시서 8.6절, 디자인 지시서 5.5절).
// 금액 → 기한 → 행동 순서로 세로로 읽히게 한다. "했어요" 후에는 되돌리기 토스트(5초).
import { ArrowCounterClockwiseIcon, CheckCircleIcon, TrashIcon, WarningOctagonIcon } from '@phosphor-icons/react';
import { useId, useState } from 'react';
import type { TodoItem } from '../api/types';
import { useTodos } from '../context/TodoContext';
import { formatDate, formatDday, formatKRW, formatKRWRaw } from '../lib/format';
import { ActionButton } from './ActionButton';
import { BigButton } from './BigButton';
import { Card } from './Card';
import { Highlight } from './Highlight';
import { useToast } from './Toast';
import styles from './TodoCard.module.css';

interface TodoCardProps {
  todo: TodoItem;
  /** 형광펜 — 한 화면 최대 3곳 규칙에 맞춰 화면이 정한다 */
  highlightAmount?: boolean;
  highlightDday?: boolean;
  headingLevel?: 2 | 3;
}

/** 지울 때 카드가 사라지는 시간 (CSS .leaving 과 같게) */
const LEAVE_MS = 180;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function TodoCard({ todo, highlightAmount = false, highlightDday = false, headingLevel = 3 }: TodoCardProps) {
  const { setStatus, removeDone, restore } = useTodos();
  const [leaving, setLeaving] = useState(false);
  const toast = useToast();
  const titleId = useId();
  const done = todo.status === 'done';
  const dday = todo.dueDate ? formatDday(todo.dueDate) : null;
  const dueText = todo.dueDate ? formatDate(todo.dueDate) : null;
  const overdue = dday?.tone === 'overdue';
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  const raw = todo.amount !== undefined ? formatKRWRaw(todo.amount) : null;

  const markDone = () => {
    setStatus(todo.id, 'done');
    toast.show('끝낸 일로 옮겼어요', { actionLabel: '되돌리기', onAction: () => setStatus(todo.id, 'todo') });
  };
  const markTodo = () => {
    setStatus(todo.id, 'todo');
    toast.show('해야 할 일로 되돌렸어요');
  };
  // 끝낸 일 지우기: 확인 창 대신 되돌리기 알림 (했어요와 같은 방식, 구현지시서 8.6절)
  const remove = () => {
    setLeaving(true);
    window.setTimeout(
      () => {
        const removed = removeDone([todo.id]);
        if (removed.length) toast.show('끝낸 일을 지웠어요', { actionLabel: '되돌리기', onAction: () => restore(removed) });
      },
      prefersReducedMotion() ? 0 : LEAVE_MS,
    );
  };

  return (
    <Card
      as="article"
      stripe={overdue && !done}
      dashed={done}
      labelledBy={titleId}
      className={[done ? styles.done : '', leaving ? styles.leaving : ''].join(' ')}
    >
      <Heading id={titleId} className={styles.title}>
        {done && <CheckCircleIcon weight="bold" className={styles.titleIcon} aria-hidden="true" />}
        {done && <span className="sr-only">끝낸 일: </span>}
        {todo.title}
      </Heading>

      {todo.amount !== undefined && (
        <div className={styles.amountBlock}>
          <p className={`${styles.amount} num`}>{highlightAmount && !done ? <Highlight>{formatKRW(todo.amount)}</Highlight> : formatKRW(todo.amount)}</p>
          {raw && <p className={`${styles.raw} num`}>{raw}</p>}
        </div>
      )}

      {dueText && (
        <div className={styles.dueBlock}>
          <p className={`${styles.due} num`}>{dueText}까지</p>
          {dday && !done && (
            <p className={`${styles.dday} ${styles[dday.tone]} num`}>
              {overdue && <WarningOctagonIcon weight="bold" className={styles.ddayIcon} aria-hidden="true" />}
              {dday.tone === 'soon' && highlightDday ? <Highlight>{dday.text}</Highlight> : dday.text}
            </p>
          )}
        </div>
      )}

      {!done && todo.actions.length > 0 && (
        <div className={styles.actions}>
          {todo.actions.map((action, i) => (
            <ActionButton key={i} action={action} fileBase={todo.title} />
          ))}
        </div>
      )}

      <div className={`${styles.toggle} ${done ? styles.doneButtons : ''}`}>
        {done ? (
          <>
            <BigButton variant="secondary" icon={ArrowCounterClockwiseIcon} onClick={markTodo} disabled={leaving}>
              아직 안 했어요
            </BigButton>
            <BigButton variant="secondary" icon={TrashIcon} onClick={remove} disabled={leaving} ariaLabel={`${todo.title} 지우기`}>
              지우기
            </BigButton>
          </>
        ) : (
          <BigButton variant="ok" icon={CheckCircleIcon} onClick={markDone}>
            했어요
          </BigButton>
        )}
      </div>
    </Card>
  );
}

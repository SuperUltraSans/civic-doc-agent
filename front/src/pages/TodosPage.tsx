// 할 일 목록 (구현지시서 8.6절, 디자인 지시서 6.5절)
import { CameraIcon } from '@phosphor-icons/react';
import { useSearchParams } from 'react-router-dom';
import { BigButton, TextButton } from '../components/BigButton';
import { Collapsible } from '../components/Collapsible';
import { Page } from '../components/Page';
import { TodoCard } from '../components/TodoCard';
import { useToast } from '../components/Toast';
import { useTodos } from '../context/TodoContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { usePhotoPicker } from '../hooks/usePhotoPicker';
import { formatDday } from '../lib/format';
import { sortDone, sortPending } from '../lib/todos';
import styles from './TodosPage.module.css';

const MAX_HIGHLIGHTS = 3;

export function TodosPage() {
  const heading = usePageHeading();
  const { todos, removeDone, restore } = useTodos();
  const [params] = useSearchParams();
  const openDone = params.get('done') === '1'; // 홈의 "끝낸 일 보기"로 들어오면 펼쳐 둔다
  const toast = useToast();
  const picker = usePhotoPicker();
  const pending = sortPending(todos);
  const done = sortDone(todos);

  // 끝낸 일 모두 지우기: 확인 창 대신 되돌리기 알림
  const clearDone = () => {
    const removed = removeDone(done.map((t) => t.id));
    if (removed.length) toast.show(`끝낸 일 ${removed.length}개를 지웠어요`, { actionLabel: '되돌리기', onAction: () => restore(removed) });
  };

  // 형광펜은 한 화면 최대 3곳: 위에서부터 금액, 임박한 남은 일수 순서로 나눠 준다
  let budget = MAX_HIGHLIGHTS;
  const marks = pending.map((todo) => {
    const amount = todo.amount !== undefined && budget > 0 ? (budget--, true) : false;
    const soon = todo.dueDate ? formatDday(todo.dueDate)?.tone === 'soon' : false;
    const dday = soon && budget > 0 ? (budget--, true) : false;
    return { amount, dday };
  });

  return (
    <Page>
      <h1 ref={heading} tabIndex={-1} className="title">
        해야 할 일
      </h1>

      {pending.length > 0 ? (
        <div className={`stack ${styles.list}`}>
          {pending.map((todo, i) => (
            <TodoCard key={todo.id} todo={todo} headingLevel={2} highlightAmount={marks[i].amount} highlightDday={marks[i].dday} />
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          <p>해야 할 일이 없어요</p>
          <div className="stack">
            <BigButton icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
              {picker.busy ? '사진을 준비하고 있어요' : '문서 사진 찍기'}
            </BigButton>
          </div>
          {picker.inputs}
        </div>
      )}

      {done.length > 0 && (
        <div className="section">
          <Collapsible title={`끝낸 일 (${done.length}개)`} defaultOpen={openDone}>
            <div className="stack">
              {done.map((todo) => (
                <TodoCard key={todo.id} todo={todo} />
              ))}
            </div>
            <p className={styles.clearDone}>
              <TextButton danger onClick={clearDone}>
                끝낸 일 모두 지우기
              </TextButton>
            </p>
          </Collapsible>
        </div>
      )}
    </Page>
  );
}

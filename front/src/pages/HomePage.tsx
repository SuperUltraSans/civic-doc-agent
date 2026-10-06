// 홈 (구현지시서 8.2절, 디자인 지시서 6.1절)
import { CameraIcon, ImageIcon } from '@phosphor-icons/react';
import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { BigButton, TextButton } from '../components/BigButton';
import { Highlight } from '../components/Highlight';
import { Page } from '../components/Page';
import { useCapture } from '../context/CaptureContext';
import { useTodos } from '../context/TodoContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { usePhotoPicker } from '../hooks/usePhotoPicker';
import { formatDday } from '../lib/format';
import { sortDone, sortPending } from '../lib/todos';
import topBarStyles from '../components/TopBar.module.css';
import styles from './HomePage.module.css';

export function HomePage() {
  const heading = usePageHeading();
  const picker = usePhotoPicker();
  const { todos } = useTodos();
  const capture = useCapture();
  const pending = sortPending(todos);
  const doneCount = sortDone(todos).length;
  const urgent = pending[0];
  const dday = urgent?.dueDate ? formatDday(urgent.dueDate) : null;

  // 홈으로 돌아오면 촬영 이미지를 비운다 (이미지 비저장 원칙)
  const { clear } = capture;
  useEffect(() => clear(), [clear]);

  return (
    <Page
      back={false}
      title={
        // 홈에는 "뒤로"가 없어 상단 바 왼쪽이 비므로, 서비스 이름(화면 제목)을 그 자리에 둔다
        <h1 ref={heading} tabIndex={-1} className={topBarStyles.title}>
          읽어드림
        </h1>
      }
    >
      <p className="sub">고지서나 안내문을 찍으면 쉬운 말로 알려 드려요</p>

      <div className={`stack ${styles.buttons}`}>
        <BigButton hero icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
          {picker.busy ? '사진을 준비하고 있어요' : '문서 사진 찍기'}
        </BigButton>
        <BigButton variant="secondary" icon={ImageIcon} onClick={picker.openGallery} disabled={picker.busy}>
          사진첩에서 고르기
        </BigButton>
      </div>
      {picker.inputs}

      <section className="section" aria-labelledby="home-todos">
        {urgent ? (
          <>
            <h2 id="home-todos" className="h2">
              해야 할 일이 {pending.length}개 있어요
            </h2>
            <Link to="/todos" className={styles.todoCard}>
              <span className={styles.todoTitle}>{urgent.title}</span>
              {dday && (
                <span className={`${styles.dday} ${dday.tone === 'today' || dday.tone === 'overdue' ? styles.danger : ''} num`}>
                  {dday.tone === 'soon' ? <Highlight>{dday.text}</Highlight> : dday.text}
                </span>
              )}
              <span className={styles.more}>할 일 모두 보기</span>
            </Link>
          </>
        ) : doneCount > 0 ? (
          // 할 일을 모두 끝냈어도 끝낸 일 목록으로 갈 길을 남긴다
          <>
            <h2 id="home-todos" className="h2">
              해야 할 일을 모두 끝냈어요
            </h2>
            <p className={styles.doneLink}>
              <TextButton to="/todos?done=1">끝낸 일 {doneCount}개 보기</TextButton>
            </p>
          </>
        ) : (
          <p id="home-todos">아직 해야 할 일이 없어요. 받은 고지서가 있으면 찍어 보세요.</p>
        )}
      </section>

      <p className={styles.settings}>
        <TextButton to="/settings">설정</TextButton>
      </p>
    </Page>
  );
}

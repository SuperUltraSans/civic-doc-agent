// 상단 바 (디자인 지시서 5.1절): 왼쪽 "뒤로"(홈은 서비스 이름), 오른쪽 "글씨 크기". 스크롤 시 위에 고정.
import { ArrowLeftIcon, TextAaIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSettings } from '../context/SettingsContext';
import styles from './TopBar.module.css';

interface TopBarProps {
  /** false: 뒤로 버튼 없음(홈). 함수: 누를 때 할 일. true: 이전 화면(없으면 홈) */
  back?: boolean | (() => void);
  /** 뒤로 버튼이 없을 때 왼쪽에 두는 제목 (홈의 "읽어드림") */
  title?: ReactNode;
}

export function TopBar({ back = true, title }: TopBarProps) {
  const navigate = useNavigate();
  const { fontLabel, cycleFontScale } = useSettings();

  const goBack = () => {
    if (typeof back === 'function') {
      back();
      return;
    }
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate('/', { replace: true });
  };

  return (
    <header className={styles.bar}>
      <div className={styles.inner}>
        {back ? (
          <button type="button" className={styles.button} onClick={goBack}>
            <ArrowLeftIcon weight="bold" className={styles.icon} aria-hidden="true" />
            <span>뒤로</span>
          </button>
        ) : (
          (title ?? <span />)
        )}
        <button type="button" className={`${styles.button} ${styles.font}`} onClick={cycleFontScale} aria-label={`글씨 크기 바꾸기, 지금은 ${fontLabel}`}>
          <TextAaIcon weight="bold" className={styles.icon} aria-hidden="true" />
          <span className={styles.fontText}>
            <span>글씨 크기</span>
            <span className={styles.level}>{fontLabel}</span>
          </span>
        </button>
      </div>
    </header>
  );
}

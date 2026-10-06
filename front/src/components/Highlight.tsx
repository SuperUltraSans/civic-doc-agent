import type { ReactNode } from 'react';
import styles from './Highlight.module.css';

interface HighlightProps {
  children: ReactNode;
  /** 결과 화면 진입 시 한 번 그어지는 연출 (디자인 지시서 7.1절) */
  draw?: boolean;
  /** 같은 문장 안에서 몇 번째 형광펜인지 (그어지는 시작 시간을 조금씩 늦춘다) */
  order?: number;
}

/** 형광펜 표시. 금액·기한·임박한 남은 일수에만, 한 화면 최대 3곳 (디자인 지시서 4.1절) */
export function Highlight({ children, draw = false, order = 0 }: HighlightProps) {
  return (
    <span
      className={`${styles.highlight} ${draw ? styles.draw : ''}`}
      style={draw ? { animationDelay: `${200 + order * 150}ms` } : undefined}
    >
      {children}
    </span>
  );
}

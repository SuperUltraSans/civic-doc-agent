// 펼치기/접기 (디자인 지시서 5.7절). <details>/<summary> 기반, 제목 줄 전체가 누르는 영역.
import { CaretRightIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import styles from './Collapsible.module.css';

interface CollapsibleProps {
  title: ReactNode;
  children: ReactNode;
  /** 작게 (확인 과정 보기) */
  small?: boolean;
  defaultOpen?: boolean;
  className?: string;
}

export function Collapsible({ title, children, small, defaultOpen, className }: CollapsibleProps) {
  return (
    <details className={`${styles.details} ${small ? styles.small : ''} ${className ?? ''}`} open={defaultOpen}>
      <summary className={styles.summary}>
        {/* 닫힘 ▸ / 열림 ▾ — 화살표 하나가 돌아간다 */}
        <CaretRightIcon weight="bold" className={styles.caret} aria-hidden="true" />
        <span>{title}</span>
      </summary>
      <div className={styles.body}>{children}</div>
    </details>
  );
}

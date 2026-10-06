// 내용 묶음 (디자인 지시서 5.4절). 그림자 없음, 종이 한 장처럼 얇은 테두리만.
import type { ReactNode } from 'react';
import styles from './Card.module.css';

interface CardProps {
  children: ReactNode;
  /** warning: 사칭 의심 등 경고 카드 (왼쪽 빨간 띠 + 옅은 빨강 바탕) */
  tone?: 'normal' | 'warning';
  /** 기한 지난 할 일: 왼쪽 빨간 띠만 */
  stripe?: boolean;
  /** 끝낸 일: 점선 테두리 */
  dashed?: boolean;
  as?: 'div' | 'section' | 'li' | 'article';
  className?: string;
  labelledBy?: string;
}

export function Card({ children, tone = 'normal', stripe, dashed, as: Tag = 'div', className, labelledBy }: CardProps) {
  const cls = [styles.card, tone === 'warning' ? styles.warning : '', stripe ? styles.stripe : '', dashed ? styles.dashed : '', className ?? ''].join(' ');
  return (
    <Tag className={cls} aria-labelledby={labelledBy}>
      {children}
    </Tag>
  );
}

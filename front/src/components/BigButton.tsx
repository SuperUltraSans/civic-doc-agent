// 전체 폭 버튼 (구현지시서 7장, 디자인 지시서 5.2·5.3절). 아이콘은 글자 앞에만.
import type { Icon } from '@phosphor-icons/react';
import type { MouseEventHandler, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import styles from './BigButton.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ok';

interface BigButtonProps {
  children: ReactNode;
  variant?: ButtonVariant;
  icon?: Icon;
  /** 홈 화면 "문서 사진 찍기" 전용: 높이 7rem, 아이콘을 글자 위에 */
  hero?: boolean;
  onClick?: MouseEventHandler<HTMLElement>;
  disabled?: boolean;
  /** 앱 안의 이동 */
  to?: string;
  /** 바깥 주소 (tel: 등) */
  href?: string;
  /** href 를 새 창으로 연다 */
  newTab?: boolean;
  /** 버튼 오른쪽에 작게 붙는 부가 정보 (전화번호 등) */
  aside?: ReactNode;
  ariaLabel?: string;
  className?: string;
}

export function BigButton({ children, variant = 'primary', icon: IconComp, hero, onClick, disabled, to, href, newTab, aside, ariaLabel, className }: BigButtonProps) {
  const cls = [styles.button, styles[variant], hero ? styles.hero : '', className ?? ''].join(' ');
  const content = (
    <>
      {IconComp && <IconComp weight="bold" className={styles.icon} aria-hidden="true" />}
      {aside ? (
        // 좁은 화면·큰 글씨에서는 번호가 문구 아래 줄로 내려간다
        <span className={styles.withAside}>
          <span className={styles.labelText}>{children}</span>
          <span className={styles.aside}>{aside}</span>
        </span>
      ) : (
        <span className={styles.label}>{children}</span>
      )}
    </>
  );
  if (to && !disabled) {
    return (
      <Link to={to} className={cls} onClick={onClick} aria-label={ariaLabel}>
        {content}
      </Link>
    );
  }
  if (href && !disabled) {
    return (
      <a
        href={href}
        className={cls}
        onClick={onClick}
        aria-label={ariaLabel}
        {...(newTab ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      >
        {content}
      </a>
    );
  }
  return (
    <button type="button" className={cls} onClick={onClick} disabled={disabled} aria-label={ariaLabel}>
      {content}
    </button>
  );
}

/** 글자 링크 모양 버튼 (설정, 건너뛰기 등) */
export function TextButton({ children, onClick, to, danger }: { children: ReactNode; onClick?: () => void; to?: string; danger?: boolean }) {
  const cls = `${styles.text} ${danger ? styles.textDanger : ''}`;
  if (to) {
    return (
      <Link to={to} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type="button" className={cls} onClick={onClick}>
      {children}
    </button>
  );
}

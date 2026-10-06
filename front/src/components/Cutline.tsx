// 절취선 — 결과 화면에서 "꼭 하실 일"과 "알아두면 좋은 것"을 나누는 곳 한 군데에만 (디자인 지시서 4.2절).
// 선이 아니라 문장이 의미를 전달하고, 선은 그것을 시각적으로 보강한다.
import { ScissorsIcon } from '@phosphor-icons/react';
import styles from './Cutline.module.css';

export function Cutline() {
  return (
    <div className={styles.wrap}>
      <p className={styles.note}>꼭 하실 일은 여기까지예요</p>
      <div className={styles.line} aria-hidden="true">
        <ScissorsIcon weight="bold" className={styles.scissors} />
      </div>
      <p className={styles.next}>알아두면 좋은 것</p>
    </div>
  );
}

// 개발·시연용 시나리오 선택 (구현지시서 6.3절).
// 개발 모드 또는 ?dev=1 일 때만 화면 왼쪽 아래에 작게 보인다(접힌 상태). 시연 영상 녹화 시에는 ?scenario= 쿼리로만 지정한다.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { USING_MOCK } from '../api';
import { devToolsEnabled, getScenario, SCENARIO_LABELS, SCENARIOS, setScenario, type ScenarioKey } from '../lib/scenario';
import styles from './ScenarioSwitcher.module.css';

export function ScenarioSwitcher() {
  const [value, setValue] = useState<ScenarioKey>(getScenario);
  if (!devToolsEnabled()) return null;
  return (
    <details className={styles.box}>
      <summary className={styles.summary}>개발 · {value}</summary>
      <div className={styles.body}>
        <label htmlFor="dev-scenario" className={styles.label}>
          시나리오 {USING_MOCK ? '(목업)' : '(백엔드)'}
        </label>
        <select
          id="dev-scenario"
          className={styles.select}
          value={value}
          onChange={(e) => {
            const next = e.target.value as ScenarioKey;
            setScenario(next);
            setValue(next);
          }}
        >
          {SCENARIOS.map((key) => (
            <option key={key} value={key}>
              {key} — {SCENARIO_LABELS[key]}
            </option>
          ))}
        </select>
        <Link to="/dev/styleguide" className={styles.link}>
          스타일 가이드
        </Link>
      </div>
    </details>
  );
}

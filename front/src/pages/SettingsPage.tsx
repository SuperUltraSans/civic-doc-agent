// 설정 (구현지시서 8.7절, 디자인 지시서 6.6절)
import { CheckCircleIcon } from '@phosphor-icons/react';
import { useState } from 'react';
import { BigButton, TextButton } from '../components/BigButton';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Page } from '../components/Page';
import { useToast } from '../components/Toast';
import { useHistory } from '../context/HistoryContext';
import { useProfile } from '../context/ProfileContext';
import { FONT_SCALES, useSettings } from '../context/SettingsContext';
import { useTodos } from '../context/TodoContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { useSpeechSupported } from '../hooks/useSpeech';
import { eulReul } from '../lib/korean';
import { AGE_OPTIONS, ageLabel, REGION_OPTIONS, regionLabel } from '../lib/regions';
import styles from './SettingsPage.module.css';

type Editing = 'region' | 'ageGroup' | null;

export function SettingsPage() {
  const heading = usePageHeading();
  const settings = useSettings();
  const { profile, setField, clear: clearProfile } = useProfile();
  const todos = useTodos();
  const history = useHistory();
  const toast = useToast();
  const speechSupported = useSpeechSupported();
  const [editing, setEditing] = useState<Editing>(null);
  const [confirming, setConfirming] = useState(false);

  const savedRows: Array<{ field: 'region' | 'ageGroup'; label: string; value: string | null; options: ReadonlyArray<{ label: string; value: string }> }> = [
    { field: 'region', label: '사는 지역', value: regionLabel(profile.region), options: REGION_OPTIONS },
    { field: 'ageGroup', label: '나이대', value: ageLabel(profile.ageGroup), options: AGE_OPTIONS },
  ];

  const clearAll = () => {
    todos.clear();
    history.clear();
    clearProfile();
    setConfirming(false);
    toast.show('모든 기록을 지웠어요');
  };

  return (
    <Page>
      <h1 ref={heading} tabIndex={-1} className="title">
        설정
      </h1>

      {/* 1. 글씨 크기 — 세로로 쌓인 큰 선택 칸, 각 칸 안에 그 크기로 미리보기 */}
      <fieldset className={`section ${styles.fieldset}`}>
        <legend className="h2">글씨 크기</legend>
        <div className={styles.choices}>
          {FONT_SCALES.map((scale) => {
            const selected = settings.fontScale === scale.value;
            return (
              <label key={scale.value} className={`${styles.choice} ${selected ? styles.selected : ''}`}>
                <input
                  type="radio"
                  name="fontScale"
                  className="sr-only"
                  checked={selected}
                  onChange={() => settings.setFontScale(scale.value)}
                />
                <span className={styles.choiceHead}>
                  <span className={styles.choiceName}>{scale.label}</span>
                  {selected && <CheckCircleIcon weight="bold" className={styles.check} aria-label="선택됨" />}
                </span>
                <span className={styles.preview} style={{ fontSize: `${scale.px}px` }} aria-hidden="true">
                  가나다 이 크기로 보여요
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {/* 2. 결과 자동으로 읽어주기 — 토글 대신 켜기/끄기 두 버튼 중 하나 */}
      {speechSupported && (
        <fieldset className={`section ${styles.fieldset}`}>
          <legend className="h2">결과 자동으로 읽어주기</legend>
          <div className={styles.pair}>
            {[
              { on: true, label: '켜기' },
              { on: false, label: '끄기' },
            ].map(({ on, label }) => {
              const selected = settings.autoSpeak === on;
              return (
                <label key={label} className={`${styles.choice} ${styles.pairChoice} ${selected ? styles.selected : ''}`}>
                  <input type="radio" name="autoSpeak" className="sr-only" checked={selected} onChange={() => settings.setAutoSpeak(on)} />
                  <span className={styles.choiceName}>{label}</span>
                  {selected && <CheckCircleIcon weight="bold" className={styles.check} aria-label="선택됨" />}
                </label>
              );
            })}
          </div>
        </fieldset>
      )}

      {/* 3. 저장된 내 정보 */}
      <section className="section" aria-labelledby="saved-title">
        <h2 id="saved-title" className="h2">
          저장된 내 정보
        </h2>
        <div className={styles.rows}>
          {savedRows.map((row) => (
            <div key={row.field} className={styles.row}>
              <p>
                <span className={styles.rowLabel}>{row.label}</span>
                <br />
                <span className={row.value ? styles.rowValue : 'sub'}>{row.value ?? '아직 없어요'}</span>
              </p>
              {editing === row.field ? (
                <div className="stack" role="group" aria-label={`${row.label} 고르기`}>
                  {row.options.map((option) => (
                    <BigButton
                      key={option.value}
                      variant="secondary"
                      onClick={() => {
                        setField(row.field, option.value);
                        setEditing(null);
                        toast.show(`${eulReul(row.label)} 저장했어요`);
                      }}
                    >
                      {option.label}
                    </BigButton>
                  ))}
                  <TextButton onClick={() => setEditing(null)}>그만둘게요</TextButton>
                </div>
              ) : (
                <div className={styles.rowButtons}>
                  <BigButton variant="secondary" onClick={() => setEditing(row.field)}>
                    {row.value ? '바꾸기' : '알려 주기'}
                  </BigButton>
                  {row.value && (
                    <BigButton
                      variant="secondary"
                      onClick={() => {
                        setField(row.field, null);
                        toast.show(`${eulReul(row.label)} 지웠어요`);
                      }}
                    >
                      지우기
                    </BigButton>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 5. 안내 문구 */}
      <p className={`section ${styles.notice}`}>찍은 사진은 저장하지 않아요. 할 일과 설정은 이 휴대폰에만 저장돼요.</p>

      {/* 4. 모든 기록 지우기 — 화면 맨 아래, 빨간 글자 밑줄 링크. 이 동작만 확인 대화상자 */}
      <p className="section">
        <TextButton danger onClick={() => setConfirming(true)}>
          모든 기록 지우기
        </TextButton>
      </p>
      <ConfirmDialog
        open={confirming}
        title="모든 기록을 지울까요?"
        message="할 일, 결과 기록, 내 정보를 모두 지워요. 지우면 되돌릴 수 없어요."
        confirmLabel="모두 지울게요"
        onConfirm={clearAll}
        onCancel={() => setConfirming(false)}
      />
    </Page>
  );
}

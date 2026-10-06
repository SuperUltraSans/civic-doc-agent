// 결과 (구현지시서 8.5절, 디자인 지시서 6.4절). 중요도 순서로 세로 한 줄 배치, 탭·좌우 넘기기 없음.
// 형광펜은 이 화면에서 요약 안 2곳 + 첫 번째 할 일 카드 금액 1곳, 최대 3곳.
import { MapPinIcon, ShareNetworkIcon } from '@phosphor-icons/react';
import { useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { agentApi, ERRORS, isApiError, type TodoItem } from '../api';
import { ActionButton } from '../components/ActionButton';
import { BigButton } from '../components/BigButton';
import { Card } from '../components/Card';
import { Collapsible } from '../components/Collapsible';
import { Cutline } from '../components/Cutline';
import { ImpersonationNotice } from '../components/ImpersonationNotice';
import { Page } from '../components/Page';
import { SpeakButton } from '../components/SpeakButton';
import { TodoCard } from '../components/TodoCard';
import { useToast } from '../components/Toast';
import { useHistory } from '../context/HistoryContext';
import { useSettings } from '../context/SettingsContext';
import { useTodos } from '../context/TodoContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { useShare } from '../hooks/useShare';
import { agencyShortName, isSafeUrl, linkLabel, TOOL_LABELS } from '../lib/agency';
import type { StoredResult } from '../lib/history';
import { ieyo } from '../lib/korean';
import { fillTemplate, fillTemplateText } from '../lib/template';
import styles from './ResultPage.module.css';

const STATUS_TEXT: Record<string, string> = {
  done: '끝남',
  running: '하는 중',
  pending: '예정',
  failed: '못 함',
  skipped: '건너뜀',
};

/** 요약을 채울 수 없을 때(배포 모드) 대신 보여 주는 숫자 없는 문장 */
function fallbackSummary(result: StoredResult): string {
  return `${ieyo(result.document.docTypeLabel || '문서')}.`;
}

function buildSpeech(result: StoredResult, todoTitles: string[], who: string): string {
  const parts: string[] = [];
  if (result.tools.impersonation?.status === 'mismatch') parts.push(`주의하세요. ${who} 공식 번호와 달라요.`);
  parts.push(fillTemplateText(result.explanation.summaryTemplate, result.document) ?? fallbackSummary(result));
  if (todoTitles.length) parts.push(`꼭 하실 일. ${todoTitles.join('. ')}.`);
  return parts.join(' ');
}

/** 가족에게 보내기 문장 (구현지시서 9.4절). 문서에 적힌 연락처·계좌·주소는 넣지 않는다 */
function buildShareText(result: StoredResult, todoTitles: string[], who: string): string {
  const lines = [`[읽어드림] ${result.document.docTypeLabel} 정리`];
  lines.push(`- ${fillTemplateText(result.explanation.summaryTemplate, result.document) ?? fallbackSummary(result)}`);
  if (result.tools.impersonation?.status === 'mismatch') lines.push(`- 주의: ${who} 공식 번호와 달라요. 적힌 번호로 연락하지 마세요.`);
  if (todoTitles.length) lines.push(`- 해야 할 일: ${todoTitles.join(', ')}`);
  lines.push('읽어드림이 정리한 내용이에요. 정확한 내용은 원래 문서를 확인해 주세요.');
  return lines.join('\n');
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="section" aria-labelledby={id}>
      <h2 id={id} className="h2">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function ResultPage() {
  const { docId = '' } = useParams();
  const history = useHistory();
  const stored = history.get(docId);
  const { todos } = useTodos();
  const { autoSpeak } = useSettings();
  const share = useShare();
  const toast = useToast();
  const navigate = useNavigate();
  const [simplifying, setSimplifying] = useState(false);
  const [draw, setDraw] = useState(true); // 형광펜 긋기는 화면 진입당 한 번만
  const [flash, setFlash] = useState(0);
  const heading = usePageHeading(flash); // 쉬운 설명으로 바뀌면 바뀐 요약으로 포커스를 옮긴다

  const goHome = () => navigate('/', { replace: true });

  if (!stored) {
    return (
      <Page back={goHome}>
        <h1 ref={heading} tabIndex={-1} className="title">
          이 결과를 다시 불러올 수 없어요
        </h1>
        <div className={`stack ${styles.block}`}>
          <BigButton to="/">처음으로</BigButton>
        </div>
      </Page>
    );
  }

  const { document: doc, explanation, tools } = stored;
  const who = agencyShortName(doc.issuer);
  // 할 일 카드는 할 일 목록과 완료 상태가 어긋나지 않도록 TodoContext 에서 찾는다. 지운 할 일은 보여 주지 않는다
  const docTodos: TodoItem[] = stored.todos.flatMap((t) => todos.filter((x) => x.id === t.id));
  const allRemoved = stored.todos.length > 0 && docTodos.length === 0;
  const todoTitles = docTodos.filter((t) => t.status === 'todo').map((t) => t.title);
  const firstAmountId = docTodos.find((t) => t.amount !== undefined && t.status === 'todo')?.id;

  const summary = fillTemplate(explanation.summaryTemplate, doc, { draw, maxHighlights: 2 });
  const consequences = explanation.consequences
    .map((c) => fillTemplate(c, doc, { maxHighlights: 0 }))
    .filter((c): c is ReactNode[] => c !== null);
  const terms = explanation.terms
    .map((t) => ({ ...t, plain: fillTemplate(t.plain, doc, { maxHighlights: 0 }) }))
    .filter((t) => t.plain !== null);
  const welfare = tools.welfare;
  const flashCls = flash ? styles.flash : '';

  const simplify = async () => {
    setSimplifying(true);
    try {
      const next = await agentApi.simplify(docId);
      history.updateExplanation(docId, next);
      setDraw(false);
      setFlash((f) => f + 1);
    } catch (err) {
      toast.show(isApiError(err) ? err.message : ERRORS.server.message);
    } finally {
      setSimplifying(false);
    }
  };

  return (
    <Page back={goHome}>
      {/* 2. 문서 종류와 보낸 곳 — 가운데 점으로 잇지 않고 두 줄 */}
      <p className="small sub">{doc.docTypeLabel}</p>
      {doc.issuer && <p className="small sub">보낸 곳: {doc.issuer}</p>}

      {/* 3. 한 줄 요약 */}
      <h1 ref={heading} tabIndex={-1} key={`summary-${flash}`} className={`${styles.summary} ${flashCls}`}>
        {summary ?? fallbackSummary(stored)}
      </h1>

      {/* 4. 읽어주기 */}
      <div className={styles.block}>
        <SpeakButton text={buildSpeech(stored, todoTitles, who)} autoStart={autoSpeak} />
      </div>

      {/* 6. 사칭 확인 — 상태와 관계없이 읽어주기 바로 아래, 할 일보다 위 */}
      {tools.impersonation && (
        <div className={styles.block}>
          <ImpersonationNotice result={tools.impersonation} who={who} hadPhone={stored.contact.phone || !stored.contact.url} />
        </div>
      )}

      {/* 5. 꼭 해야 할 일 */}
      <Section id="todos-title" title="꼭 하실 일">
        {docTodos.length > 0 ? (
          <div className="stack">
            {docTodos.map((todo) => (
              <TodoCard key={todo.id} todo={todo} highlightAmount={todo.id === firstAmountId} />
            ))}
          </div>
        ) : (
          <p>{allRemoved ? '이 문서의 할 일은 모두 끝내고 지웠어요.' : '따로 하실 일은 없어요.'}</p>
        )}
      </Section>

      <Cutline />

      {/* 7. 안 하면 어떻게 되나요 */}
      {consequences.length > 0 && (
        <section aria-labelledby="cons-title" key={`cons-${flash}`} className={flashCls}>
          <h2 id="cons-title" className="h2">
            안 하면 어떻게 되나요
          </h2>
          <ul className={styles.bullets}>
            {consequences.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      {/* 8. 도움 받을 수 있는 제도 */}
      {welfare && (
        <Section id="welfare-title" title="도움 받을 수 있는 제도">
          <p className="sub">해당될 수 있는 제도예요. 받을 수 있는지는 담당 기관에서 확인해 주세요.</p>
          <div className={`stack ${styles.welfareList}`}>
            {welfare.items.map((item) => (
              <Card key={item.name} as="article">
                <h3 className={styles.itemTitle}>{item.name}</h3>
                <p className={styles.itemText}>{item.summary}</p>
                <p className={`small sub ${styles.itemText}`}>이렇게 안내한 이유: {item.reason}</p>
                {isSafeUrl(item.url) && (
                  <div className={styles.itemAction}>
                    <ActionButton action={{ type: 'link', label: linkLabel(item.url), url: item.url }} />
                  </div>
                )}
              </Card>
            ))}
          </div>
          {!welfare.usedProfile && (
            <div className={styles.regionAsk}>
              <p>사는 지역을 알려 주시면 더 맞는 제도를 찾을 수 있어요</p>
              <BigButton variant="secondary" icon={MapPinIcon} to="/settings">
                사는 지역 알려 주기
              </BigButton>
            </div>
          )}
        </Section>
      )}

      {/* 9. 어려운 말 보기 */}
      {terms.length > 0 && (
        <div className={`section ${flashCls}`} key={`terms-${flash}`}>
          <Collapsible title="어려운 말 보기">
            <dl className={styles.terms}>
              {terms.map((t) => (
                <div key={t.term} className={styles.term}>
                  <dt className={styles.termName}>{t.term}</dt>
                  <dd>
                    {t.plain}
                    {t.source === 'llm' && <span className={styles.llmTag}>참고용 설명</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </Collapsible>
        </div>
      )}

      {/* 10·11. 더 쉽게 설명 / 가족에게 보내기 */}
      <div className="stack section">
        {explanation.level === 1 && (
          <BigButton variant="secondary" onClick={simplify} disabled={simplifying}>
            {simplifying ? '더 쉽게 바꾸고 있어요' : '더 쉽게 설명해 주세요'}
          </BigButton>
        )}
        <BigButton
          variant="secondary"
          icon={ShareNetworkIcon}
          onClick={() => share(`[읽어드림] ${doc.docTypeLabel} 정리`, buildShareText(stored, todoTitles, who))}
        >
          가족에게 보내기
        </BigButton>
      </div>

      {/* 12. 확인 과정 보기 — 시연 시 에이전트 동작을 보여 주는 용도 */}
      <div className="section">
        <Collapsible title="확인 과정 보기" small>
          <h3 className={styles.logTitle}>계획</h3>
          {stored.plan.length > 0 ? (
            <ul className={styles.log}>
              {stored.plan.map((p, i) => (
                <li key={i}>
                  <strong>{TOOL_LABELS[p.tool] ?? p.tool}</strong> (
                  {p.required ? '꼭 하는 확인' : p.reason.startsWith('결과를 보고 추가') ? '결과를 보고 에이전트가 더한 확인' : '에이전트가 고른 확인'})
                  <br />
                  <span className="small">{p.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="small">따로 정한 확인이 없어요.</p>
          )}
          <h3 className={styles.logTitle}>단계 기록</h3>
          <ol className={styles.log}>
            {stored.steps.map((s) => (
              <li key={s.id}>
                <strong>{s.status === 'done' ? (s.doneLabel ?? s.label) : s.label}</strong> ({STATUS_TEXT[s.status] ?? s.status})
                {s.detail && (
                  <>
                    <br />
                    <span className={`small ${styles.detail}`}>{s.detail}</span>
                  </>
                )}
              </li>
            ))}
          </ol>
          {welfare?.fallbackUsed && <p className={`small ${styles.logNote}`}>인터넷 연결 문제로 미리 받아 둔 자료로 찾았어요</p>}
        </Collapsible>
      </div>
    </Page>
  );
}

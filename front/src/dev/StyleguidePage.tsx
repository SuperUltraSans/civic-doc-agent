// 개발 모드 전용 스타일 가이드 (디자인 지시서 9.1절 4번).
// 모든 버튼 종류, 카드, 경고 카드, 할 일 카드(미완료·기한 지남·완료), 단계 목록(각 상태), 형광펜, 절취선을 한 화면에.
// 글씨 크기는 상단 바의 "글씨 크기" 버튼으로 바꿔 본다.
import { CameraIcon, ImageIcon, PhoneIcon } from '@phosphor-icons/react';
import type { AgentStep, TodoItem } from '../api/types';
import { ActionButton } from '../components/ActionButton';
import { BigButton, TextButton } from '../components/BigButton';
import { Card } from '../components/Card';
import { Collapsible } from '../components/Collapsible';
import { Cutline } from '../components/Cutline';
import { Highlight } from '../components/Highlight';
import { ImpersonationNotice } from '../components/ImpersonationNotice';
import { Page } from '../components/Page';
import { StepList } from '../components/StepList';
import { TodoCard } from '../components/TodoCard';
import { useToast } from '../components/Toast';
import { todayYmd } from '../lib/format';

function shift(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return todayYmd(d);
}

const NOW = new Date().toISOString();
const TODOS: TodoItem[] = [
  {
    id: 'sg-1',
    docId: 'sg',
    title: '건강보험료 내기',
    amount: 32500,
    dueDate: shift(5),
    status: 'todo',
    createdAt: NOW,
    actions: [
      { type: 'call', label: '공단에 전화하기', tel: '1577-1000' },
      { type: 'calendar', label: '달력에 추가하기', title: '건강보험료 내는 날 (읽어드림)', date: shift(5) },
    ],
  },
  { id: 'sg-2', docId: 'sg', title: '지방세 내기', amount: 86400, dueDate: shift(2), status: 'todo', createdAt: NOW, actions: [] },
  { id: 'sg-3', docId: 'sg', title: '과태료 내기', amount: 40000, dueDate: shift(-3), status: 'todo', createdAt: NOW, actions: [] },
  { id: 'sg-4', docId: 'sg', title: '나눠서 낼 수 있는지 물어보기', status: 'done', createdAt: NOW, doneAt: NOW, actions: [] },
];

const STEPS: AgentStep[] = [
  { id: 'a', label: '사진에서 글자를 읽고 있어요', doneLabel: '글자를 읽었어요', status: 'done' },
  { id: 'b', label: '연락처가 공단 번호가 맞는지 확인하고 있어요', status: 'running' },
  { id: 'c', label: '도움 받을 수 있는 제도를 찾을게요', status: 'pending' },
  { id: 'd', label: '내야 하는 날짜를 확인하고 있어요', status: 'failed' },
  { id: 'e', label: '복지 제도 찾기', status: 'skipped' },
];

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="section">
      <h2 className="h2">{title}</h2>
      <div className="stack" style={{ marginTop: 'var(--sp-3)' }}>
        {children}
      </div>
    </section>
  );
}

export function StyleguidePage() {
  const toast = useToast();
  return (
    <Page>
      <h1 className="title">스타일 가이드</h1>
      <p className="sub">개발 모드 전용 화면이에요.</p>

      <Block title="버튼">
        <BigButton hero icon={CameraIcon}>
          문서 사진 찍기
        </BigButton>
        <BigButton icon={PhoneIcon}>주요 버튼</BigButton>
        <BigButton variant="secondary" icon={ImageIcon}>
          보조 버튼
        </BigButton>
        <BigButton variant="ok">했어요</BigButton>
        <BigButton disabled>확인하고 있어요</BigButton>
        <ActionButton action={{ type: 'call', label: '공단에 전화하기', tel: '1577-1000' }} />
        <ActionButton action={{ type: 'link', label: '복지로에서 확인하기', url: 'https://www.bokjiro.go.kr' }} />
        <ActionButton action={{ type: 'calendar', label: '달력에 추가하기', title: '건강보험료 내는 날 (읽어드림)', date: shift(5) }} />
        <p>
          <TextButton>글자 링크</TextButton> · <TextButton danger>모든 기록 지우기</TextButton>
        </p>
        <BigButton variant="secondary" onClick={() => toast.show('끝낸 일로 옮겼어요', { actionLabel: '되돌리기', onAction: () => {} })}>
          토스트 보기
        </BigButton>
      </Block>

      <Block title="형광펜">
        <p className="title" style={{ fontSize: 'var(--fs-summary)' }}>
          9월분 건강보험료 <Highlight draw>3만 2,500원</Highlight>을 <Highlight draw order={1}>10월 6일 화요일</Highlight>까지 내라는 안내예요.
        </p>
      </Block>

      <Block title="카드">
        <Card>일반 카드 — 흰 바탕, 얇은 테두리, 그림자 없음</Card>
        <ImpersonationNotice
          result={{ status: 'mismatch', officialPhone: '1577-1000', redFlags: ['짧게 줄인 인터넷 주소가 있어요', '기관이라면서 휴대전화 번호로 연락하라고 해요'] }}
          who="공단"
          hadPhone
        />
        <ImpersonationNotice result={{ status: 'unknown', officialPhone: '1577-1000', redFlags: [] }} who="공단" hadPhone />
        <ImpersonationNotice result={{ status: 'unknown', redFlags: [] }} who="김해시청" hadPhone />
        <ImpersonationNotice result={{ status: 'match', officialPhone: '1577-1000', redFlags: [] }} who="공단" hadPhone />
      </Block>

      <Block title="할 일 카드 (미완료 · 3일 이내 · 기한 지남 · 완료)">
        <TodoCard todo={TODOS[0]} highlightAmount />
        <TodoCard todo={TODOS[1]} highlightDday />
        <TodoCard todo={TODOS[2]} />
        <TodoCard todo={TODOS[3]} />
      </Block>

      <Block title="단계 목록">
        <StepList steps={STEPS} live={false} />
      </Block>

      <Block title="접기">
        <Collapsible title="어려운 말 보기">
          <p>
            <strong>납기 내 금액</strong>
            <br />
            정해진 날까지 내면 되는 돈
          </p>
        </Collapsible>
        <Collapsible title="확인 과정 보기" small>
          <p className="small">작은 접기</p>
        </Collapsible>
      </Block>

      <Cutline />
    </Page>
  );
}

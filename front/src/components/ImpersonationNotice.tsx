// 사칭 확인 결과 (구현지시서 8.5절 6번, 디자인 지시서 5.4·6.4절).
// 문제가 없다는 사실은 작게(한 줄), 문제가 있다는 사실은 크게(경고 카드). 어떤 경우에도 "안전하다"고 말하지 않는다.
import { CheckCircleIcon, PhoneIcon, WarningOctagonIcon } from '@phosphor-icons/react';
import type { ImpersonationResult } from '../api/types';
import { telDigits } from '../lib/format';
import { ActionButton } from './ActionButton';
import { BigButton } from './BigButton';
import { Card } from './Card';
import styles from './ImpersonationNotice.module.css';

interface Props {
  result: Omit<ImpersonationResult, 'checkedValue'>;
  /** 화면 문구용 기관 이름 ("공단") */
  who: string;
  /** 문서에 번호가 적혀 있었는지 (없고 주소만 있었으면 주소 문구를 쓴다) */
  hadPhone: boolean;
}

const GOV_CALL = { tel: '110', label: '정부민원안내콜센터에 전화하기' };
// 같은 뜻을 제목·본문에서 이미 말하는 경고는 목록에서 뺀다
const PHONE_DIFFERS = '적힌 번호가 공식 번호와 달라요';

export function ImpersonationNotice({ result, who, hadPhone }: Props) {
  const official = result.officialPhone;

  if (result.status === 'match') {
    return (
      <p className={styles.match}>
        <CheckCircleIcon weight="bold" className={styles.matchIcon} aria-hidden="true" />
        <span>{hadPhone ? `적힌 번호가 ${who} 공식 번호와 같아요` : `적힌 주소가 ${who} 공식 주소와 같아요`}</span>
      </p>
    );
  }

  if (result.status === 'mismatch') {
    const call = official ? { tel: official, label: `${who} 공식 번호로 전화하기` } : GOV_CALL;
    return (
      <Card as="section" tone="warning" labelledBy="imp-title">
        <h2 id="imp-title" className={styles.warnTitle}>
          <WarningOctagonIcon weight="bold" className={styles.warnIcon} aria-hidden="true" />
          <span>{hadPhone ? `${who} 공식 번호와 달라요` : `${who} 공식 주소가 아니에요`}</span>
        </h2>
        {result.redFlags.length > 0 && (
          <ul className={styles.flags}>
            {result.redFlags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        )}
        <p className={styles.advice}>
          {hadPhone ? '적힌 번호로 연락하지 말고, 공식 번호로 먼저 확인해 보세요.' : '적힌 주소를 누르지 말고, 공식 번호로 먼저 확인해 보세요.'}
        </p>
        <div className={styles.callButton}>
          {/* 경고 상황의 행동 버튼은 빨강이 아니라 침착한 주요 버튼(잉크)으로 둔다 */}
          <BigButton icon={PhoneIcon} href={`tel:${telDigits(call.tel)}`} aside={call.tel} ariaLabel={`${call.label} ${call.tel}`}>
            {call.label}
          </BigButton>
        </div>
      </Card>
    );
  }

  // unknown: 중간 크기 — 일반 카드에 안내 + 대표번호 버튼
  const others = result.redFlags.filter((f) => f !== PHONE_DIFFERS);
  return (
    <Card as="section" labelledBy="imp-title">
      <h2 id="imp-title" className="h2">
        {official ? '공식 대표번호로 확인해 보세요' : '공식 번호를 확인하지 못했어요'}
      </h2>
      <p className={styles.body}>
        {official
          ? hadPhone
            ? '적힌 번호가 공식 대표번호와 달라요. 부서 번호일 수도 있으니 대표번호로 확인해 보세요.'
            : '적힌 주소가 공식 주소인지 알 수 없어요. 대표번호로 확인해 보세요.'
          : '정부민원안내콜센터(110)에 물어보세요.'}
      </p>
      {others.length > 0 && (
        <ul className={styles.flagsPlain}>
          {others.map((flag) => (
            <li key={flag}>{flag}</li>
          ))}
        </ul>
      )}
      <div className={styles.callButton}>
        <ActionButton action={{ type: 'call', ...(official ? { tel: official, label: '대표번호로 전화하기' } : GOV_CALL) }} />
      </div>
    </Card>
  );
}

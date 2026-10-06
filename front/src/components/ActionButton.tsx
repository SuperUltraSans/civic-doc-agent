// 전화·링크·달력 실행 버튼 (구현지시서 7장, 9.5·9.6절).
// 전화: tel: 링크에는 숫자만, 버튼 문구에는 번호도 함께 표시. 링크: 새 창. 달력: .ics 내려받기.
import { CalendarPlusIcon, GlobeIcon, PhoneIcon } from '@phosphor-icons/react';
import type { TodoAction } from '../api/types';
import { isSafeUrl } from '../lib/agency';
import { telDigits } from '../lib/format';
import { downloadIcs } from '../lib/ics';
import { BigButton, type ButtonVariant } from './BigButton';
import { useToast } from './Toast';

interface ActionButtonProps {
  action: TodoAction;
  /** 달력 파일 이름에 쓸 할 일 제목 */
  fileBase?: string;
  variant?: ButtonVariant;
}

export function ActionButton({ action, fileBase, variant = 'secondary' }: ActionButtonProps) {
  const toast = useToast();
  switch (action.type) {
    case 'call': {
      const digits = telDigits(action.tel);
      if (!digits) return null;
      return (
        <BigButton variant={variant} icon={PhoneIcon} href={`tel:${digits}`} aside={action.tel} ariaLabel={`${action.label} ${action.tel}`}>
          {action.label}
        </BigButton>
      );
    }
    case 'link': {
      if (!isSafeUrl(action.url)) return null;
      return (
        <BigButton variant={variant} icon={GlobeIcon} href={action.url} newTab ariaLabel={`${action.label} (새 창)`}>
          {action.label}
        </BigButton>
      );
    }
    case 'calendar':
      return (
        <BigButton
          variant={variant}
          icon={CalendarPlusIcon}
          onClick={() => {
            try {
              downloadIcs({ title: action.title, date: action.date }, fileBase ?? action.title);
              toast.show('달력 파일을 받았어요. 열어서 저장해 주세요');
            } catch {
              toast.show('달력에 넣지 못했어요. 날짜를 직접 적어 두세요');
            }
          }}
        >
          {action.label}
        </BigButton>
      );
    default:
      return null;
  }
}

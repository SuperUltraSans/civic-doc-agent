import { BigButton } from '../components/BigButton';
import { Page } from '../components/Page';
import { usePageHeading } from '../hooks/usePageHeading';

export function NotFoundPage() {
  const heading = usePageHeading();
  return (
    <Page>
      <h1 ref={heading} tabIndex={-1} className="title">
        이 화면은 없어요
      </h1>
      <div className="stack section">
        <BigButton to="/">처음으로</BigButton>
      </div>
    </Page>
  );
}

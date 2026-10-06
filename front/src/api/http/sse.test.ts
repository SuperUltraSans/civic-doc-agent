import { describe, expect, it } from 'vitest';
import { SseParser } from './sse';

describe('SseParser', () => {
  it('이름 있는 이벤트와 주석(ping)', () => {
    const p = new SseParser();
    const out = p.feed(': connected\n\nevent: step\ndata: {"id":"a"}\n\n: ping\n\nevent: result\ndata: {"docId":"d"}\n\n');
    expect(out).toEqual([
      { event: 'step', data: '{"id":"a"}' },
      { event: 'result', data: '{"docId":"d"}' },
    ]);
  });

  it('청크가 중간에서 잘려도 이어 붙인다 (CRLF 포함)', () => {
    const p = new SseParser();
    expect(p.feed('event: pl')).toEqual([]);
    expect(p.feed('an\r')).toEqual([]);
    expect(p.feed('\ndata: [1,')).toEqual([]);
    expect(p.feed('2]\r\n\r\n')).toEqual([{ event: 'plan', data: '[1,2]' }]);
  });

  it('여러 줄 data 는 줄바꿈으로 잇는다', () => {
    const p = new SseParser();
    expect(p.feed('data: a\ndata: b\n\n')).toEqual([{ event: 'message', data: 'a\nb' }]);
  });
});

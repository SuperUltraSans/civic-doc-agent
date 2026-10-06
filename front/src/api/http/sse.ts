// text/event-stream 파서. EventSource 대신 fetch 스트림을 쓰는 이유:
// EventSource 는 끊기면 스스로 다시 연결하는데, 백엔드는 다시 연결되면 버퍼를 처음부터 보내므로
// 단계 이벤트가 두 번 들어온다. fetch 는 끊김을 직접 감지해 오류 화면으로 넘길 수 있다.

export interface SseMessage {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = '';
  private event = '';
  private data: string[] = [];

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    for (;;) {
      const match = /\r\n|\r|\n/.exec(this.buffer);
      if (!match) break;
      // 청크가 '\r' 로 끝나면 다음 청크의 '\n' 과 한 줄바꿈일 수 있으므로 기다린다
      if (match[0] === '\r' && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      this.line(line, out);
    }
    return out;
  }

  private line(line: string, out: SseMessage[]): void {
    if (line === '') {
      if (this.data.length > 0) out.push({ event: this.event || 'message', data: this.data.join('\n') });
      this.event = '';
      this.data = [];
      return;
    }
    if (line.startsWith(':')) return; // 주석 (": ping")
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.event = value;
    else if (field === 'data') this.data.push(value);
  }
}

import assert from 'node:assert/strict';
import { postJsonNative, ProviderError, RequestAborted, streamMercury } from '../src/engine/providers';

class FakeXHR {
  static latest: FakeXHR;
  readyState = 0;
  status = 200;
  statusText = '';
  responseText = '';
  timeout = 0;
  aborted = false;
  onreadystatechange: (() => void) | null = null;
  onprogress: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() { FakeXHR.latest = this; }
  open() { this.readyState = 1; }
  setRequestHeader() {}
  send() {}
  abort() { this.aborted = true; this.onabort?.(); }
  chunk(text: string) { this.readyState = 3; this.responseText += text; this.onprogress?.(); }
  end(text = '') { this.responseText += text; this.readyState = 4; this.onreadystatechange?.(); }
}

async function main() {
  const original = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest;
  try {
    const events: unknown[] = [];
    const response = streamMercury('https://provider.example', 'test', {}, {
      timeoutMs: 1000, onData: (data) => events.push(data),
    });
    const socket = FakeXHR.latest;
    socket.chunk('data: {"choices":[{"delta":{"content":"An');
    socket.chunk(' answer"}}]}\r\n\r\n');
    socket.chunk('data: {"usage":{"total_tokens":12}}\n\ndata: [DO');
    socket.chunk('NE]');
    await response;
    assert.equal(events.length, 2, 'fragmented frames and usage are retained');
    assert.equal(socket.readyState, 3, 'completion must not wait for HTTP EOF');
    assert.equal(socket.aborted, true, 'terminal marker releases the live socket');
    assert.equal(socket.onprogress, null, 'late network callbacks are detached');

    const broken = streamMercury('https://provider.example', 'test', {}, {
      timeoutMs: 1000, onData: () => { throw new ProviderError(503, 'stream failed'); },
    });
    FakeXHR.latest.end('data: {"error":"failed"}');
    await assert.rejects(broken, (error: unknown) => error instanceof ProviderError && error.status === 503,
      'errors in an unterminated final frame must not be swallowed');

    const controller = new AbortController();
    const stopped = streamMercury('https://provider.example', 'test', {}, {
      timeoutMs: 1000, signal: controller.signal, onData: () => {},
    });
    controller.abort();
    await assert.rejects(stopped, RequestAborted);

    const timed = streamMercury('https://provider.example', 'test', {}, {
      timeoutMs: 20, onData: () => {},
    });
    await assert.rejects(timed, (error: unknown) => error instanceof ProviderError && /time/.test(error.message),
      'missing native timeout callbacks cannot leave the turn pending');
    assert.equal(FakeXHR.latest.aborted, true);

    const search = postJsonNative('https://provider.example/search', 'test', {}, undefined, 1000);
    const searchSocket = FakeXHR.latest;
    assert.equal(searchSocket.timeout, 1000, 'retrieval also has a native networking deadline');
    searchSocket.end('{"results":[{"title":"A result"}]}');
    assert.deepEqual(await search, { results: [{ title: 'A result' }] });
    const stalledSearch = postJsonNative('https://provider.example/search', 'test', {}, undefined, 1000);
    FakeXHR.latest.ontimeout?.();
    await assert.rejects(stalledSearch, ProviderError, 'native timeout resolves a stalled parallel search');
    assert.equal(FakeXHR.latest.aborted, true);

    const disconnected = streamMercury('https://provider.example', 'test', {}, {
      timeoutMs: 1000, onData: () => {},
    });
    FakeXHR.latest.status = 0;
    FakeXHR.latest.end();
    await assert.rejects(disconnected, ProviderError);
    console.log('Provider terminal-stream, cancellation and deadline checks passed.');
  } finally {
    globalThis.XMLHttpRequest = original;
  }
}
void main();

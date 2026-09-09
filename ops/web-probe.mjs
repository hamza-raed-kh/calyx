// Drives headless Chrome over CDP and reads the persistence probe the app
// publishes into the DOM. Flutter paints to a canvas, so this is the only way
// to observe which storage tier the browser actually resolved to.
const CDP = process.env.CDP || 'http://127.0.0.1:9222';
const URL_ = process.env.TARGET || 'https://localhost/';
const DEADLINE = Date.now() + 60_000;

const target = await (await fetch(`${CDP}/json/new?${encodeURIComponent(URL_)}`, { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let id = 0;
const pending = new Map();
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
};
const send = (method, params = {}) =>
  new Promise((res) => { const n = ++id; pending.set(n, res); ws.send(JSON.stringify({ id: n, method, params })); });

const evaluate = (expr) =>
  send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: false });

while (Date.now() < DEADLINE) {
  const r = await evaluate(
    "(() => { const n = document.getElementById('drift-persistence'); return n ? n.textContent : null; })()"
  );
  const value = r?.result?.result?.value;
  if (value) {
    console.log(value);
    ws.close();
    process.exit(0);
  }
  await new Promise((r2) => setTimeout(r2, 500));
}

// Nothing published: report what the page thinks it is, so the failure is
// diagnosable rather than just a timeout.
const ctx = await evaluate(
  "JSON.stringify({isSecureContext:self.isSecureContext,crossOriginIsolated:self.crossOriginIsolated,url:location.href,title:document.title})"
);
console.error('probe never published. page context:', ctx?.result?.result?.value ?? '(no result)');
ws.close();
process.exit(1);

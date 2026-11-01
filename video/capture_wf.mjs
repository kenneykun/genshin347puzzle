/**
 * 世界式动效采集（v2）：用鼠标拖拽事件精确驱动相机 yaw，逐帧 1px → 每帧 0.355°，
 * 帧帧都是新姿态，不会像之前那样「抓 8fps 再重采样」导致掉帧。
 *
 * 页面里拖拽一次 dx 让 cam.yaw += dx * 0.0062 rad，所以：
 *   每帧向右拖 1px = 0.0062 rad = 0.355°/帧 = 10.7°/s（30fps 播放）
 *
 * 用法： node video/capture_wf.mjs [帧数]     （默认 560 帧 ≈ 18.7s）
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const VIDEO = resolve(new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const REPO_DOCS = resolve(VIDEO, '..', 'repo', 'docs');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9338;
const PROFILE = join(VIDEO, 'build', 'chrome-prof-wf');
const OUT = join(VIDEO, 'build', 'clips', 'wf');
const W = 1080, H = 1920;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitPort() {
  for (let i = 0; i < 200; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return;
    } catch { /* wait */ }
    await sleep(250);
  }
  throw new Error('no devtools');
}

function cdp(ws) {
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    }
  });
  return (method, params = {}) => new Promise((res, rej) => {
    const i = ++id; pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
}

const evaluate = async (send, expression, awaitPromise = false) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise });
  if (r && r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r && r.result ? r.result.value : undefined;
};

const rafWait = `new Promise(r=>{requestAnimationFrame(()=>requestAnimationFrame(()=>r(1)))})`;

async function main() {
  const frames = Number(process.argv[2] || 560);
  mkdirSync(OUT, { recursive: true });
  for (const f of readdirSync(OUT)) if (f.endsWith('.jpg')) rmSync(join(OUT, f), { force: true });
  if (existsSync(PROFILE) && resolve(PROFILE).startsWith(resolve(VIDEO, 'build'))) {
    rmSync(PROFILE, { recursive: true, force: true });
  }

  const chrome = spawn(CHROME, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--enable-unsafe-swiftshader',
    '--hide-scrollbars', '--allow-file-access-from-files',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    `--window-size=${W},${H}`, 'about:blank',
  ], { stdio: 'ignore' });

  try {
    await waitPort();
    const created = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
    const ws = new WebSocket(created.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const send = cdp(ws);

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    const url = 'file:///' + join(REPO_DOCS, 'world_formula.html').replace(/\\/g, '/') + '?embed=1';
    await send('Page.navigate', { url });
    for (let i = 0; i < 200; i++) {
      if (await evaluate(send, 'document.readyState === "complete"')) break;
      await sleep(200);
    }
    await sleep(2600);
    await evaluate(send, `(() => { const z = document.getElementById('zoomOut');
      if (z) for (let i = 0; i < 5; i++) z.click(); return 1; })()`);
    await sleep(700);

    // 按住舞台开始拖拽
    const X0 = 520, Y0 = 900;
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: X0, y: Y0, button: 'left', buttons: 1, clickCount: 1 });
    await evaluate(send, rafWait, true);

    for (let i = 0; i < frames; i++) {
      await send('Input.dispatchMouseEvent', {
        type: 'mouseMoved', x: X0 + i, y: Y0, button: 'left', buttons: 1, clickCount: 1,
      });
      await evaluate(send, rafWait, true);
      const { data } = await send('Page.captureScreenshot', { format: 'jpeg', quality: 92, optimizeForSpeed: true });
      writeFileSync(join(OUT, `f${String(i).padStart(4, '0')}.jpg`), Buffer.from(data, 'base64'));
      if (i % 60 === 0) console.log(`  wf ${i}/${frames}`);
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: X0 + frames, y: Y0, button: 'left', buttons: 0, clickCount: 1 });
    console.log('OK clip wf', frames, 'frames ->', OUT);
    ws.close();
  } finally {
    chrome.kill();
  }
}

main().catch((e) => { console.error('FAILED', e.message); process.exit(1); });

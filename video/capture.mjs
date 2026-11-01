/**
 * CDP 采集：站点静帧 + 版式页 + 透明字幕层
 *
 * 用法：
 *   node video/capture.mjs site          只抓站点素材（assets/a1..a6.png）
 *   node video/capture.mjs pages         只抓版式页与字幕层
 *   node video/capture.mjs all           全抓
 *
 * 产物：
 *   video/assets/a1..a6.png
 *   video/build/pages/<id>.png       2160x3840
 *   video/build/subs/subNN.png       2160x3840 透明
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const VIDEO = resolve(new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const REPO_DOCS = resolve(VIDEO, '..', 'repo', 'docs');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9333;
const PROFILE = join(VIDEO, 'build', 'chrome-prof');
const ASSETS = join(VIDEO, 'assets');
const PAGES_OUT = join(VIDEO, 'build', 'pages');
const SUBS_OUT = join(VIDEO, 'build', 'subs');
const OVERLAY_OUT = join(VIDEO, 'build', 'overlays');
const CAPTION_OUT = join(VIDEO, 'build', 'captions');
const SLIDES = join(VIDEO, 'slides.html');

const MODE = process.argv[2] || 'all';
const only = process.argv[3];

const fileUrl = (p, hash = '', query = '') => {
  let u = 'file:///' + p.replace(/\\/g, '/');
  if (query) u += query;
  if (hash) u += '#' + hash;
  return u;
};

/* 站点素材：机位沿用 plan §4 */
const SITE_JOBS = [
  { name: 'a1', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    w: 2160, h: 2160, kind: 'site',
    cam: [0.9, 8.4, 6.6, 0, -0.6, 0] },
  { name: 'a2', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    w: 2160, h: 2160, kind: 'site',
    cam: [0.9, 5.9, 4.6, 0, 0.25, -0.2] },
  { name: 'a3', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    w: 2160, h: 2160, kind: 'site',
    cam: [0.7, 4.7, 2.3, 0, 0.05, -0.2] },
  { name: 'a4', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    w: 2160, h: 2160, kind: 'site',
    cam: [2.5, 5.3, 2.9, 0.2, 0.05, 0] },
  { name: 'a5', file: 'world_formula.html', query: '?embed=1&still=1',
    w: 2160, h: 2880, kind: 'world' },
  { name: 'a6', file: 'prism_three_planb.html', query: '?still=1',
    w: 2160, h: 3840, kind: 'site-ui' },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitPort(timeoutMs = 45000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch { /* not up yet */ }
    await sleep(300);
  }
  throw new Error('chrome devtools port not ready');
}

function cdpClient(ws) {
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
    }
  });
  return (method, params = {}) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
}

async function withPage(w, h, transparent, fn) {
  const created = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(created.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const send = cdpClient(ws);
  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    if (transparent) {
      await send('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });
    }
    return await fn(send);
  } finally {
    try { ws.close(); } catch { }
    try { await fetch(`http://127.0.0.1:${PORT}/json/close/${created.id}`); } catch { }
  }
}

const evaluate = async (send, expression, awaitPromise = false) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise });
  return r && r.result ? r.result.value : undefined;
};

async function pollTrue(send, expression, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (await evaluate(send, expression)) return true;
    await sleep(250);
  }
  throw new Error('timeout waiting ' + label);
}

const rafWait = `new Promise(r=>{let n=0;const f=()=>{ if(++n>=3) r(1); else requestAnimationFrame(f); }; requestAnimationFrame(f);})`;

async function shoot(send, out) {
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, fromSurface: true });
  writeFileSync(out, Buffer.from(data, 'base64'));
}

async function captureSite(job) {
  const url = fileUrl(join(REPO_DOCS, job.file), '', job.query);
  const out = join(ASSETS, job.name + '.png');
  await withPage(job.w, job.h, false, async (send) => {
    await send('Page.navigate', { url });
    if (job.kind === 'site') {
      await pollTrue(send, '!!window.__dbg', 90000, job.name + ' __dbg');
      if (job.cam) {
        const [x, y, z, tx, ty, tz] = job.cam;
        const expr = `(()=>{const d=window.__dbg;if(!d)return 'no';
          const st=document.createElement('style');
          st.textContent='body > *:not(#scene){display:none!important}';
          document.head.appendChild(st);
          d.state.running=false;
          d.camera.position.set(${x},${y},${z});
          d.controls.target.set(${tx},${ty},${tz});
          d.controls.update();
          d.camera.lookAt(${tx},${ty},${tz});
          return 'ok';})()`;
        const r = await evaluate(send, expr);
        if (r !== 'ok') throw new Error('camera set failed: ' + r);
      }
      await pollTrue(send, '!document.getElementById("loading")', 90000, job.name + ' loader-gone');
      await evaluate(send, rafWait, true);
      await sleep(700);
    } else if (job.kind === 'site-ui') {
      await pollTrue(send, 'document.readyState==="complete"', 60000, job.name + ' load');
      await pollTrue(send, '!document.getElementById("loading")', 90000, job.name + ' loader-gone');
      await evaluate(send, rafWait, true);
      await sleep(900);
    } else {
      await pollTrue(send, 'document.readyState==="complete"', 60000, job.name + ' load');
      await sleep(2200);
    }
    await shoot(send, out);
  });
  console.log('OK  site ', job.name, '->', out);
}

async function capturePage(id, transparent, subOut) {
  const out = join(subOut, id + '.png');
  const url = fileUrl(SLIDES, id, transparent || id[0] === 'o' ? '' : '?nosub=1');
  await withPage(2160, 3840, transparent, async (send) => {
    await send('Page.navigate', { url });
    await pollTrue(send, 'document.documentElement.dataset.ready==="1"', 45000, id + ' ready');
    await sleep(220);
    await shoot(send, out);
  });
  console.log('OK  page ', id, '->', out);
}

async function main() {
  for (const d of [ASSETS, PAGES_OUT, SUBS_OUT, OVERLAY_OUT, CAPTION_OUT, join(VIDEO, 'build')]) mkdirSync(d, { recursive: true });
  if (existsSync(PROFILE) && resolve(PROFILE).startsWith(resolve(VIDEO, 'build'))) {
    rmSync(PROFILE, { recursive: true, force: true });
  }

  const chrome = spawn(CHROME, [
    '--headless=new', '--no-sandbox', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
    '--hide-scrollbars', '--allow-file-access-from-files',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--window-size=1080,1920', 'about:blank',
  ], { stdio: 'ignore' });

  try {
    await waitPort();
    if (MODE === 'site' || MODE === 'all') {
      for (const job of SITE_JOBS) {
        if (only && job.name !== only) continue;
        await captureSite(job);
      }
    }
    if (MODE === 'pages' || MODE === 'all') {
      const pages = readFileSync(join(VIDEO, 'build', 'pages.txt'), 'utf8').split(/\r?\n/).filter(Boolean);
      for (const id of pages) await capturePage(id, false, PAGES_OUT);
      const subs = readFileSync(join(VIDEO, 'build', 'subs.txt'), 'utf8').split(/\r?\n/).filter(Boolean);
      for (const id of subs) await capturePage(id, true, SUBS_OUT);
      const overlays = readFileSync(join(VIDEO, 'build', 'overlays.txt'), 'utf8').split(/\r?\n/).filter(Boolean);
      for (const id of overlays) await capturePage(id, true, OVERLAY_OUT);
      const caps = readFileSync(join(VIDEO, 'build', 'captions.txt'), 'utf8').split(/\r?\n/).filter(Boolean);
      for (const id of caps) await capturePage(id, true, CAPTION_OUT);
    }
    console.log('DONE');
  } finally {
    chrome.kill();
  }
}

main().catch((e) => { console.error('FAILED', e.message); process.exit(1); });

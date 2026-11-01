/**
 * 3D 动效采集：把站点 WebGL 场景按「确定性的 30fps 帧序列」录下来。
 *
 * 做法：
 *   1. 覆盖 performance.now()，让页面时间只在我拨动 __vt 时前进（每个 rAF 的 dt 精确等于 1/30s）；
 *   2. 每帧先拨时间和相机球坐标，等一帧渲染，再截图；
 *   3. 输出 1080×1920 JPEG 序列，交给 render.py 当底片用。
 *
 * 用法：
 *   node video/capture_clips.mjs             全部片段
 *   node video/capture_clips.mjs pan 90      只录 pan，且只录 90 帧（调试用）
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const VIDEO = resolve(new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const REPO_DOCS = resolve(VIDEO, '..', 'repo', 'docs');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9334;
const PROFILE = join(VIDEO, 'build', 'chrome-prof-clip');
const OUT = join(VIDEO, 'build', 'clips');
const SLIDES = join(VIDEO, 'slides.html');
const PAGES = join(VIDEO, 'build', 'pages');
const FPS = 30;
const W = 1080, H = 1920;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const fileUrl = (p, hash = '', query = '') =>
  'file:///' + p.replace(/\\/g, '/') + (query || '') + (hash ? '#' + hash : '');

/* 片段定义：球坐标机位，azimuth/elevation 从起点线性走到终点 */
const CLIPS = {
  pan: {                                   // 镜 2 / 镜 9a：全景缓慢环绕
    kind: 'site', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    frames: 260, running: true, hidePlate: true,
    cam: { r0: 13.6, r1: 12.6, az0: 3, az1: 33, el0: 51, el1: 46, target: [0, 0.45, 0] },
  },
  seat: {                                  // 镜 4：座位特写缓慢横移 + 抬升
    kind: 'site', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    frames: 300, running: true, hidePlate: true,
    cam: { r0: 11.2, r1: 10.2, az0: -18, az1: 6, el0: 47, el1: 53, target: [0, 1.15, -0.2] },
  },
  plate: {                                 // 镜 5：电盘特写，缓慢俯冲
    kind: 'site', file: 'prism_three_planb.html', query: '?visual=1&still=1&debug=1',
    frames: 200, running: true,
    cam: { r0: 7.2, r1: 6.0, az0: 6, az1: 26, el0: 56, el1: 47, target: [0, 0.15, -0.15] },
  },
  ui: {                                    // 镜 9b：带侧栏的站点定格（只用实时动效，不藏 UI）
    kind: 'ui', file: 'prism_three_planb.html', query: '?still=1&debug=1',
    frames: 200, running: true, hidePlate: true,
    cam: { r0: 11.6, r1: 11.0, az0: 8, az1: 24, el0: 49, el1: 45, target: [0, 0.35, 0] },
  },
};

async function waitPort(timeoutMs = 45000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return;
    } catch { /* not up */ }
    await sleep(250);
  }
  throw new Error('devtools not ready');
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

async function pollTrue(send, expr, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (await evaluate(send, expr)) return;
    await sleep(200);
  }
  throw new Error('timeout ' + label);
}

const rafWait = `new Promise(r=>{const f=()=>r(1);requestAnimationFrame(f);requestAnimationFrame(f);})`;

async function recordClip(name, spec, frameOverride) {
  const frames = frameOverride || spec.frames;
  const dir = join(OUT, name);
  mkdirSync(dir, { recursive: true });
  const created = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(created.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const send = cdp(ws);
  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: fileUrl(join(REPO_DOCS, spec.file), '', spec.query) });

    if (spec.kind === 'site') {
      await pollTrue(send, '!!window.__dbg', 90000, name + ' __dbg');
      await pollTrue(send, '!document.getElementById("loading")', 90000, name + ' loader');
      await evaluate(send, `(()=>{
        const st=document.createElement('style');
        st.textContent='body > *:not(#scene){display:none!important}';
        document.head.appendChild(st);
        return 1;})()`);
    } else {
      await pollTrue(send, 'document.readyState==="complete"', 60000, name + ' load');
      await pollTrue(send, '!document.getElementById("loading")', 90000, name + ' loader');
    }

    // 覆盖虚拟时钟 + 初始化相机
    await evaluate(send, `(()=>{
      const d = window.__dbg;
      const realNow = performance.now.bind(performance);
      const base = realNow();
      window.__vt = 0;
      performance.now = () => base + window.__vt;
      if (d) {
        d.scene.traverse((o) => { if (o.isPoints) o.visible = false; });
        // 四影标签（生·燃烧·绽放 / 空·扩散 / 时·结晶）在 3D 镜头里是噪音，隐藏那一组
        d.scene.traverse((o) => {
          if (!o.isGroup || o.children.length !== 6) return;
          const isZoneGroup = o.children.every((c) => {
            const img = c.material && c.material.map && c.material.map.image;
            return c.isSprite && img && img.width > 128 && img.height === 64;
          });
          if (isZoneGroup) o.visible = false;
        });
        if (${spec.hidePlate ? 'true' : 'false'} && d.plate) d.plate.visible = false;
        d.state.running = ${spec.running ? 'true' : 'false'};
        if ('autoOrbit' in d.state) d.state.autoOrbit = false;
        if (d.controls) { d.controls.autoRotate = false; d.controls.enableDamping = false; }
      }
      window.__setCam = (r, azDeg, elDeg, tg) => {
        const az = azDeg * Math.PI / 180, el = elDeg * Math.PI / 180;
        const x = tg[0] + r * Math.cos(el) * Math.sin(az);
        const y = tg[1] + r * Math.sin(el);
        const z = tg[2] + r * Math.cos(el) * Math.cos(az);
        const c = window.__dbg.camera, o = window.__dbg.controls;
        c.position.set(x, y, z);
        o.target.set(tg[0], tg[1], tg[2]);
        o.update();
        c.lookAt(tg[0], tg[1], tg[2]);
      };
      return 1;})()`);

    const { r0, r1, az0, az1, el0, el1, target } = spec.cam;
    for (let i = 0; i < frames; i++) {
      const p = frames > 1 ? i / (frames - 1) : 0;
      const r = r0 + (r1 - r0) * p;
      const az = az0 + (az1 - az0) * p;
      const el = el0 + (el1 - el0) * p;
      await evaluate(send, `(()=>{ window.__vt = ${(i * 1000 / FPS).toFixed(3)};
        ${spec.kind === 'site' || spec.kind === 'ui' ? `window.__setCam(${r},${az},${el},${JSON.stringify(target)});` : ''}
        return 1; })()`);
      await evaluate(send, rafWait, true);
      const { data } = await send('Page.captureScreenshot', { format: 'jpeg', quality: 90, optimizeForSpeed: true });
      writeFileSync(join(dir, `f${String(i).padStart(4, '0')}.jpg`), Buffer.from(data, 'base64'));
      if (i % 40 === 0) console.log(`  ${name} ${i}/${frames}`);
    }
    console.log('OK clip', name, frames, 'frames ->', dir);
  } finally {
    try { ws.close(); } catch { }
    try { await fetch(`http://127.0.0.1:${PORT}/json/close/${created.id}`); } catch { }
  }
}

async function main() {
  for (const d of [OUT, join(VIDEO, 'build')]) mkdirSync(d, { recursive: true });
  if (existsSync(PROFILE) && resolve(PROFILE).startsWith(resolve(VIDEO, 'build'))) {
    rmSync(PROFILE, { recursive: true, force: true });
  }
  const only = process.argv[2];
  const frameOverride = process.argv[3] ? Number(process.argv[3]) : 0;

  const chrome = spawn(CHROME, [
    '--headless=new', '--no-sandbox', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
    '--hide-scrollbars', '--allow-file-access-from-files',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    `--window-size=${W},${H}`, 'about:blank',
  ], { stdio: 'ignore' });

  try {
    await waitPort();
    for (const [name, spec] of Object.entries(CLIPS)) {
      if (only && name !== only) continue;
      await recordClip(name, spec, frameOverride);
    }
    console.log('DONE');
  } finally {
    chrome.kill();
  }
}

main().catch((e) => { console.error('FAILED', e.message); process.exit(1); });

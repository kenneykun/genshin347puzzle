# 抖音《三月 · 三域》成片产线

一条 1080×1920 / 30fps / 75 秒左右的竖屏成片：站点 **3D 实时镜头** + 中文旁白 + 硬字幕 + 合成配乐。
文案与镜头的唯一真值来源是 [`config.json`](config.json)，改文案只改它再重跑 `build.ps1`。

## 一键重跑

```powershell
pwsh -File video/build.ps1                 # 全流程（3D 动效 → 版式页 → 旁白 → 混音 → 渲染 → 交付）
pwsh -File video/build.ps1 -SkipClips      # 不重录 3D 镜头
pwsh -File video/build.ps1 -SkipCapture    # 素材与页面都已就绪
```

分步：

```powershell
python video/build.py                      # config → slides.html + 页面/字幕/覆盖层清单 + a1c 裁图
node   video/capture_clips.mjs             # 三域 3D 动效底片（确定性逐帧）→ build/clips/<name>/fNNNN.jpg
node   video/capture_wf.mjs 540            # 世界式平滑自转底片（拖拽驱动，帧帧新姿态）→ build/clips/wf/
node   video/capture.mjs site              # CDP 站点静帧 → video/assets/a1..a6.png
node   video/capture.mjs pages             # 状态页 + 透明字幕 + 透明覆盖层 → build/
python video/tts.py                        # 9 段旁白（默认 MeloTTS，可切 edge-tts）→ build/nNN.wav
python video/voice_samples.py              # 配音 A/B 样音（都过广播链）→ out/voice-samples/
python video/voice_lab.py review build/n03.wav   # 配音体检：F0 标准差 / 能量动态 / 语速
python video/audio.py                      # BGM/音效合成 + 混音 → build/mix.wav
python video/render.py --stills 0,10,28    # 抽几帧检查（build/check/）
python video/render.py --video             # 全片 → out/three_domain_1080x1920.mp4
python video/deliver.py                    # 封面 + 分镜 PDF（取成片真实帧）→ out/
```

## 三样东西叠成一层画面

| 层 | 来源 | 说明 |
|---|---|---|
| 底片 | `build/clips/<name>/fNNNN.jpg`（3D）或 `build/pages/<id>.png`（静态页） | 3D 底片是站点 WebGL 场景逐帧录的，不是图片推镜 |
| 覆盖层 | `build/overlays/<id>.png`（透明） | 3D 镜头上的标题、芯片行、免责 pill 都在这一层 |
| 字幕 | `build/captions/cNNN.png`（透明，逐句） | 抖音式大字幕：白字黑边、贴句出现；由 `sentence_times.json` 定时 |

镜 2 / 4 / 5 / 8 用动态底片（三域 3D 或世界式自转），其余是静态版式页。混合方式在 `config.json` 里用
`"clip": "pan"`（整镜）或 `{"clip": "plate", "offset": 20, "overlay": "o05"}`（单状态）表达。

## 3D 动效是怎么录的（`capture_clips.mjs`）

1. 覆盖 `performance.now()`，让页面时间只在我拨动 `window.__vt` 时前进 → 每个 rAF 的 `dt` 精确等于 1/30s；
2. 每帧：拨时间 → 按球坐标设机位（`__dbg.camera` + `__dbg.controls`）→ 等一帧渲染 → `Page.captureScreenshot`；
3. 结果是一段**确定性 30fps 帧序列**，不会因为截图快慢导致运动抖动。

四条坑：
- `OrbitControls` 的 `minDistance/maxDistance` 会把半径夹到 `[3.6, 20]`，所以机位半径要写在这个区间内；
- 电盘那层 GLSL 在 swiftshader 下极慢（≈2s/帧），非电盘镜头会 `hidePlate` 把它藏掉，快 10 倍以上；
- 站点把「生·燃烧·绽放 / 空·扩散 / 时·结晶」画在 3D 场景里，采集时按特征（一个 6 子节点的 Group，子 sprite 高 64px、宽 >128）
  整组隐藏，免得和讲解打架；
- 世界式页面的动画时间取自 rAF timestamp（不是 `performance.now`），CDP 虚拟时间在这里会卡住；
  改成**按住舞台拖拽驱动 yaw**：页面里 `cam.yaw += dx * 0.0062`，所以每帧拖 1px = 0.355°，
  帧帧都是新姿态、不重采样，30fps 播放不会再掉帧。抓帧前先点 5 次 `zoomOut` 才装得进竖屏。

## 几个必须知道的点

- **素材采集不要用 `--virtual-time-budget` 截图**：非 embed 页面会留下半透明 `BUILDING GRATING` 残影。`capture.mjs` 用 CDP 轮询 `#loading` 移除后截，并注入样式隐藏除 `#scene` 外的所有 DOM。
- **站点参数**：三域净画面用 `?visual=1&still=1&debug=1`；世界式用 `?embed=1&still=1`；带侧栏的定格用 `?still=1&debug=1`。`debug` 只为拿 `window.__dbg`。
- **推镜会裁掉页面上的文字**：所以页面文案锁在安全区（左右 8%、上下 12%），`kenburns` 幅度控制在 1.0–1.05。
- **几何真值**与站点一致：`ρ = 6.0622`，圆心 日(0,3.5) / 月(−3.03,−1.75) / 星(3.03,−1.75)；六个座位半径**交替 3.5 / 7**，是两颗嵌套正三角形（六角星），不是正六边形。
- **七元素图标是官方「卡牌UI-元素-*.png」**（128×128，取自 biligame 原神 wiki 元素页），
  `python video/fetch_element_icons.py` 可重抓；属米哈游素材的同人使用，发布时注明来源、勿商用。
- **配乐**是 gm_compose.py 现编的 lo-fi（零第三方素材）；要换真实曲目就用抖音 App 内的平台音乐库叠加，别把歌烧进文件。
- **本机 PATH 上的 ffmpeg 是 2013 年的版本**（AAC 编码器还挂着 experimental），所以 `render.py` / `deliver.py` 优先调用 `imageio-ffmpeg` 附带的新二进制。
- **配音引擎**：`config.json` → `voice.engine = melo | edge`。melo 走 `tts_melo.py`（需 `py -3.11` + torch + `pip install -e MeloTTS` + `py -3.11 -m unidic download`），
  edge 走在线音色。MeloTTS 是自带说话人的模型，不做音色克隆；要指定某个 SoVITS 音色需要具体的模型文件与授权参考音。
- 时长以配音实测为准：`timeline.py` 用 `旁白 + 0.25s 起播 + tail` 算每镜长度，整体补齐到 66–76s；
  收紧循环带了「无进展就退出」的护栏，否则旁白总长超过上限时会死循环。

## 目录

```
video/
  config.json        9 镜文案 / 状态 / 3D 底片 / 推镜 / 音效 / 最短时长
  slides.tpl.html    版式源（__CFG__ 占位），含几何绘制与七元素图标
  build.py           config 注入模板 + 产出页面/字幕/覆盖层清单 + a1c 裁图
  capture_clips.mjs  3D 动效逐帧录制
  capture.mjs        站点静帧 + 状态页 + 透明字幕/覆盖层
  tts.py             旁白生成与归一
  timeline.py        时长与帧排布
  bgm_compose.py     自编 lo-fi 配乐（78 BPM 钢琴琶音 + 轻鼓点），可单独试听
  audio.py           旁白 + BGM + 音效混音
  render.py          逐帧合成（底片+覆盖层+字幕）+ 编码 + srt
  deliver.py         封面 + 分镜 PDF（从成片取帧）
  assets/  build/  out/
```

## 合规

- 配音为 AI 合成（Microsoft Edge 语音），片尾与简介都标注「AI 配音」。
- BGM 与音效全部本机合成；七元素图标为自绘矢量，不含第三方素材。
- 画面全部来自本项目站点，未使用游戏原画或过场截图。

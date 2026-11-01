# 一键跑完整条产线
#   pwsh -File video/build.ps1                 全流程
#   pwsh -File video/build.ps1 -SkipClips      不重录 3D 镜头
#   pwsh -File video/build.ps1 -SkipCapture    素材与页面已就绪
param(
  [switch]$SkipClips,
  [switch]$SkipCapture,
  [switch]$SkipTts
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
  Write-Host '== 1/8 生成版式页清单 ==' -ForegroundColor Cyan
  python build.py

  if (-not $SkipClips) {
    Write-Host '== 2/8 录 3D 动效底片 ==' -ForegroundColor Cyan
    node capture_clips.mjs
  }

  if (-not $SkipCapture) {
    Write-Host '== 3/8 采集站点静帧 ==' -ForegroundColor Cyan
    node capture.mjs site
    Write-Host '== 4/8 采集状态页 / 字幕 / 覆盖层 ==' -ForegroundColor Cyan
    node capture.mjs pages
  }

  if (-not $SkipTts) {
    Write-Host '== 5/8 生成旁白 ==' -ForegroundColor Cyan
    python tts.py
  }

  Write-Host '== 6/8 合成混音 ==' -ForegroundColor Cyan
  python audio.py

  Write-Host '== 7/8 渲染成片 ==' -ForegroundColor Cyan
  python render.py --video

  Write-Host '== 8/8 封面与分镜 PDF ==' -ForegroundColor Cyan
  python deliver.py
}
finally {
  Pop-Location
}

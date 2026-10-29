# 三光 · 世界式

**Live site → [kenneykun.github.io/genshin347puzzle](https://kenneykun.github.io/genshin347puzzle/)**

A visual essay on the three moons, Abyss erosion, and Teyvat's 4-1-7 world-formula.

The site is a static shell with two live scenes:

- **Left:** Three.js glass cone, three light sources, and three dispersion rings — two dim moons, one bright violet "living" moon.
- **Right:** the earlier HTML/canvas 3D world-formula tree: 4 shadows, 1 interface, 7 elements, 2 interstitial travellers.

Both scenes are interactive: drag to orbit/rotate, wheel to zoom. No build step, no CDN, no tracking.

![Site preview](docs/world_formula_live_preview.png)

## Structure

```text
docs/
  index.html                    landing page / personal site shell
  prism_three.html              Three.js light-cone scene (?visual=1 for embed)
  world_formula.html            HTML/canvas 3D world-formula tree (?embed=1 for stage only)
  world_formula_visual.html     earlier static visual version (archive)
  world_formula_live_preview.png
  favicon.svg
  .nojekyll
.github/workflows/pages.yml     deploy docs/ to GitHub Pages
```

The primary nav switches in-page views, not pages:

- `#live` — both scenes
- `#world` — world-formula scene expanded
- `#prism` — light-cone scene expanded

The older full notes and lab pages are secondary links in the footer.

## Local preview

```powershell
python -m http.server 8080 -d docs
```

Open `http://127.0.0.1:8080/`.

## Deploy

GitHub Pages is deployed from `docs/` via the included workflow.

1. **Settings → Pages → Build and deployment**
2. Source: **GitHub Actions**
3. Push to `main`, or run **Deploy visual site** manually.

The site is published at <https://kenneykun.github.io/genshin347puzzle/>.

## Notes

- The site is intentionally text-light: the diagrams carry the argument.
- The two iframes are same-origin pages and must stay in the same `docs/` directory.
- If the repository or domain changes, update the canonical/Open Graph URLs in `docs/index.html`.

## License

See [LICENSE](LICENSE).

# MoonLabeler

**0.9.3** · Fluorine Zhu · GPL-3.0-or-later

Register lunar photographs, edit terrain labels, and export annotated PNG or SVG images.
为月面照片配准、标注地名并导出图片。

[中文使用说明](README.zh-CN.md) · [Release notes](UPDATE_HISTORY.md) · [Acknowledgements](ACKNOWLEDGEMENTS.md)

![MoonLabeler — synthetic editing example / 合成编辑示例](docs/moonlabeler.png)

## Download

| Platform | Package | Open after extracting |
| --- | --- | --- |
| macOS 14.4+, Apple Silicon | [macOS ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-macos-arm64.zip) | `MoonLabeler.app`; also movable to Applications |
| Windows x64 | [Windows ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-windows-x64.zip) | `MoonLabeler.exe`; keep the `_internal` folder beside it |

Both packages include Python, FITS support and offline ephemerides. The Mac app is ad-hoc signed; if blocked on first launch, allow it in System Settings → Privacy & Security. The Mac package requires Apple Silicon; Linux uses the source installation below.

## Quick start

1. Open a photograph and check its capture date and **UTC** time. The initial default is 15:00 UTC; location is optional.
2. Click **Identify and annotate**. If recognition fails, confirm one or two known features for assisted registration, or use at least three points for manual calibration.
3. Adjust filters and appearance, then **Regenerate annotations**. Hold **Cmd** on macOS or **Ctrl** on Windows/Linux while dragging a label; double-click to rename it.
4. Save a `.moonlabel` project or export PNG/SVG at the original image dimensions. Exports use the source filename; PNG is converted to sRGB.

Ordinary dragging pans the canvas; the wheel zooms it or scrolls settings without changing parameter values. The interface supports English, Simplified Chinese and Traditional Chinese.

## Features

- Automatic, reference-assisted and manual registration, including rotated, mirrored and afocal photographs.
- Editable terrain names, collision-aware label placement, relative font sizes and optional Apollo/Chang’e landing locations.
- Optional **medieval** and **wilderness topographic** themes, lunar coordinate grids, elevation colours, contours and terminators.
- Live opacity and photo-lit coverage controls. Sliders also accept numeric input; press Enter or leave the field to apply it.

Art themes use a desaturated display copy of the photograph. The original image and calibration stay intact. Map layers and edits are saved with projects and included in exports. See the [art-layer guide](README.zh-CN.md#可选艺术样式与地图图层).

## Source installation

Requires **Python 3.12+** and a C++ compiler: Xcode Command Line Tools on macOS, Visual Studio Build Tools with Desktop development with C++ on Windows, or `build-essential` on Linux. CMake and Ninja are installed by the build environment.

```bash
git clone https://github.com/Fluorine7/MoonLabeler.git
cd MoonLabeler
python3 -m venv .venv
# Windows: python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=26.2"
python -m pip install .
python -m moonlabeler
```

On macOS, `./start-mac.command` handles environment setup and launch. Linux also needs Qt system libraries and CJK fonts, for example `libegl1 libopengl0 libgl1 fonts-noto-cjk` on Ubuntu/Debian.

Optional extras: `python -m pip install ".[fits]"` for FITS or `".[gpu]"` for GPU terrain shading (`".[apple-gpu]"` for the Apple MLX backend). **Compute settings** selects Auto or CPU-only; unavailable GPUs fall back to CPU. For migration from upstream OpenCV wheels, see the [0.8.0 notes](UPDATE_HISTORY.md#080).

Source installs download about 20 MB of ephemerides on first use; terrain matching and map layers may additionally need the 33 MB LOLA DEM. Downloads are cached.

## Limits

- Recognition can fail with inaccurate times, heavy shadows, blur or sparse terrain. Check recognizable landmarks and use manual points when needed.
- Basic LOLA sampling is about 1.9 km. Crater outlines and terminators are references; fit residuals are not absolute position accuracy.
- Landing markers show projected coordinates, not detected spacecraft. The bundled demo is synthetic.

## Development and licence

Tests: install `".[dev]"`, then run `QT_QPA_PLATFORM=offscreen python -m pytest -q`.
Packaging: [macOS guide](docs/macos-app.md) · [Windows script](build-windows.ps1).

Copyright © 2026 Fluorine Zhu. Application code is [GPL-3.0-or-later](LICENSE). Data sources and third-party terms are recorded in [acknowledgements](ACKNOWLEDGEMENTS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

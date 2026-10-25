# MoonLabeler

**0.10.0** · Fluorine Zhu · GPL-3.0-or-later

Register lunar photographs, edit terrain labels, and export annotated PNG or SVG images.
为月面照片配准、标注地名并导出图片。

[中文](#中文) · [English](#english) · [详细使用说明](README.zh-CN.md) · [更新记录 / Release notes](UPDATE_HISTORY.md) · [致谢 / Acknowledgements](ACKNOWLEDGEMENTS.md)

![MoonLabeler — synthetic editing example / 合成编辑示例](docs/moonlabeler.png)

## 中文

### 下载

当前源码为 0.10.0，安装包为 0.9.3。

| 系统 | 安装包 | 打开方式 |
| --- | --- | --- |
| macOS 14.4+，Apple Silicon | [macOS ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-macos-arm64.zip) | 解压后打开 `MoonLabeler.app`，也可拖入“应用程序” |
| Windows x64 | [Windows ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-windows-x64.zip) | 完整解压后运行 `MoonLabeler.exe`，保留旁边的 `_internal` 文件夹 |

安装包自带 Python、FITS 支持和离线星历。Mac 包为临时签名，若首次打开被拦截，可在“系统设置 → 隐私与安全性”中允许；不支持 Intel Mac。Linux 使用源码安装。

### 快速开始

1. 打开照片，核对拍摄日期与 **UTC 时间**；启动默认 UTC 15:00，拍摄地点可选。
2. 点击 **“自动识别并标注”**。失败时可确认一两个已知点辅助自动配准，或用至少三个点手动校准。
3. 调整筛选和样式后点击标注页顶部固定的 **“重新生成标注”**；按住 **Cmd / Ctrl** 拖动标签，双击改名。
4. 保存 `.moonlabel` 工程，或导出原尺寸 PNG / SVG。导出沿用照片文件名，PNG 转换为 sRGB。

普通拖动平移画面，滚轮缩放画布或滚动面板，不会改变参数。界面和地形类别支持简体中文、繁体中文和英文。

### 功能与图层

- 自动、参考点辅助和手动配准，支持旋转、镜像及目镜后照片。
- 可编辑地名、自动避让、分档字号，以及阿波罗 / 嫦娥着陆点。
- 可选中世纪风、旷野地形图、蓝晒星图、铜版图录、水墨朱砂、红警地形图；支持经纬网、高程着色、等高线与晨昏线。
- 照片区域示意图标出当前覆盖范围，外观随艺术样式变化，支持 Cmd / Ctrl 拖动、保存位置并导出。
- 不透明度和受光阈值实时调整，支持滑块及数字输入；原图、配准和手工编辑保留。

艺术主题使用去色后的显示底图；切回“原始标注”会关闭地图图层，点击“重新生成标注”即可恢复。具体操作见[中文指南](README.zh-CN.md)。

### 从源码运行

需要 **Python 3.12+** 和 C++ 编译器：macOS 使用 Xcode Command Line Tools，Windows 使用 Visual Studio Build Tools，Linux 使用 `build-essential`。macOS 可直接运行 `./start-mac.command`；其他系统见下方[通用安装命令](#source-installation)。FITS、GPU 可选组件也在该节说明。

源码首次识别需下载约 20 MB 星历，高程相关功能另需约 33 MB LOLA 数据，缓存后可离线使用。

开发测试：安装 `".[dev]"` 后运行 `python -X warn_default_encoding -m pytest -q`；无桌面环境时设置 `QT_QPA_PLATFORM=offscreen`。

### 使用边界

时间、阴影、模糊和畸变可能影响识别。基础 LOLA 采样约 1.9 km，坑缘圈和晨昏线仅供参考，拟合残差不等于绝对定位精度。着陆点表示公开坐标，示例为合成图。

代码采用 [GPL-3.0-or-later](LICENSE)。数据与贡献者见[致谢](ACKNOWLEDGEMENTS.md)，第三方条款见[许可声明](THIRD_PARTY_NOTICES.md)。

## English

### Download

Source version: 0.10.0. Downloadable apps: 0.9.3.

| Platform | Package | Open after extracting |
| --- | --- | --- |
| macOS 14.4+, Apple Silicon | [macOS ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-macos-arm64.zip) | `MoonLabeler.app`; also movable to Applications |
| Windows x64 | [Windows ZIP](https://github.com/Fluorine7/MoonLabeler/releases/download/v0.9.3/MoonLabeler-0.9.3-windows-x64.zip) | `MoonLabeler.exe`; keep the `_internal` folder beside it |

Both packages include Python, FITS support and offline ephemerides. The Mac app is ad-hoc signed; if blocked on first launch, allow it in System Settings → Privacy & Security. The Mac package requires Apple Silicon; Linux uses the source installation below.

### Quick start

1. Open a photograph and check its capture date and **UTC** time. The initial default is 15:00 UTC; location is optional.
2. Click **Identify and annotate**. If recognition fails, confirm one or two known features for assisted registration, or use at least three points for manual calibration.
3. Adjust filters and appearance, then use **Regenerate annotations**, pinned at the top of the annotation tab. Hold **Cmd** on macOS or **Ctrl** on Windows/Linux while dragging a label; double-click to rename it.
4. Save a `.moonlabel` project or export PNG/SVG at the original image dimensions. Exports use the source filename; PNG is converted to sRGB.

Ordinary dragging pans the canvas; the wheel zooms it or scrolls settings without changing parameter values. Interface text and feature types support English, Simplified Chinese and Traditional Chinese.

### Features

- Automatic, reference-assisted and manual registration, including rotated, mirrored and afocal photographs.
- Editable terrain names, collision-aware label placement, relative font sizes and optional Apollo/Chang’e landing locations.
- Optional **medieval**, **wilderness topographic**, **cyanotype**, **copperplate**, **ink/cinnabar** and **Red Alert terrain** themes, with lunar grids, elevation colours, contours and terminators.
- Optional lunar locator showing the registered photo footprint, styled to match the art theme, with Cmd/Ctrl dragging and a saved position shared by PNG/SVG exports.
- Live opacity and photo-lit coverage controls. Sliders also accept numeric input; press Enter or leave the field to apply it.

Art themes use a desaturated display copy. Switching to Original annotations turns off map layers; click Regenerate annotations to restore the original appearance. The original image, calibration and manual edits stay intact. See the [art-layer guide](README.zh-CN.md#可选艺术样式与地图图层).

### Source installation

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

### Limits

- Recognition can fail with inaccurate times, heavy shadows, blur or sparse terrain. Check recognizable landmarks and use manual points when needed.
- Basic LOLA sampling is about 1.9 km. Crater outlines and terminators are references; fit residuals are not absolute position accuracy.
- Landing markers show projected coordinates, not detected spacecraft. The bundled demo is synthetic.

### Development and licence

Tests: install `".[dev]"` and run `python -X warn_default_encoding -m pytest -q` (`QT_QPA_PLATFORM=offscreen` for headless runs).
Packaging: [macOS guide](docs/macos-app.md) · [Windows script](build-windows.ps1).

Copyright © 2026 Fluorine Zhu. Application code is [GPL-3.0-or-later](LICENSE). Data sources and third-party terms are recorded in [acknowledgements](ACKNOWLEDGEMENTS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

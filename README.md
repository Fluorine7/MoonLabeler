# MoonLabeler

**Author / 作者：Fluorine Zhu** · **Version / 版本：0.4.6** · **GPL-3.0-or-later**

Register your own lunar photographs, place editable terrain labels, and export annotated PNG / SVG images.
在自己的月面照片上配准地形、排布可编辑标签，并导出 PNG / SVG。

[中文使用说明](README.zh-CN.md) · [Acknowledgements / 致谢](ACKNOWLEDGEMENTS.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [License](LICENSE)

![MoonLabeler — explicitly synthetic editing example / 合成编辑示例](docs/moonlabeler.png)

## 中文

MoonLabeler 是用 Python / Qt 编写的桌面月面照片标注工具，支持整月盘、局部照片、旋转及镜像。界面目前为中文。

### 功能

- 自动识别：匹配内置 LROC 纹理；也可拟合较完整的月盘外缘，并联合验证月相和月海纹理；局部图再通过坑群搜索目录；仍失败时使用小型 LOLA 高程数据生成阴影参考。
- 手动校准：以至少 3 个已知地形中心求解比例、旋转、偏移和镜像；显示逐点偏差。
- 疑似坑检测：本地 OpenCV 检测圆形 / 椭圆坑缘，支持修正中心与导出 CSV。
- 照片画布在左、紧凑检查器在右；低频参数折叠，候选坑确认操作固定在页脚。
- 标注布局：自动避让标签、地形中心和引线；拖动标签或双击改名。
- 字号按照片短边比例缩放，默认 **1.5%**；新照片的标签上限为 **200**。
- 默认近白色文字与深色描边；大环形山默认用平滑椭圆，可选坑缘轮廓，小坑使用短引线。
- 设置修改后，点击 **“重新生成标注”** 统一应用。
- 中文译名来自国家天文科学数据中心词表；没有可靠译名的名称保留英文。
- 保存 `.moonlabel` 工程，导出与原图同尺寸 PNG 或可编辑 SVG；另提供 LOLA DEM 光照模拟参考。

### 从源码运行

需要 **Python 3.11 或更高版本**。主要在 macOS 上开发与测试。

```bash
git clone https://github.com/Fluorine7/MoonLabeler.git
cd MoonLabeler
./start-mac.command
```

也可在 macOS 双击 `start-mac.command`。首次启动会创建虚拟环境并安装依赖。
其他系统可通过 Python 启动，相关界面尚未完成平台实测：

```bash
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m moonlabeler
```

FITS 可选依赖：`python -m pip install astropy`。打开后可点 **“打开示例”** 测试内置的合成工程；它用于演示编辑与校准流程，不用于证明实拍识别准确率。

### 使用与限制

打开照片，选择拍摄日期（默认使用当日 **UTC 15:00**），点击“自动识别并标注”。“具体时间”默认折叠，展开后可设置 UTC 时分秒；收起或更换日期不会重置时间，可点击恢复默认。旧工程保留已保存的精确时间。地点可选；不填时使用地心近似。照片在本机处理。首次自动识别需要下载约 20 MB JPL 星历，坑群精修和高程后备匹配使用约 33 MB LOLA 数据，缓存后可离线使用；自动识别无需 NASA 在线影像或 AI 权重。

自动识别属于实验性功能。强阴影、月缘与极区的严重压缩、模糊、水印、日期错误或候选坑太少时仍可能失败。不能通过验证的结果不会作为地名标注，也不会替换已有配准。可改用已知地形点手动校准。

局部坑群识别通过后，会使用同一份约 33 MB 的 LOLA DEM 精修相机与观测方向；局部参考渲染和拟合都考虑地形高度。修正必须通过空间分区留出点与重新渲染的整幅纹理检查，否则保留原配准。该修正不代表反推出的拍摄地点或天平动测量值。

坑缘圈仅用于直径至少 35 km 且在照片中足够大的坑，小坑保留短引线。“标注 → 排版选项 → 轮廓形状”默认选择平滑 **椭圆**，也可选 **坑缘轮廓（手绘风）**；点击“重新生成标注”应用。局部坑群路径优先沿 DEM 中连续的坑缘高地取点，考虑地形高度投影，再拟合椭圆；坑缘轮廓选项保留这些点的不规则形状。数据不足或其他识别路径使用目录参考圈。形状设置与高程坑缘保存在工程中，并用于 PNG / SVG。这些轮廓受 DEM 约 1.9 km 网格、遮挡与配准残差限制，并非逐像素测得的真实坑壁。小拟合残差不等于绝对定位精度。

本仓库包含源码、公开数据来源记录及可公开示例。用户提供的摄影师实拍、相关导出图、运行缓存和虚拟环境不随源码分发。

### 许可与致谢

Copyright © 2026 **Fluorine Zhu**。MoonLabeler 代码按 **GNU General Public License v3.0 or later** 发布，完整文本见 [LICENSE](LICENSE)。改编代码保留原作者的 MIT 许可与版权声明；第三方数据及依赖保留其原有条款，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

向 Jim Mosher、Henrik Bondo、Ram Maruboina，以及 LTVT、PixInsight AnnotateImage、OpenCV、NASA / LROC / LOLA、USGS / IAU、JPL、Skyfield 和中文词表的贡献者致敬。完整来源与实际采用范围见 [致谢](ACKNOWLEDGEMENTS.md)。

感谢 **樊仕达（10deg）** 提供 **moonlib** 代码，作为本项目月面几何研究与实现的参考。

## English

MoonLabeler is a Python / Qt desktop application for registering lunar photographs and placing editable terrain labels. It supports full-disk and close-up images, rotation, and mirrored views. The current application interface is in Chinese.

### Features

- Automatic registration using a bundled LROC texture, a wide-limb fallback validated with phase and albedo texture, crater-pattern catalogue matching for close-up views, and a small LOLA slope/shadow-reference fallback.
- Manual calibration from at least three known terrain centers, with rotation, scale, translation, reflection, and per-point error review.
- Local OpenCV crater-rim candidate detection, center correction, and CSV export.
- Photo-first layout with a compact right-hand inspector, collapsible advanced settings, and a pinned crater-confirmation panel.
- Automatic label placement with collision avoidance, draggable labels, and editable names.
- Font sizes proportional to the image's shorter dimension, defaulting to **1.5%**, and a default limit of **200** labels.
- Near-white annotations with dark text outlines; projected reference outlines for large craters and short leaders for small craters.
- A **Regenerate annotations** button (重新生成标注) that applies edited settings together.
- Sourced Chinese names, original English names, or bilingual labels.
- Editable `.moonlabel` projects, original-size PNG export, SVG export, and a separate LOLA DEM lighting-reference tool.

### Installation and usage

Requires **Python 3.11+**. Development and native UI testing are primarily on macOS.
Clone the repository and run `./start-mac.command` on macOS, or create a virtual environment, install `requirements.txt`, and run `python -m moonlabeler` as shown above. Windows and Linux have not received native UI validation.

Open a photograph, select the capture date (default **15:00 UTC** on that date; saved projects retain their original timestamps), then click **自动识别并标注** (Identify and annotate). Expand **具体时间** (Exact time), collapsed by default, to edit UTC hours, minutes and seconds. Collapsing it or changing the date retains the chosen time; a reset button restores 15:00 UTC. An observing location is optional; omitting it uses a geocentric approximation. Image processing is local. About 20 MB of JPL ephemerides are downloaded on first use; crater refinement and the terrain fallback use about 33 MB of LOLA elevation data. Both are cached; automatic identification does not require NASA SVS image downloads or AI model weights.

For manual calibration, open **校准 → 已知地名取点** (Calibration → Known-name points). A reference point pairs a known terrain name with its location in your photograph:

1. Search for a crater you recognize and select its name from the results.
2. Click **在照片中标记** (Mark in photo), then click the geometric center of that same crater's rim. Avoid using the bright patch or shadow center. Zoom if needed; Esc cancels picking.
3. Repeat for 3–6 well-separated, non-collinear craters, then click **完成校准并生成标注** (Calibrate and generate annotations). Geometry is computed automatically and the annotation page opens. Collected points survive an ephemeris-download failure.

The **辅助找坑** (Find candidate centers) tab only assists point placement; you still confirm each name. Its footer links back to the confirmed reference points. Double-click a reference-point table row to replace its position, or uncheck it to exclude it before recalibrating.

The bundled example is explicitly synthetic and demonstrates calibration and editing. It is not a real-image recognition benchmark. Optional FITS support requires `astropy`.

### Scientific limitations

Automatic recognition is experimental. Strong shadows, severely foreshortened polar or limb terrain, poor resolution, watermarks, incorrect dates, and too few reliable crater candidates can cause rejection. Rejected results do not replace an existing registration. Known terrain points provide a manual fallback.

The wide-limb fallback requires at least a 120° outer arc, clear phase agreement, distinct albedo correlation, and separation from competing rotations / reflections. Its reported residual is the outer-edge fit, not crater-center accuracy. The local 2026-08-17 crescent regression passes. The 2025-09-14 north- and south-polar crops now pass broad region-identification checks; these are not pixel-accurate rim benchmarks.

After crater-pattern identification, local refinement uses the same small LOLA DEM, with terrain height included consistently in reference rendering and pose fitting. A small camera correction is followed by retrieval of further independent terrain points and a bounded two-axis view fit. The terrain fallback also attempts view refinement. Changes are accepted only with spatially held-out improvement and a fresh dense-render check. The estimated direction is an image-derived projection correction, not a recovered observing location or a libration measurement. The original ephemeris geometry and validation record are retained in the project.

Outlines are shown for craters at least 35 km across that are also large enough in the photograph; smaller craters use short leaders. Under 标注 → 排版选项 → 轮廓形状, smooth **ellipses** are the default; the optional **rim contour (hand-drawn appearance)** preserves irregular terrain shapes. Click 重新生成标注 to apply changes. The close-up crater-pattern route samples continuous DEM crests with terrain-height projection before fitting ellipses. Catalogue reference circles remain the fallback when suitable elevation contours are unavailable. Both the style and elevation contours are saved in projects and shared by PNG/SVG export. These are not pixel-accurate photographic rim measurements: the approximately 1.9 km DEM grid, occlusion and registration residuals can still cause offsets. A low fitting residual measures internal consistency, not absolute lunar positioning accuracy.

Third-party photographers' test images and derived exports remain local and are not distributed with this repository. Public data sources and processing provenance are documented separately.

### Tests

```bash
python -m pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Tests cover geometry, mirrored registration, crater detection, catalogue matching, rejection of unrelated / competing patterns, project persistence, label layout, and exports. Some real-photo and DEM checks require local fixtures and caches and are skipped when those inputs are unavailable. Synthetic tests do not establish recognition rates on arbitrary photographs.

### License and acknowledgements

Copyright © 2026 **Fluorine Zhu**. The MoonLabeler code is licensed under **GNU GPL version 3 or, at your option, any later version**. See [LICENSE](LICENSE). Adapted MIT code retains its original copyright and permission notice. Third-party dependencies and data retain their respective terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

We gratefully acknowledge Jim Mosher and Henrik Bondo for LTVT, Ram Maruboina for Lunar Crater Detector, the PixInsight AnnotateImage authors, OpenCV contributors, NASA / LROC / LOLA, USGS / IAU, JPL, Skyfield, and the Chinese astronomical terminology contributors. See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for detailed credits and a clear distinction between adapted code, independent implementations, and projects studied for future work.

Thanks to **樊仕达 (10deg)** for providing the **moonlib** code as a reference for this project's lunar geometry research and implementation.

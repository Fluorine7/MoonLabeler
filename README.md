# MoonLabeler

**Author / 作者：Fluorine Zhu** · **Version / 版本：0.4.4** · **GPL-3.0-or-later**

Register your own lunar photographs, place editable terrain labels, and export annotated PNG / SVG images.
在自己的月面照片上配准地形、排布可编辑标签，并导出 PNG / SVG。

[中文使用说明](README.zh-CN.md) · [Acknowledgements / 致谢](ACKNOWLEDGEMENTS.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [License](LICENSE)

![MoonLabeler — explicitly synthetic editing example / 合成编辑示例](docs/moonlabeler.png)

## 中文

MoonLabeler 是用 Python / Qt 编写的桌面月面照片标注工具，支持整月盘、局部照片、旋转及镜像。界面目前为中文。

### 功能

- 自动识别：匹配内置 LROC 纹理；也可拟合较完整的月盘外缘，并联合验证月相和月海纹理；局部图再通过坑群搜索目录。
- 手动校准：以至少 3 个已知地形中心求解比例、旋转、偏移和镜像；显示逐点偏差。
- 疑似坑检测：本地 OpenCV 检测圆形 / 椭圆坑缘，支持修正中心与导出 CSV。
- 标注布局：自动避让标签、地形中心和引线；拖动标签或双击改名。
- 字号按照片短边比例缩放，默认 **1.5%**；新照片的标签上限为 **200**。
- 默认近白色文字与深色描边；大环形山显示投影坑缘轮廓，小坑使用短引线。
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

打开照片，填写拍摄日期与大致 **UTC** 时间（北京时间减 8 小时），点击“自动识别并标注”。地点可选；不填时使用地心近似。照片在本机处理。首次自动识别需要下载 JPL 星历，缓存后可离线使用；自动识别无需 NASA 在线影像或 AI 权重。

自动识别属于实验性功能。强阴影、月缘与极区的严重压缩、模糊、水印、日期错误或候选坑太少时仍可能失败。不能通过验证的结果不会作为地名标注，也不会替换已有配准。可改用已知地形点手动校准。

坑缘圈根据目录经纬度与直径投影，是参考轮廓，并非逐像素拟合真实坑壁。当前使用球面模型；不规则坑形、地形高差、检测中心和整体配准偏差都可能影响圈的位置。小拟合残差不等于绝对定位精度。

本仓库包含源码、公开数据来源记录及可公开示例。用户提供的摄影师实拍、相关导出图、运行缓存和虚拟环境不随源码分发。

### 许可与致谢

Copyright © 2026 **Fluorine Zhu**。MoonLabeler 代码按 **GNU General Public License v3.0 or later** 发布，完整文本见 [LICENSE](LICENSE)。改编代码保留原作者的 MIT 许可与版权声明；第三方数据及依赖保留其原有条款，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

向 Jim Mosher、Henrik Bondo、Ram Maruboina，以及 LTVT、PixInsight AnnotateImage、OpenCV、NASA / LROC / LOLA、USGS / IAU、JPL、Skyfield 和中文词表的贡献者致敬。完整来源与实际采用范围见 [致谢](ACKNOWLEDGEMENTS.md)。

## English

MoonLabeler is a Python / Qt desktop application for registering lunar photographs and placing editable terrain labels. It supports full-disk and close-up images, rotation, and mirrored views. The current application interface is in Chinese.

### Features

- Automatic registration using a bundled LROC texture, a wide-limb fallback validated with phase and albedo texture, and crater-pattern catalogue matching for close-up views.
- Manual calibration from at least three known terrain centers, with rotation, scale, translation, reflection, and per-point error review.
- Local OpenCV crater-rim candidate detection, center correction, and CSV export.
- Automatic label placement with collision avoidance, draggable labels, and editable names.
- Font sizes proportional to the image's shorter dimension, defaulting to **1.5%**, and a default limit of **200** labels.
- Near-white annotations with dark text outlines; projected reference outlines for large craters and short leaders for small craters.
- A **Regenerate annotations** button (重新生成标注) that applies edited settings together.
- Sourced Chinese names, original English names, or bilingual labels.
- Editable `.moonlabel` projects, original-size PNG export, SVG export, and a separate LOLA DEM lighting-reference tool.

### Installation and usage

Requires **Python 3.11+**. Development and native UI testing are primarily on macOS.
Clone the repository and run `./start-mac.command` on macOS, or create a virtual environment, install `requirements.txt`, and run `python -m moonlabeler` as shown above. Windows and Linux have not received native UI validation.

Open a photograph, enter the capture date and approximate **UTC** time, then click **自动识别并标注** (Identify and annotate). An observing location is optional; omitting it uses a geocentric approximation. Image processing is local. JPL ephemerides are downloaded on first use and cached; automatic identification does not require NASA SVS image downloads or AI model weights.

The bundled example is explicitly synthetic and demonstrates calibration and editing. It is not a real-image recognition benchmark. Optional FITS support requires `astropy`.

### Scientific limitations

Automatic recognition is experimental. Strong shadows, severely foreshortened polar or limb terrain, poor resolution, watermarks, incorrect dates, and too few reliable crater candidates can cause rejection. Rejected results do not replace an existing registration. Known terrain points provide a manual fallback.

The wide-limb fallback requires at least a 120° outer arc, clear phase agreement, distinct albedo correlation, and separation from competing rotations / reflections. Its reported residual is the outer-edge fit, not crater-center accuracy. The local 2026-08-17 crescent regression passes; the extreme 2025-09-14 north-polar crop remains a documented expected failure, rather than being presented as solved.

Crater outlines are projected from catalogue coordinates and diameters, not fitted pixel by pixel to the photographed rim. The current spherical model does not fully account for terrain relief, irregular rims, or atmospheric refraction. A low fitting residual measures internal consistency, not absolute lunar positioning accuracy.

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

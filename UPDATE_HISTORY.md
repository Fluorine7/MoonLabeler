# 更新记录 / Release notes

[项目主页](README.md) · [中文指南](README.zh-CN.md)

## 0.10.0

2026-10-26

- 新增蓝晒星图、铜版图录、水墨朱砂、红警地形图，配套高程着色、等高线和图例。 / Added cyanotype, copperplate, ink/cinnabar and Red Alert terrain themes with matching map layers and legends.
- 新增照片区域示意图，外观跟随艺术样式，可按住 Cmd / Ctrl 移动，位置随工程保存并用于 PNG/SVG。 / Added a themed photo-footprint locator with Cmd/Ctrl dragging and saved positions in PNG/SVG exports.
- “重新生成标注”固定在标注页顶部，合并重复的应用按钮；重排标签不再顺带应用其他待修改设置。 / Pinned Regenerate annotations at the top of the tab and removed the duplicate Apply button. Reflow leaves other pending settings untouched.
- 修正待应用样式与实时滑块相互干扰的问题，地形类别跟随简体、繁体或英文界面显示。 / Fixed live sliders modifying the applied map while another style was pending; feature types now follow the interface language.
- 分段填充后台文字预览，减少文字细化时的界面停顿，并及时响应缩放、拖动的取消操作。 / Split background text fills to reduce refinement stalls and respond to navigation cancellation.
- 采用蔡明翰（Evan Tsai）的 [PR #16](https://github.com/Fluorine7/MoonLabeler/pull/16) 修复：测试显式使用 UTF-8，解决繁体 Windows 代码页的解码错误，并加入编码检查。 / Applied Evan Tsai's UTF-8 test fixes and encoding checks for Traditional Chinese Windows.

本次更新源码，安装包仍为 0.9.3。 / Source update; downloadable apps remain at 0.9.3.

## 0.9.5

- 合并 [sothic 的 PR #15](https://github.com/Fluorine7/MoonLabeler/pull/15)：工具栏增加原始大小、放大、缩小按钮及快捷键，缩放时保持视图中心。 / Merged sothic's toolbar zoom controls and shortcuts, preserving the viewport centre.

## 0.9.4

2026-10-24

- 高程图例支持 Cmd / Ctrl 拖动，位置随工程保存并用于 PNG / SVG。 / Movable elevation legend with saved and exported position.
- 名称语言明确区分简繁双语，并将两个双语选项置顶。 / Distinct Simplified/Traditional bilingual choices, both listed first.
- 切回原始标注时统一关闭地图图层，保留原始文字设置、配准及手工编辑。 / Switching back to Original annotations clears map layers and preserves text settings, calibration and manual edits.
- 清理公开仓库中的开发截图、报告和内部记录。 / Removed development screenshots, reports and internal notes from the public tree.

本次仅更新源码，暂不打包。 / Source update only; no new application packages.

## 0.9.3

2026-10-24

- 改善艺术标注缩放、拖动及停止操作后的文字清晰度恢复。
- 不透明度与受光阈值支持手工输入，与滑块同步；保留滚轮不改值的保护。
- 发布 macOS Apple Silicon 与 Windows x64 应用包，版本统一为 0.9.3。

Smoother art-label navigation, precise numeric slider input, and macOS/Windows packages under the corrected 0.9.3 version.

## 0.9.2

2026-10-23

- 恢复按照片亮度控制地图覆盖，自动阈值可手动调整，边缘柔和渐隐。
- 调整阈值实时生效，工程与 PNG/SVG 保留相同覆盖效果。

Photo-lit map coverage with an adjustable automatic threshold and feathered edges, shared by projects and exports.

## 0.9.1

2026-10-23

- 完善中世纪风与旷野地形图，加入自动等高距和晨昏线。
- 艺术底图去色；月盘外的弧形地名改为直排，定位辅助线仅在拖动时显示。
- 修复大图字号和图层卡顿；导出沿用原文件名，PNG 使用 sRGB。
- 加入蔡明翰（Evan Tsai）的繁体中文与 Windows 修复贡献致谢。

Refined art themes, adaptive contours, terminators, label placement and navigation; source-based export names and sRGB PNGs. Credits Evan Tsai's contributions.

## 0.9.0

2026-10-23

- 新增可选艺术主题、月面经纬网和 LOLA 高程着色。
- 图层不透明度使用实时滑块；统一保护参数控件，滚轮仅滚动面板或缩放画布。

Optional art themes, coordinate grids and elevation overlays, with live opacity sliders and wheel-safe controls.

## 0.8.0

2026-10-22

- 发布独立 macOS 与 Windows 应用包，补齐 TIFF/FITS 的打包依赖。
- 完善繁体中文、界面语言与跨平台兼容；更新 Python 和依赖安全基线。
- 源码最低要求 Python 3.12，使用项目自带的精简 OpenCV。

Standalone apps, TIFF/FITS packaging fixes, language improvements and dependency updates. Source installs require Python 3.12+ and the private minimal OpenCV build.

从旧版升级时，在当前虚拟环境中移除旧 OpenCV wheel，再安装项目：

```bash
python -m pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless
python -m pip install --upgrade ".[fits]"
```

[macOS 打包 / macOS build guide](docs/macos-app.md)

## 0.7.12

修复球面配准后重复追加高程造成的标注偏移；工程记录实际配准表面。 / Fixed extra elevation offsets after spherical registration and saved the fitted surface type.

## 0.7.11

加入地形高程快照和完整坑缘的视觉中心修正，支持离线重开与导出。 / Added saved terrain heights and visual rim centres for annotations and offline exports.

## 0.7.10

跳过不必要的坑缘检测，复用目镜照片的匹配特征，加快自动识别。 / Skipped unused crater detection and reused afocal-image features.

## 0.7.9

增加“自动 / 相机直拍 / 目镜后”拍摄方式选项。 / Added Auto, Direct camera and Afocal capture modes.

## 0.7.8

增加受限的参考图重匹配，改善手机目镜后照片识别。 / Added a guarded reference-rematching retry for afocal photographs.

## 0.7.7

接入 2026-10-16 综合地貌资料，保留原有译名、来源及扩展元数据。 / Imported the combined nomenclature snapshot while preserving translations and provenance.

## 0.7.6

修复暗半球被裁切时过早拒绝月缘测量的问题，完善失败原因提示。 / Fixed premature limb rejection when the dark hemisphere is cropped; improved diagnostics.

## 0.7.5

改善带大片黑边的手机月牙照片识别。 / Improved recognition of afocal crescents with large black margins.

## 0.7.4

标签改为 Cmd/Ctrl 拖动，普通拖动平移画面。 / Modifier-drag moves labels; ordinary dragging pans the canvas.

## 0.7.3

小月盘识别允许排除边框附近的图注。 / Compact-disk searches can exclude border captions.

## 0.7.2

修复小月盘被大片黑边包围时的识别失败。 / Fixed recognition of small lunar disks surrounded by black margins.

## 0.7.1

加入受限的手机目镜后畸变校正。 / Added guarded optical-distortion correction for afocal photographs.

## 0.7.0

中文译名优先采用 LPND；提供自动 / 仅 CPU 计算设置。 / Prioritized LPND translations and simplified compute settings to Auto/CPU-only.

## 0.6.6

加入可选 wgpu 跨平台高程光照加速，失败时回退 CPU。 / Added optional cross-platform wgpu terrain shading with CPU fallback.

## 0.6.5

增加计算设置与本机设备选择。 / Added compute preferences and device selection.

## 0.6.4

首次加入 Apple MLX/Metal 高程光照加速。 / Introduced optional Apple MLX/Metal terrain shading.

## 0.6.3

优化坑群索引构建。 / Optimized crater-pattern indexing.

## 0.6.2

减少标签布局中的重复碰撞查询。 / Reduced redundant label-layout collision queries.

## 0.6.1

重要地形优先排布，保留手工位置和隐藏选择。 / Prioritized major landmarks while respecting manual positions and visibility choices.

## 0.6.0

增加阿波罗与嫦娥着陆点可选图层。 / Added an optional Apollo/Chang’e landing-site layer.

## 0.5.11

改进高倍大坑候选检测；支持 WinJUPOS 文件名 UTC 时间导入。 / Improved large-crater candidates and added WinJUPOS timestamp import.

## 0.5.10

改善北极地形识别，复用照片特征以减少计算。 / Improved northern-terrain matching and feature reuse.

## 0.5.9

改善模糊极区与拼接照片识别。 / Improved blurred polar and mosaic-image matching.

## 0.5.8

修复整月盘纹理配准在月缘附近的投影偏移。 / Corrected atlas-registration drift near the limb.

## 0.5.7

加入大、中、小三档相对字号与字号递减设置。 / Added three relative font tiers and a configurable decrement.

## 0.5.6

日期、时分独立输入，合并候选找坑与参考点流程。 / Split date/time fields and unified candidate and reference workflows.

## 0.5.5

确认栏持续显示当前候选与地名。 / Kept the selected candidate and name visible in the confirmation bar.

## 0.5.4

完善日期、时间及候选坑复核界面。 / Refined capture-time and crater-review controls.

## 0.5.3

修复参考点搜索、工程加载和照片读取，改善透明图及 16 位 TIFF 处理。 / Fixed reference searches, project loading and image decoding.

## 0.5.2

改善高程后备匹配的局部精修，合并重复候选。 / Improved terrain fallback refinement and candidate deduplication.

## 0.5.1

确认一两个地形点后，可尝试参考点辅助自动配准。 / Added automatic registration guided by one or two confirmed features.

## 0.4.8

地名搜索改为可见列表，支持 Enter 选首项。 / Made name-search results directly selectable, including via Enter.

## 0.4.7

改进候选优先级、避让补位与标签数量限制。 / Improved candidate ranking, collision-aware backfilling and label limits.

## 0.4.6

局部配准考虑高程，加入椭圆与坑缘轮廓选项。 / Added terrain-aware local refinement and selectable rim outlines.

## 0.4.5

整合校准、标注、参考三页界面与手动补点流程。 / Integrated the three-tab inspector and manual reference workflow.

## 0.4.4

首个公开 Git 版本：自动与手动配准、标签编辑、工程保存及 PNG/SVG 导出。 / First public Git version, with registration, editable labels, projects and exports.

## 早期原型 / Earlier prototypes（0.4.4 以前 / before 0.4.4）

0.2.x–0.4.3 逐步建立图片载入、参考点、坑检测与标注流程；未保留逐版本 Git 快照。 / Early prototypes established image loading, references, crater detection and annotations; individual Git snapshots were not retained.

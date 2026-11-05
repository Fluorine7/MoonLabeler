# 更新记录 / Release notes

[项目主页](README.md) · [中文指南](README.zh-CN.md)

## 0.12.3

2026-11-05

- 修正较强手机目镜畸变下月缘地形的标注偏移：用基础 LOLA 阴影补充灰度底图缺失的极区细节，校验额外径向项；保留原有图像对应点、九分区留出及分开的月缘训练/验证数据，普通照片与轻微畸变保留快速路径。 / Improve limb labels in strongly distorted afocal photos using LOLA shading for polar details missing from the albedo map. An additional radial term must preserve reliable albedo anchors and pass spatial holdouts and separate limb measurements; ordinary and mildly distorted photos retain the fast path.
- 扩展校正与工程保存、正反向投影、字号、蒙版、地图图层及 PNG / SVG 共用；旧工程缺少 `k2` 时沿用原模型。高程下载可中止，校验失败保留原结果并提示。 / Share the extended correction across projects, forward/inverse projection, font scaling, masks, maps and PNG/SVG. Missing `k2` retains the legacy model; downloads are cancellable and rejected refinements preserve the accepted pose.

本次更新源码，安装包仍为 0.12.2。 / Source update; downloadable apps remain at 0.12.2.

## 0.12.2

2026-11-04

- 照片区域示意图直接使用工程的实际观测几何，显示对应月相、天平动和月轴倾角；局部、月缘或极区取景不再改变小图月相。 / The photo-footprint locator now uses the project's actual observing geometry for phase, libration and lunar-axis tilt, so local, limb or polar crops no longer change its apparent phase.
- 移除 Earth 标记，保留取景范围和取景中心坐标；N/S 极点及背面方向箭头跟随月轴倾斜。 / Removed the Earth marker while retaining the footprint and field-centre coordinates. Pole markers and hidden-pole arrows follow the projected lunar axis.
- 所有样式的示意图底板统一为半透明中性黑，月面与图线保留艺术主题配色；沿用拖动缓存、工程位置保存及一致的 PNG / SVG 导出。 / All locator styles use a translucent neutral-black panel, retaining the themed Moon and lines, cached dragging, saved project positions and matching PNG / SVG exports.

提供本地构建的 macOS 14.4+ Apple Silicon 兼容应用包及云端构建的 Windows x64 应用包，内置运行环境、FITS 支持和离线星历。 / App packages include a locally built macOS 14.4+ Apple Silicon compatibility build and a cloud-built Windows x64 build, with the runtime, FITS support and offline ephemerides bundled.

## 0.12.1

2026-11-03

- 整理侧栏层级：常用的艺术样式、名称语言、字号、数量、受光阈值和示意图集中在顶部；筛选、文字样式、排版、地图图层和标签列表默认折叠。重新生成、沿地形开关和待应用提示固定在滚动区上方，分组统一使用标题与分隔线。 / Reorganized the sidebar with common settings at the top and collapsible filters, text, layout, maps and label lists. Regeneration, landform placement and pending-setting feedback stay above the scroll area, with consistent section headings and dividers.
- 识别蒙版放入自动识别分组，辅助找坑的候选与地名步骤按检测结果显隐，手动补点和参考点入口保留；补充参考页的用途提示。 / Grouped recognition masks with automatic recognition and show crater candidate/name steps when results exist, retaining manual points and references. Added guidance on the reference page.
- 修正英文侧栏中输入框、下拉箭头和受光阈值 Auto 按钮被裁切的问题，收紧三处英文文案；回归按实际控件边界验证简中、繁中和英文的待应用、折叠及展开状态，避免依赖字体的零滚动像素断言。 / Fixed clipped English inputs, arrows and the light-threshold Auto button with concise captions. Regression checks validate actual control bounds across three languages, pending settings and collapsed/expanded sections, replacing the font-dependent zero-scroll assertion.
- 完善跨平台测试：文字分簇允许平台字体差异，同时校验原文、字符边界与字距；响应测试保留 60 ms 标准和主线程阻塞反例，以三次独立峰值的中位数降低单次调度暂停造成的误判。 / Hardened cross-platform tests: shaping checks allow font-backend cluster differences while retaining text, boundary and advance validation. Responsiveness keeps the 60 ms limit and blocking control, using the median of three independent peak gaps to tolerate one scheduling pause.
- 维护平台收敛为 macOS 和 Windows，移除 Linux 客户端 CI 构建与测试任务，并同步源码安装说明。 / Maintenance now targets macOS and Windows; removed the Linux client CI build/test job and updated source installation guidance.

本次更新源码，安装包仍为 0.11.0。 / Source update; downloadable apps remain at 0.11.0.

## 0.12.0

2026-11-03

- 新增“沿地形排列名称”：月溪、山脉、山脊、月谷、月崖和坑链可沿地形走向排字，普通与艺术样式共用。开关固定在标注页顶部、“重新生成标注”按钮下方；新工程默认启用，旧工程保持原布局。 / Added Follow landform shapes for rilles, mountain ranges, ridges, valleys, scarps and crater chains in all styles. The switch stays below Regenerate annotations; new projects enable it, while older projects retain their layout.
- 完成整行字体排版后按文字簇沿曲线放置，保留真实字距、连字和组合音标。双语名称采用中文主行与较小的英文副行，两行各自按偏移基线的弧长排列，减少弯曲内侧挤字。 / Text is shaped as a complete line before its clusters follow the curve, preserving kerning, ligatures and combining marks. Bilingual names use a Chinese primary row and a smaller English row, each laid out by the arc length of its own offset baseline.
- 排字基线采用受约束的局部平滑与多段候选，保留大弯，限制相邻文字突变和倒置；资料不足、路径过短或无法合理排放时保留普通标注。手动位置、改名、不透明度和 PNG / SVG 共用同一套文字位置。 / Bounded local smoothing and candidate spans preserve broad bends while limiting abrupt turns and inverted text. Unavailable or unsuitable paths use ordinary labels. Edits, opacity, PNG and editable SVG share the same placements.
- 随软件提供约 0.17 MB 的离线路径，来源为樊仕达（10deg）整理的 USGS / IAU 月面地貌数据；区域边界仅生成代表性排字走向，不作为精测山脊。路径按已配准视角投影，支持天平动、旋转、镜像和镜头畸变，按需缓存，不参与识别计算。 / Bundled about 0.17 MB of offline paths derived from USGS/IAU geometry supplied by 10deg. Area-derived axes are representative label routes, not surveyed crests. Projection follows the registered view, libration, rotation, reflection and lens distortion; cached paths do not enter recognition.

本次更新源码，安装包仍为 0.11.0。 / Source update; downloadable apps remain at 0.11.0.

## 0.11.2

2026-11-02

- 合并蔡明翰（Evan Tsai）的 [PR #18](https://github.com/Fluorine7/MoonLabeler/pull/18)：兼容 Windows venv 启动器与实际解释器的父子进程关系，避免新窗口已经启动却被误判失败或超时；继续校验交接归属和所选语言。 / Merged Evan Tsai's PR #18 to accept Windows venv interpreter acknowledgements through their launcher parent, while retaining process ownership and language validation.
- 增加普通解释器也能运行的“仅父 PID 匹配”和非字典交接数据回归测试；将虚拟环境、重启交接及 Windows UTF-8 兼容要求写入 Agent 规则。 / Added platform-independent regression cases for parent-only PID matches and non-dictionary markers, and documented the compatibility requirements in the Agent rules.

本次更新源码，安装包仍为 0.11.0。 / Source update; downloadable apps remain at 0.11.0.

## 0.11.1

2026-10-29

- 文字颜色和着陆点颜色选择框跟随简体中文、繁体中文或英文界面，修正 Windows 中文界面中颜色框仍显示英文的问题。 / Colour pickers follow the application language, including Chinese interfaces on Windows.
- 新增普通与艺术标注共用的文字不透明度滑块，文字与描边实时更新，保留位置和文字缓存；随工程保存，PNG / SVG 同步应用。旧工程默认完全不透明。 / Added live text opacity shared by standard and artistic labels, preserving layout and caches, with project persistence and PNG/SVG export. Older projects remain fully opaque.
- 状态栏新增“中止当前任务”。下载连接或读取停滞时可以取消并关闭窗口，取消后保留完整缓存并清理临时文件；缺失星历统一使用可取消的下载流程。修复此前下载缺少取消通道、忙碌状态拒绝关闭窗口的问题。 / Added Cancel task. Stalled downloads can be cancelled and the window closed while keeping complete caches and removing partial files. Missing ephemerides use the same cancellable downloader, fixing uninterruptible downloads and blocked window closure.
- 语言入口增加双语提示“界面语言 / Language”及“Language / 中文”，与计算设置、帮助等保留在工具栏右侧，支持 Cmd / Ctrl + Shift + L；窄窗口为设置区保留宽度，工程操作可从“更多操作”进入。修复“更多操作”箭头被内边距遮住的问题。 / Added a bilingual language switch beside compute settings and help on the right, with Cmd / Ctrl + Shift + L. Narrow windows reserve space for settings and keep project actions in the More actions menu. Fixed padding hiding the overflow arrow.
- 语言重启等待新窗口确认就绪后才关闭旧窗口；新进程异常退出、超时或未应用所选语言时保留旧窗口并报告启动日志，避免启动命令返回成功后程序仍消失。 / Language restarts wait for the replacement window to acknowledge readiness. Failed, timed-out or incorrectly localized replacements leave the original window open and report the startup log.

本次更新源码，安装包仍为 0.11.0。 / Source update; downloadable apps remain at 0.11.0.

## 0.11.0

2026-10-28

- 修复高程读取中断后打印异常可能崩溃的问题：映射缓冲区随最后一个数组引用释放，避免提前关闭仍被使用的数据；不复制高程图。 / Fixed crashes while reporting interrupted terrain work by retaining mapped buffers until their last array reference is released, without copying the DEM.
- 改善低对比月面配准：月缘和月相给出唯一方向、但月海纹理不足时，按该方向重新匹配高程细节；结果仍须通过四分区留出验证、新参考图和独立月缘检查，已成功的快速路径不增加这一步。 / Added a bounded terrain fallback for distinct limb/phase poses with weak albedo, retaining spatial holdouts, fresh-render and independent limb checks; successful fast paths skip it.
- 辅助找坑增加坑缘与邻近纹理的对比，减少密集山脊造成的圆形误检，并合并同一坑底的重复圆圈。 / Assisted detection now compares circular rims against nearby terrain and merges duplicate floor circles.
- 校准页新增识别排除区域，支持半透明红色画笔、直径滑块、橡皮擦、撤销和重做，随工程保存，供自动识别与辅助找坑共用；不影响现有标注和导出。顶部新增标注、蒙版预览开关。 / Added persistent recognition exclusions with a brush, diameter slider, eraser, undo and redo, plus independent label and mask preview toggles. Existing annotations and exports are unchanged.
- 排除区域同时参与月面选择和亮度阈值估计，避免已涂掉的大型插图继续干扰识别；保留未被涂抹的画面边缘部分坑缘。 / Masked insets no longer influence lunar-region selection or brightness thresholds; unrelated exclusions preserve valid partial craters at the image edge.

提供 Windows x64 和 macOS 14.4+ Apple Silicon 应用包。 / Windows x64 and macOS 14.4+ Apple Silicon app packages.

## 0.10.3

2026-10-28

- 整理 `.moonlabel` 配准读取规范和地图贴图示例，供 Tsukikage 等软件接入；工程补充原图尺寸与坐标约定，保留旧文件兼容。 / Documented the project format and photo projection for map integrations; added image dimensions and coordinate metadata without changing existing fields.
- 打开工程时核对照片尺寸，避免把原有配准套到缩放后的照片上。 / Check photo dimensions when reopening a project to avoid applying registration to a resized image.
- 改善疑似坑筛选，排除月盘外缘、独立插图和文字带来的误检；自动识别失败后，提示单独运行辅助找坑。 / Reduced false crater candidates from the lunar limb, detached insets and captions; clarified how to run assisted detection after automatic recognition fails.
- 修正 macOS 云端测试将等待超时计入界面卡顿的误报，仍保留 60 ms 标准。 / Fixed false macOS CI latency reports caused by test sleep overshoot, keeping the 60 ms limit.

本次更新源码，安装包仍为 0.10.2。 / Source update; downloadable apps remain at 0.10.2.

## 0.10.2

2026-10-26

- 地形类别改为默认折叠的多选框，支持同时标注多种地形；保留旧工程的类别选择。 / Feature types now use a collapsed checklist with multiple selection; existing project filters are preserved.
- 两种晨昏线统一使用虚线，预览与 PNG / SVG 导出一致。 / Both terminator sources now use dashed lines in the preview and PNG/SVG exports.
- 示意图补充南北极标记，背面极点用方向箭头表示；原始样式的取景范围不再给月球染色。 / Added locator pole markers and direction arrows for hidden poles; the original-style footprint no longer tints the lunar surface.
- 受光阈值移到“标注内容”，地名和地图共用；拖动实时显隐标签，保留原来的位置和排版。 / Moved the shared light threshold to annotation content. Labels and maps use the same value; dragging changes label visibility without moving them.
- 提供 Windows x64 和 macOS 14.4+ Apple Silicon 应用包。 / Windows x64 and macOS 14.4+ Apple Silicon app packages.

## 0.10.1

2026-10-26

- 修复切换手绘风后仍画椭圆的问题：缺少坑缘时后台按 DEM 提取并缓存，数据不足时明确提示参考圈。 / Fixed hand-drawn outlines falling back silently to ellipses; missing crests are traced from the DEM in the background and cached, with an explicit reference-ring fallback.
- 切换坑缘形状只更新轮廓线，保留文字缓存和标签位置，避免生成完成时卡顿。 / Rim shape changes reuse labels and text caches, avoiding a pause when tracing finishes.

## 0.10.0

2026-10-26

- 新增蓝晒星图、铜版图录、水墨朱砂、红警地形图，配套高程着色、等高线和图例。 / Added cyanotype, copperplate, ink/cinnabar and Red Alert terrain themes with matching map layers and legends.
- 新增照片区域示意图，外观跟随艺术样式，可按住 Cmd / Ctrl 移动，位置随工程保存并用于 PNG/SVG。 / Added a themed photo-footprint locator with Cmd/Ctrl dragging and saved positions in PNG/SVG exports.
- “重新生成标注”固定在标注页顶部，合并重复的应用按钮；重排标签不再顺带应用其他待修改设置。 / Pinned Regenerate annotations at the top of the tab and removed the duplicate Apply button. Reflow leaves other pending settings untouched.
- 修正待应用样式与实时滑块相互干扰的问题，地形类别跟随简体、繁体或英文界面显示。 / Fixed live sliders modifying the applied map while another style was pending; feature types now follow the interface language.
- 分段填充后台文字预览，缩放、拖动可及时中断；关闭或隐藏画布后停止细化任务。 / Split background text fills for responsive navigation; hidden or closed canvases stop refinement.
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

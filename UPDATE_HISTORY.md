# Update History / 更新历史

[README / 项目主页](README.md) · [中文使用说明](README.zh-CN.md)

按版本从新到旧排列。0.4.4 及以后的记录依据 Git 中保存的版本、对应改动和开发记录整理；更早的原型见文末。当前 Git 未保存独立的 0.5.0 版本，参考点辅助自动配准的首个可核验版本为 0.5.1。

Entries are listed newest first. Versions from 0.4.4 onward are reconstructed from saved Git versions, their changes and development notes. Earlier prototypes are summarized at the end. No separate 0.5.0 version is preserved in Git; reference-guided automatic registration first appears in the verifiable 0.5.1 version.

## 1.9.2

2026-10-23 · 受光覆盖、自动阈值与柔和过渡。

本次仅更新源码并推送 GitHub，不构建安装包、不创建 Release。此前的打包继续暂停，现有本地 1.9.1 macOS 包不包含本次改动。

- 恢复可选的“地图仅覆盖受光区域”，按照片亮度自动估计阈值；经纬网、高程和等高线共用柔和渐隐边界，保留亮坑缘包围的暗坑底。关闭后覆盖全部有效月面，地名、晨昏线与图例独立保留。
- 阈值滑块实时更新，点击“自动”恢复照片估计；自动模式和手动数值随工程保存。滚轮只滚动面板，不修改阈值；其他待确认设置不被顺带应用。
- 调节复用照片明暗及既有地图，不重新采样高程、提取等高线或排版标签。柔化蒙版只合成当前可见区域，避免高倍缩放分配整幅放大图像而卡顿。PNG / SVG 共用渐变蒙版，矢量路径仍可编辑。
- 覆盖不依赖拍摄时间或太阳方向，也不修改原图与配准。选择艺术主题时预填开启；缺少新设置的旧工程保持原有覆盖，废弃的 `map_lit_only` 字段继续忽略。

### English

Source-only update, without packages or a Release. Restores optional photo-lit map coverage with an automatically estimated brightness threshold, a live manual slider and Auto reset. Elevation, contours and the grid share a softly feathered boundary; enclosed crater shadows remain covered, while names, the terminator and legend stay independent. Threshold controls preserve wheel protection and unrelated pending edits. Cached photo analysis and maps are reused, and compositing stays bounded by the viewport during high zoom. PNG/SVG use the same soft mask, with editable vector paths retained. Saved settings round-trip, older projects retain their previous coverage, and the original photo, ephemeris and registration remain unchanged.

## 1.9.1

2026-10-23 · 艺术地图排版、图层性能与导出修复。

打包与发布暂停：已完成的本地 macOS 包先保留；Windows 云构建已取消，1.9.1 Release 尚未发布。恢复发布时只附 macOS Apple Silicon 与 Windows x64 两个应用 ZIP 包，中间文件留在 Actions 或本地。已有工程、原始标注与手工编辑继续保留。

新增 **蔡明翰（[Evan Tsai](https://www.facebook.com/mjrt.mj)）** 的贡献致谢：繁体中文支持及 Windows 部分问题修复。软件内致谢和中英文文档同步更新。

地图图层在此版本移除“仅覆盖受光面”，经纬网、高程和等高线覆盖全部有效月面，忽略旧工程的对应开关；原有受光地形名称筛选保留。

“中世纪风”以古航海地图为审美参考，采用蓝灰古金配色、分类衬线地名、疏排弧形大地名和斜体地形名称，收起菱形、下划线及大坑圈，SVG 保留可编辑的逐字旋转文本组。另增旷野平面地形图主题与可独立调节的 DEM 等高线。

修复艺术地名一经 Cmd / Ctrl 拖动就永久增加引线的问题：保存位置不再改变显示风格；普通地名仅在拖动时显示定位辅助线，松开鼠标或修饰键、切离画布即隐藏，PNG / SVG 不导出辅助线。原始标注的引线、着陆点符号及旧工程的手动位置保留。

艺术地名按最终文字位置切换排版：完整位于已配准月盘内时保留弧形，越过月缘或排到月盘外时使用直线基线；自动布局和手动拖动共用判断，保留字号、疏排字距与固定位置。布局为两种形状预留空间，过期文字预览不会覆盖切换后的形状，PNG / 可编辑 SVG 使用相同规则。

艺术样式的照片底图先去色，再叠加主题配色，避免彩月原色与地图色混合；预览、PNG 和 SVG 一致，低不透明度或关闭着色时也使用灰度底图。切回原始样式恢复彩色，原图文件及识别、配准输入保持不变。

修复艺术图层开启后平移、缩放及不透明度滑块卡顿：复杂等高线复用有界预览和缩小层级，文字复用绘制缓存，PNG 按原图尺寸重绘等高线，SVG 保留原始矢量路径。各类导出默认沿用照片目录和文件名主干。带 ICC 的照片先将显示副本转换到 sRGB，再合成艺术配色与文字；PNG 嵌入 sRGB 配置，SVG 使用同一转换后的底图。原始 RGB、识别与配准输入保持不变。

艺术图层面板移除常驻说明与重复的成功状态，仅在处理进行中或需要处理问题时显示提示。修复打开照片或工程时 ICC 转换失败造成工程信息与旧画面错配的问题：色彩转换成功后才切换当前文档，失败时保留当前工程及未保存的编辑。

修复大照片缩放时文字缓存额外缩放、导致字号忽大忽小的问题；文字始终保持原图坐标下的比例，连续缩放复用现有画面，在后台补齐文字清晰度。等高距默认改为自动，按当前视野内高程梯度选择，手动间距及旧工程数值保留；实际间距同步显示于下拉框、图例及导出。等高线按独立曲线分开绘制，提取和预览生成移至后台；完成时不再重建标签，等待期间仍可缩放、平移。经纬网同样复用有界预览，PNG 按原图尺寸绘制，SVG 保留矢量网格。

新增默认关闭的晨昏线图层，提供“照片估计”虚线及“工程时间（理论）”实线；独立开关与实时不透明度滑块，不依赖 DEM，不裁切其他图层。默认从照片的大范围明暗交界估计，避免未核实的工程时间把理论边界画进亮区；缺少可靠交界时提示并留空，不把暗坑或局部阴影当成晨昏线。估计不修改时间、太阳方向和配准，也不模拟精确地形阴影。工程保存与 PNG / SVG 导出包含该设置和线条，SVG 标记来源，仅理论线附带工程计算时间。同步加粗经纬网与等高线、增加对比衬边并区分主线，改善 100% 不透明度在适合窗口显示时仍不明显的问题。

### English

Packaging and publication are paused; the Windows run was cancelled and no 1.9.1 release was published. On resumption, only the macOS and Windows app ZIPs will be attached. Refines medieval and wilderness map styling, adds optional photo-estimated or theoretical terminators, and chooses contour spacing automatically. Improves canvas responsiveness and text-cache scaling; regional captions outside the lunar disc use a straight baseline, and ordinary art captions show locator guides only while dragging. Exports retain the source filename, with an sRGB-converted photo base and an embedded sRGB profile in PNG. Credits 蔡明翰 (Evan Tsai) for Traditional Chinese support and fixes for several Windows issues.

## 0.9.0

2026-10-23 · 可选艺术主题、月面地图图层与交互完善。

- 新增默认关闭的手抄本艺术主题、10° / 15° / 30° 经纬网与 LOLA 高程着色，保持原始标注、配准、手工文字和固定位置。切回原始样式可恢复已有配色与字重。
- 手抄本采用系统衬线字体、浅金字芯、深色光晕、暖金引线和菱形纹饰；高程颜色融合原照片明暗，提高浓着色时的地形层次与文字可读性。
- 网格和高程不透明度改为带百分比读数的滑块；图层首次应用后，拖动实时更新，不重新取样 DEM、不重排标签，也不应用其他待确认设置。工程、PNG 与 SVG 反映当前已应用的不透明度。
- 统一保护数字、日期、下拉框和滑块：滚轮与触控板只滚动面板，控件聚焦后也不改值；键盘、按钮和明确拖动继续有效。新增控件沿用同一保护，交互约束写入项目 AGENTS.md。
- 修复参考球面日夜判断误裁实拍亮地形的问题。高程图和经纬网优先使用照片中的可见地形范围，边界柔和渐隐，保留亮坑缘包围的暗坑底；无照片时才使用工程太阳方向。显示蒙版与星历、配准和 DEM 分开，不作为严格的物理日夜边界。
- 地名优先于经纬度数字，自动排版为高程色标预留空间。图层支持旋转、镜像及已有的目镜畸变校正；无数据及月盘外区域透明。高程显示栅格最长边为 1000 像素，精度受实际 DEM 限制。
- SVG 保留可编辑文字、网格和纹饰；文字描边兼容忽略 SVG 2 `paint-order` 的渲染器。高程图后台生成，复用未变化的地理采样；重新配准或更换照片使缓存失效，数据缺失或生成失败时保留标注并阻止不完整导出。

### 升级

已有 `.moonlabel` 工程继续使用，旧工程默认保持原始样式并关闭地图图层。在“标注 → 艺术与地图图层（可选）”启用；首次使用高程着色需下载基础 LOLA 数据或导入 DEM。源码用户按原安装方式更新。0.9.0 安装包暂缓构建，现有独立 App 下载仍为 0.8.0，不包含本次新功能。

### 发布前验证

本机项目测试 **582 项通过、6 项按条件跳过**，涵盖实拍识别、球面及地形投影、工程兼容、PNG / SVG 导出、滑块拖动、滚轮保护与光照误裁回归。另检查高程不透明度 85% / 100% 的实拍效果，以及原始模式切回后的像素一致性。本次推送触发的 GitHub Actions 已取消，跨平台检查与安装包构建、验证暂缓。

### English

Source update only for now: installer builds are deferred, and the existing 0.8.0 downloads do not include these changes.

Adds optional manuscript styling, selenographic grids and LOLA elevation colours while preserving the original annotation workflow, registration and manual edits. Elevation colours retain photographed relief; brighter serif lettering and dark halos improve contrast. Opacity sliders update applied layers immediately without moving labels or resampling the DEM. Wheel gestures scroll settings panels without changing focused values, and canvas zoom remains available.

Fixes bright photographed terrain being clipped by the project's spherical day/night model. Grid and elevation display masks now prefer observed terrain and retain shadowed floors enclosed by bright rims, with geometric fallback only when no photo is supplied. The display mask does not change the ephemeris, registration or height data. Projects and PNG/SVG exports preserve the optional layers; SVG text remains editable, including in renderers without SVG 2 paint-order support. Elevation display resolution is bounded to 1000 pixels on its longest edge and depends on the supplied DEM.

## 0.8.0

2026-10-22 · 多语言、跨平台兼容与依赖安全更新。由于最低 Python 版本和原生依赖安装方式发生变化，从 0.7.12 升为 0.8.0。

### 界面与兼容修复

- 补充本机打包的 macOS Apple Silicon 独立 App：最低系统版本为 macOS 14.4，包含 Python、Qt、FITS、最小 OpenCV 和四份离线星历；用户解压即可打开，无需编译器。检查全部 Mach-O 架构、最低系统版本和外部链接，并使用同一份 App 在 macOS 14.4+ / 15 上执行配准、坑缘检测、工程保存及 PNG / SVG 导出检查。当前为临时签名，未经 Apple 公证，首次打开可能需要在系统设置中允许。
- 补齐独立安装包的 TIFF Cython 扩展、Astropy 常量和解析表，修复“源码可用但冻结后缺模块”的 TIFF / FITS 读取问题；Windows 云端打包增加对最终 EXE 的配准、坑缘、工程往返、TIFF / FITS 与 PNG / SVG 导出检查。重新打包复用已验证的最小 OpenCV wheel。
- Windows 独立程序明确使用已修补的 Python 3.12.15，并从最终 EXE 再核对版本；避免 Actions 的 `3.12` 别名继续选中旧的 Windows 3.12.10 安装包。
- 合入 mjrtmj 的贡献（PR #1–#4）：新增繁体中文与英文界面、繁体及双语繁体地名、平台中文字体和字重选项；界面语言选择保存在本机，重新启动后生效。
- 修复 Windows 非 UTF-8 默认编码下的资源 / 工程读写，以及照片、DEM 与工程跨磁盘时的路径保存。
- 新增 Windows x64 免安装版与云端打包流程（PR #12、#13）：Release 中下载 ZIP，完整解压后运行 `MoonLabeler.exe`，无需自行安装 Python 或编译器。内含最小 OpenCV、FITS 支持、示例、使用说明、许可和四份 JPL 星历；打包前解析星历，下载失败即停止，云端冒烟检查启动与完整缓存复制。Windows、macOS 和 Linux 打包模式分别使用各自的用户缓存目录。
- 补齐繁体地名检索和英文候选列表；错误提示保留原始文件路径，避免翻译改写路径；自动识别失败时继续保留已有配准、参考点和标签。

### 安全与原生构建

- 最低运行版本升为 **Python 3.12**。补声明实际使用的 certifi，安全基线包括 Qt 6.12、Pillow 13、certifi 2026.10.19；同时整合 NumPy 2.5.4、PyShp 3.1.6 和 Skyfield 1.55 的依赖更新（PR #7–#9）。完整版本约束以 `requirements.txt` / `pyproject.toml` 为准。
- 高位深 RGB TIFF 改由 imagecodecs（2026.10.10 起）的 **libtiff 4.7.2 或更新版本**解码，保留 16 位样本、分离平面及方向处理；其他照片由 Pillow 解码。照片文件不再交给 OpenCV 解码。
- 以应用 wheel 内的**私有最小 OpenCV 4.14.0**替代通用 OpenCV 安装包。仅构建 core、imgproc、flann、features2d、calib3d、Python 绑定及保留上游 EdgeDrawing 实现的 ximgproc；不编译 imgcodecs、videoio、highgui 和旧 TIFF / OpenJPEG / OpenEXR / FFmpeg 等媒体组件，移除此前仍随完整 wheel 分发的闲置解码代码（PR #10、#11）。
- 固定 OpenCV / contrib 源码提交并核验下载摘要；应用 wheel 附带构建清单和第三方许可。构建检查同时核对编译输入、已安装模块、解码 API 和原生链接库；macOS wheel 的架构标签与实际二进制架构一致。
- 修复 Windows 虚拟环境下 Python 导入库定位及失效 Ninja 缓存；非 ASCII 构建路径使用独立的 ASCII 临时目录。若账户的临时目录也含非 ASCII 字符，先将 `MOONLABELER_OPENCV_BUILD_ROOT` 设为可写的 ASCII 目录（例如 PowerShell：`$env:MOONLABELER_OPENCV_BUILD_ROOT = 'C:\Temp\MoonLabeler'`）。Release 标签必须与包版本匹配，云端临时产物保留 7 天，正式下载文件放入 Release。

### 从 0.7.x 升级

1. 使用已安装安全补丁的 Python 3.12 或更高版本；Python 3.11 环境需重新创建虚拟环境。
2. macOS 可运行 `./start-mac.command`，脚本会检查依赖、移除旧 OpenCV 安装包，并在缺少私有扩展时构建。首次源码构建需要 C++ 编译器：macOS 安装 Xcode Command Line Tools，Windows 安装 Visual Studio Build Tools 的“使用 C++ 的桌面开发”组件，Linux 安装 `build-essential`；CMake / Ninja 由构建环境安装。
3. 手动升级时，先激活项目虚拟环境，再在仓库根目录执行：

   ```bash
   python -m pip install --upgrade "pip>=26.2" "setuptools>=83"
   python -m pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless
   python -m pip install --upgrade .
   ```

   `requirements.txt` 仅列外部运行依赖，单独安装它不会构建应用原生扩展。首次安装后，后续启动复用已有构建。
4. 已有 `.moonlabel` 工程、配准结果和 PNG / SVG 导出格式继续使用。已分发的旧安装包需要使用修复后的环境重新打包，更新源码不能替换其内嵌组件。

### 验证与检查范围

- 最小构建的[三平台 CI](https://github.com/Fluorine7/MoonLabeler/actions/runs/39713471197)通过：macOS ARM64 **486 通过 / 29 跳过**，Windows x64、Linux x64 各 **472 通过 / 43 跳过**；包含配准、坑缘检测、图片读取、工程保存和 PNG / SVG 导出，以及原生组件检查与依赖审计。缺少本地照片、数据或平台特性时按条件跳过；运行器自动化测试不等同于所有平台的交互式界面及显卡实机验证。
- 本机另覆盖实拍识别、导出、工程往返和识别失败保护；修正一条将异常对象直接当字符串检查的旧测试断言，相关 **4 项定向复测通过**，其余 **500 项通过、6 项跳过**的完整测试结果复用。
- 本机环境已移除完整 OpenCV 安装中的 **94 个旧原生库文件**。31 个外部已安装分发包的审计未发现已知漏洞；版本与文档整理复用这些仍有效的安全和功能检查结果。具体 CVE、原生组件边界、Rust GPU 依赖与历史安装包的检查范围见[安全审计记录](docs/security-audit-2026-10-22.md)。

### English

- Adds a locally built Apple Silicon macOS App for **macOS 14.4 and newer, including 15**, with Python, Qt, FITS and offline ephemeris bundled. PySide/Shiboken 6.12 bindings are rebuilt for the deployment target; all native libraries are checked. The app is ad-hoc signed and not Apple notarized. Adds frozen-program tests and repairs omitted TIFF Cython modules and Astropy constants/parser tables on both packaged platforms.
- Adds Traditional Chinese and English interfaces, Traditional/bilingual-Traditional captions, platform CJK fonts and font weights, integrating mjrtmj's PRs #1–#4. Fixes Windows UTF-8 resource/project I/O, cross-drive photo/DEM paths, Traditional name search, English candidate captions and preservation of paths in translated errors.
- Adds a Windows x64 portable ZIP and cloud build/release workflow (PRs #12–#13). Extract the complete ZIP and run `MoonLabeler.exe`, with no separate Python/compiler installation. It includes FITS support, the minimal OpenCV, examples, documentation, licenses and all four JPL kernels; failed downloads stop packaging. Frozen applications use platform-specific per-user caches. Windows source builds now locate the Python import library and recover from stale Ninja paths; a non-ASCII temporary directory requires a writable ASCII `MOONLABELER_OPENCV_BUILD_ROOT`.
- Raises the minimum to **Python 3.12**, updates security dependency baselines and integrates NumPy, PyShp and Skyfield updates. High-bit-depth RGB TIFF decoding uses imagecodecs with **libtiff 4.7.2+**, preserving 16-bit samples; Pillow handles other images.
- Replaces the full upstream OpenCV wheel with a pinned private **OpenCV 4.14.0** build containing only array-processing modules and upstream EdgeDrawing. Image/video codecs and their unused TIFF, OpenJPEG, OpenEXR and FFmpeg components are excluded. Source hashes, compiled inputs, installed modules, linked libraries and macOS architecture tags are checked; native notices and a build manifest ship with the wheel.
- **Migration:** use a patched Python 3.12+ interpreter and a C++ compiler for the first source build. macOS users can run `./start-mac.command`; manual upgrades should activate the project environment, remove all four legacy OpenCV wheel variants and run `python -m pip install --upgrade .`, as shown above. Installing requirements alone does not build the native extension. Existing project/export formats remain supported; older distributed installers need rebuilding.
- Three-platform wheel builds, regression tests and dependency audits passed: **486 passed / 29 skipped** on macOS ARM64 and **472 passed / 43 skipped** on each of Windows x64 and Linux x64. Additional local photographs and failure-preservation workflows passed after correcting one stale exception-message assertion; four focused tests were rerun, while the other 500 passing results were reused. These results do not claim interactive validation of every OS/GPU or repairs to historical installers. See the linked CI and audit record for evidence and scope.

## 0.7.12

修复 0.7.11 混用配准表面基准的标注回归。`0708.jpg` 按已知日期 2026-07-08、未知 UTC 暂按 15:00 复现，实际走球面阴影参考及视角微调，0.7.11 却给最终落点追加高程；傅科、布格等处额外位移约 16–18 px。现在由配准结果明确记录 sphere / terrain，只有真正使用高程表面拟合的结果才采用高程标注；其他路径保留原参考球面坐标。自动高程路径的标注与拟合使用同一基础 DEM，预览选择和新导入 DEM 不覆盖已拟合快照。手动高程拟合及视觉中心功能保留。

工程保存表面类型。新增实拍固定配准回归、表面标记传递、非法标记校验和自动调用限制。对 `0708.jpg` 再次执行实际自动按钮，矩阵、几何及完整识别验证记录与修复前完全相同；检查的九个地貌落点及坑缘轮廓与 0.7.10 一致，额外偏移为零。这是消除本次回归，不代表原配准已无误差，也未确认照片的精确 UTC。

Version 0.7.12 fixes the annotation regression caused by mixing projection surfaces in 0.7.11. Replaying `0708.jpg` on its known date, 2026-07-08, with 15:00 UTC assumed because the actual time is unknown, uses a spherical shading reference with view refinement. The extra post-fit elevation displaced Foucault and Bouguer by approximately 16–18 pixels. Results now record sphere / terrain explicitly; only actual relief-aware fits apply display heights and visual rim centres. Automatic relief annotations use the same basic DEM as the fit; preview-map selection and subsequent imports do not replace an existing fitted snapshot. Height-aware manual fitting remains supported.

Projects persist the surface type. Regressions cover the fixed real-photo pose, surface propagation, invalid metadata and automatic sampling policy. Repeating the actual `0708.jpg` button workflow retains identical matrices, geometry and complete recognition-validation records; all nine checked anchors and crater outlines match 0.7.10 with zero added displacement. This removes the introduced regression, not all original registration errors, and does not establish the actual capture time.

## 0.7.11

将地形高程从参考图/坑缘补齐到最终标注落点。有本地 LOLA 数据时，批量采样画面附近的地貌高度和足够大的目录圈；已有连续高程坑缘优先。完整可见的大坑按默认椭圆或可选轮廓的视觉中心布置引线；跨月缘、非闭合或退化轮廓保留地理落点。月溪、直壁、小坑和着陆点继续使用短引线；着陆点不作坑缘居中。采样不下载新数据，缺失或无效高度退回参考球面。快照与来源/分辨率随工程保存，PNG、SVG 和重开使用同一份数据，手动文字位置保留。日期、配准或目录更新时失效重建；标注坐标不反馈到自动识别与验收。纯手动校准使用同一套高程/视觉落点重新拟合和显示偏差，避免球面拟合后重复加高程；无 DEM 的球面流程保持原样。增加 Autolycus、Timocharis、Pytheas、Manilius 的重要目标避让保护，避免小幅坐标变化将这些醒目地貌挤掉。

完成高程落点/闭合坑缘中心、月缘残弧拒绝、镜像与目镜畸变、工程校验/兼容、离线保存与重开、重画不重读 DEM，以及北极、南极、克拉维斯坑群、Hadley C、手机目镜后、全月图等相关回归。四份既有实拍工程中，批量采样本机约 7–11 ms；实际手机和彩色整月盘按钮流程约 11–14 ms。这些是单轮本机测量，不代表所有设备。两张照片的配准矩阵与识别验证记录和 0.7.10 完全一致；标签布局可随落点及优先级变化，不宣称所有偏移已消除。

Version 0.7.11 carries local elevation into final annotation anchors. Existing LOLA maps batch-sample on-frame features and sufficiently large catalogue rims, with traced crests taking precedence. Complete visible large craters use the visual centre of the default ellipse or optional contour; incomplete, occulted or degenerate rings retain geographic anchors. Rilles, scarps, small craters and landing sites keep short leaders; landing sites are never rim-centred. Missing or invalid height data falls back to the reference sphere without extra downloads. Projects persist the small snapshot and its provenance for offline redraw, PNG/SVG export and reopening. Manual caption positions are retained. Date, pose and catalogue updates invalidate derived data; display coordinates never feed back into automatic recognition validation. Pure manual calibration fits and reports errors on the same elevated/visual anchors as the display, preventing double-counted relief; the sphere-only path remains available without a DEM. Autolycus, Timocharis, Pytheas and Manilius now reserve layout space as important landmarks.

Related regressions cover display heights and rim centres, partial-limb rejection, mirroring and afocal distortion, project validation and compatibility, offline round-tripping, redraw without DEM reads, and real north/south polar, Clavius, Hadley C, phone and full-Moon images. Local single-run batch sampling took approximately 7–11 ms for four saved real-photo projects and 11–14 ms in the phone/colour full-Moon button workflows; these are not general timing guarantees. Both button workflows retain exactly the same pose matrices and recognition validation records as 0.7.10. Layout can change with corrected anchors and priorities; remaining photographic offsets are not claimed resolved.

## 0.7.10

将自动坑缘检测推迟到实际需要坑群识别时；参考点辅助配准保留原检测证据。纹理或月缘已通过的照片不再额外找坑，也不覆盖用户修正过的辅助候选中心。目镜重匹配复用同一搜索图像的照片特征，只重提取参考图，避免第二次灰度增强与 SIFT 提取；不同裁取区域与后续识别独立准备。验证阈值、镜像检查、投影与光学校正不变。手机 `2305271151.jpg` 和彩色整月盘 `230603-2.jpg` 的配准矩阵、验证记录与标签数量均与改动前相同，分别为 56 / 61 个标签。

Automatic crater detection is deferred until crater-pattern matching needs it; reference-guided registration retains its existing detection evidence. Successful texture/limb registration skips unused detection and preserves reviewed candidate centres. Afocal rematching reuses the current search image's photo descriptors and re-extracts only the aligned reference, avoiding a second contrast-enhancement/SIFT pass. Other crops and subsequent searches prepare independently. Validation thresholds, mirror checks, projection and optical correction are unchanged. The phone photo `2305271151.jpg` and colour full-Moon photo `230603-2.jpg` retain identical registration matrices, validation records and label counts of 56 / 61 compared with the previous version.

76 项相关测试通过，包括模式约束、分支调用、错误月缘拒绝、实际局部照片和 Hadley C 辅助配准。局部照片异步测试首次触及原有 15 秒等待上限，单独限制 OpenCV 为两线程复跑通过；未修改测试等待上限或识别阈值。耗时随运行负载变化，不据此推算统一提速比例。

All 76 related tests pass, covering mode constraints, branch execution, incompatible-limb rejection, a real close-up and Hadley C guided registration. The asynchronous close-up test initially hit its existing 15-second wait limit and passed when rerun alone with two OpenCV threads; neither the test timeout nor recognition thresholds changed. Wall-clock timing varies with runtime load, so no general speedup percentage is claimed.

## 0.7.9

拍摄条件新增“拍摄方式：自动 / 相机直拍 / 目镜后”，默认自动。相机直拍禁用目镜畸变拟合及其重匹配重试；自动与目镜后保留先普通配准、必要时校正的相同策略，验证门槛不变。设置传递到裁取窗口和完整画面的识别流程，只影响下一次无参考点自动识别，切换时保留已有配准、标注及参考点。随工程保存，旧工程缺省为自动，打开新照片恢复自动。82 项相关测试通过，覆盖模式传递与禁用、工程兼容和界面流程，以及手机照片、整月盘和小月盘回归。

Capture conditions now offer Auto / Direct camera / Afocal, defaulting to Auto. Direct camera disables optical-distortion fitting and its rematching retry; Auto and Afocal retain the same ordinary-registration-first fallback with unchanged validation. The policy reaches both compact-field and full-frame searches and affects only the next unguided automatic search; changing it preserves the current pose, labels and reference points. Projects save the selection; legacy projects and new photos default to Auto. All 82 related tests pass, covering policy propagation and exclusion, project compatibility, UI workflows, and phone, full-disk and small-disk regressions.

## 0.7.8

已有较强纹理匹配和独立月缘测量、但目镜畸变校正失败时，增加一次受限重试：按粗定位结果对齐参考图，再提取对应点，恢复到原图与月面参考坐标后重新验证。原本成功的识别不增加重试；保留原有对应点数量、分区留出、受光月缘和稳定性要求，原照片不重采样。此前失败的 `2305271151.jpg`（2023-05-27 UTC 11:51）通过实际自动标注按钮流程，生成 56 个标签；本机本次约 1.9 秒，不代表所有目镜后照片的成功率或普遍耗时。39 项相关测试通过，包含此前两张手机照片、整月盘、五张南北极实拍、镜像/缩图坐标还原以及错误月缘拒绝。无新增运行依赖。

Version 0.7.8 adds one bounded rematching attempt when a strong coarse texture match and an independently measured limb exist but afocal correction fails. The reference is rigidly aligned before re-extracting correspondences; all points return to original reference/photo coordinates and undergo the unchanged optical, spatial-holdout and illuminated-limb checks. Already successful recognition does not incur this retry, and source pixels are untouched. The previously failing `2305271151.jpg` (2023-05-27 11:51 UTC) passes the actual annotation-button workflow with 56 labels in about 1.9 seconds in this local run, not a general afocal success-rate or timing claim. All 39 related tests pass, including the earlier two phone photographs, full-disk checks, five polar photographs, mirrored/downscaled coordinate restoration and incompatible-limb rejection. No new runtime dependency.

## 0.7.7

接入樊仕达（10deg）提供的 2026-10-16 综合地貌快照 `lunar_nomenclature(1).json`：10,431 条记录，含 9,040 条中文（9,031 条标注 LPND、9 条其他来源），新增 1,391 条仍为英文待译名。原有中文与来源原文未变化。保留完整元数据，适配混合来源链接；英文占位名不覆盖旧译名或主坑派生译名，也不产生双份英文标签。现有 USGS 地形编号、坐标、类别和着陆点图层不变，VMA 独有扩展条目暂仅作资料保留。更新中英文致谢与来源说明；79 项相关测试通过。

Version 0.7.7 imports 樊仕达 (10deg)'s 2026-10-16 combined `lunar_nomenclature(1).json` snapshot: 10,431 records, with 9,040 Chinese captions (9,031 labelled LPND and 9 separately sourced) and 1,391 added English placeholders. Existing Chinese wording and attribution are unchanged. Complete metadata is retained, mixed source-link ordering is supported, and English placeholders cannot override legacy/parent translations or create duplicate English captions. Active USGS IDs, coordinates, categories and the landing-site layer remain unchanged; VMA-only supplemental entries remain reference data. Bilingual acknowledgements and provenance are updated; 79 related tests pass.

## 0.7.6

修复暗半球在画面外时提前跳过长亮缘测量的问题：只有预测受光外缘不少于 120°、且至少 95% 在画面内，才允许继续测量，实际月缘和分区纹理验证仍须通过。自动识别失败提示保留纹理与目镜校正的具体原因。新增正向/镜像暗面裁切、亮缘裁切拒绝及实际按钮错误传递回归；49 项相关测试通过，包含此前两张手机实拍。2023-05-27 UTC 11:51 的新手机实拍仍未通过畸变分区验证，本版本不宣称解决该照片。

Version 0.7.6 fixes premature rejection of long bright-limb measurement when only the invisible hemisphere extends outside the frame. Measurement is attempted only if the predicted illuminated arc spans at least 120° and is at least 95% in frame; observed-limb and spatial-texture checks remain mandatory. Automatic failures retain atlas and eyepiece validation reasons. New normal/mirrored dark-hemisphere cropping, bright-arc clipping rejection and actual button error-propagation regressions pass, with 49 related tests including the two previously accepted phone photographs. The new 2023-05-27 11:51 UTC phone photograph still fails distortion holdouts and is not claimed as fixed.

## 0.7.5

修复带大片黑边的手机目镜后月牙照片被纹理覆盖率及空间网格误拒绝的问题。独立月缘测量用于确定月盘大小、拟合范围和覆盖率；复用同一批纹理对应点，错误点仍参与留出检查。保留至少 100 个内点、80% 共识、四区留出和 120° 受光月缘验证，原图不重采样。2025-02-04 UTC 10:49 实拍通过实际按钮流程；既有手机、整月盘、局部月面、南北极及拒绝错误月缘的相关测试通过。不增加拍摄模式选择。

MoonLabeler 0.7.5 fixes rejection of a sky-padded afocal crescent by canvas-based coverage and an outlier-stretched spatial grid. An independent limb measurement supplies Moon-sized fitting and coverage bounds. Existing texture correspondences are reused, and outliers still enter holdout checks. The minimum 100 inliers, 80% consensus, four spatial holdouts and 120° illuminated arc remain required; source pixels are untouched. The 2025-02-04 10:49 UTC photograph passes the actual annotation workflow, alongside related phone, full-disk, close-up, polar and incompatible-limb rejection tests. No capture-mode selector is added.

## 0.7.4

标签仅在按住 Cmd（macOS）或 Ctrl（Windows/Linux）并拖动时移动；普通拖动平移画面，双击仍可改名。画布顶部和悬停提示显示对应按键。

MoonLabeler 0.7.4 requires Cmd (macOS) or Ctrl (Windows/Linux) while dragging to move a label. Ordinary drags pan the image; double-click still edits the text. The canvas header and tooltips show the platform-specific modifier.

## 0.7.3

小月盘的计算窗口允许排除边框附近、窗口外的成行文字，避免较大图注阻止识别。原图水印不修改；第二个明显目标、内部文字和孤立的大标志仍保守处理。已验证 DWARF 实拍添加图注后的变体，以及横向、纵向边框文字。背景亮度处理不变。

MoonLabeler 0.7.3 lets compact-disk window selection disregard small, aligned border-caption components outside the search window. Source watermarks remain untouched; substantial secondary objects, interior text and isolated large logos remain subject to conservative checks. Tested with a captioned DWARF photograph and horizontal/vertical border-text fixtures. Background-brightness handling is unchanged.

## 0.7.2

修复小月盘被大片黑边包围时的识别失败。对孤立的小亮区裁取计算窗口，保留原有纹理及几何验证，结果换回完整原图坐标；原图、保存和导出尺寸不变。已用 DWARF 实拍验证。文件名时区规则不变，本地时间仍需换算为 UTC。

MoonLabeler 0.7.2 fixes recognition of small lunar disks surrounded by large black margins. A bounded search window preserves texture and geometry validation, then restores original-image coordinates. Source pixels, saved projects and export dimensions are unchanged. Verified on a DWARF photograph; filename timezone rules are unchanged and local capture times still require conversion to UTC.

## 0.7.1

增加受限的手机目镜后畸变校正。已有可靠纹理匹配、但月缘检查失败时才尝试；需同时通过分区留出与真实受光月缘验证。原图不重采样，文字、坑缘和导出共用校正坐标。已验证一张实拍，不保证所有手机、目镜组合或局部照片都能识别。

MoonLabeler 0.7.1 adds a guarded afocal-phone distortion fallback after a strong atlas match fails its limb check. Spatial holdouts and the observed illuminated limb must both agree. Original pixels remain untouched; labels, crater outlines and exports share the corrected coordinates. Validated on one real afocal photograph, not a general success-rate claim. Distortion-aware projects require 0.7.1 or later and cannot serve as planar local-reference projects.

## 0.7.0

中文地名优先采用 LPND 资料；加入可选 wgpu 跨平台 GPU 后端，使用 Metal / Vulkan / DirectX 12 生成高程阴影参考。“计算设置”简化为自动与仅 CPU，并显示可用设备。已实测 Apple M5 Pro；NVIDIA、AMD、Intel 的硬件与驱动兼容性仍需对应机器验证。

MoonLabeler 0.7.0 prioritizes contributor-supplied LPND Chinese names and adds optional cross-platform wgpu terrain shading through Metal / Vulkan / DirectX 12. Compute settings offer Auto and CPU-only, with the detected device shown. Tested on Apple M5 Pro; NVIDIA, AMD and Intel hardware/driver compatibility still requires native validation.

## 0.6.6

增加可选 wgpu 跨平台 GPU 高程阴影参考后端，通过 Metal、Vulkan 或 DirectX 12 调用可用设备。统一计算后端选择，保留 CPU 抽样复核、失败回退及旧 Apple MLX 后端兼容；精确投影、特征匹配和标注仍使用 CPU。

Added optional cross-platform wgpu terrain-shadow acceleration through Metal, Vulkan or DirectX 12. Unified backend selection while retaining CPU spot checks, failure fallback and compatibility with the earlier Apple MLX backend. Precise projection, feature matching and annotations remain on CPU.

## 0.6.5

增加顶部“计算设置”，当时提供自动、仅 CPU 和 Apple GPU 模式，并显示可用设备。设置保存在本机，下次计算生效，不随照片工程传递；环境变量可覆盖界面设置。

Added the toolbar's Compute settings dialog, initially offering Auto, CPU-only and Apple GPU modes with device availability. Preferences persist locally and apply to subsequent jobs independently of photo projects; environment variables can override them.

## 0.6.4

首次加入 Apple 芯片可选 MLX / Metal GPU 加速，用于生成高程阴影参考。保留 CPU 精确投影、临界像素复核，以及 GPU 不可用或执行失败时的 CPU 回退。

Introduced optional MLX / Metal acceleration on Apple silicon for terrain-shadow references, retaining precise CPU projection, boundary-pixel checks and CPU fallback when the GPU is unavailable or fails.

## 0.6.3

优化自动识别中的坑群索引构建，保留候选顺序和匹配验证条件。清理 UI 拆分后遗留的未使用导入与辅助函数。

Optimized crater-pattern index construction without changing candidate order or match validation. Removed unused imports and a helper left over from the UI split.

## 0.6.2

减少标签布局中的重复空间查询和无效碰撞检查。以已有布局结果做回归对照，保留重要目标优先级和原有排版规则。

Reduced redundant spatial queries and unnecessary collision checks during label layout. Regression comparisons against existing layouts preserve landmark priorities and placement rules.

## 0.6.1

哥白尼、第谷、柏拉图等常见重要目标优先占用标签空间，普通标签及地形中心向它们让位。重要标签在紧凑位置均不可用时，可有限扩大引线范围；保留用户手动位置、隐藏选择和数量上限。

Common important landmarks such as Copernicus, Tycho and Plato reserve label space before ordinary labels and terrain centers. A bounded wider leader search is allowed when compact positions fail, while manual positions, explicit hiding and the final label budget remain respected.

## 0.6.0

增加可选阿波罗与嫦娥着陆点图层，默认关闭。使用独立的浅青色、小档字号、十字与短引线；位置及来源随源码提供，工程保存和 PNG / SVG 导出使用相同样式。

Added an optional Apollo and Chang'e landing-site layer, disabled by default. Sites use a separate pale-cyan color, the smallest font tier, cross markers and short leaders. Bundled coordinates retain provenance; projects and PNG / SVG exports share the same styling.

## 0.5.11

改进高倍单坑照片的大坑候选检测，增加长弧椭圆提案及整圈边缘方向验证，大半径搜索使用较低工作分辨率。加入 WinJUPOS 文件名 UTC 时间导入，支持十分之一分钟与常见处理后缀。

Improved large-crater candidates in close-up photographs using long-arc ellipse proposals and rim-direction validation, with lower working resolution for large-radius searches. Added UTC capture-time import from WinJUPOS filenames, including tenths of a minute and common processing suffixes.

## 0.5.10

改进北极复杂地形的识别：几何与细节证据充分时，允许受限的高程精修结果通过联合验证。每轮分块搜索复用照片特征，阴影射线在遮挡或已离开地形范围时提前停止，减少重复计算。

Improved difficult northern-terrain recognition through a guarded joint geometry/detail validation route for refined results. Tile searches reuse photograph features, and shadow rays terminate once occluded or clear of terrain, reducing repeated computation.

## 0.5.9

修复部分模糊极区和拼接照片被过早拒绝的问题。粗匹配仅用于提名区域，必须重新取得分散对应点并通过高程、纹理和留出验证；排除照片自身的黑色拼接空白，同时保留坑内阴影检查。

Fixed premature rejection of some blurred polar and mosaic photographs. Coarse matches only nominate regions; fresh distributed correspondences must pass relief-aware, texture and held-out checks. Empty mosaic borders are excluded while internal crater shadows remain validated.

## 0.5.8

修复整月盘纹理配准在月缘附近的投影偏移。使用分散对应点精修整体视角，按实际月面范围计算验证覆盖，并以实拍长月缘独立检查中心和比例；原始星历与验证记录保存在工程中。

Fixed atlas-projection drift near the lunar limb. Distributed correspondences refine the global view, coverage is measured over the observed lunar field, and a long photographed limb independently checks center and scale. Original ephemeris geometry and validation records are saved in projects.

## 0.5.7

按投影视直径划分大、中、小三档文字，默认短边的 1.8% / 1.5% / 1.2%。增加“字号递减”设置，统一用于文字边界、避让、PNG 与 SVG，保留旧工程的统一字号兼容。

Added three font tiers based on projected apparent diameter, defaulting to 1.8% / 1.5% / 1.2% of the image's short side. The font-decrement control drives text bounds, collision avoidance, PNG and SVG consistently while preserving older projects' uniform typography.

## 0.5.6

年月日及 UTC 时分拆为独立输入框，保留输入满位后跳到下一框的操作。合并辅助找坑、地名确认与参考点配准流程，手动补点默认折叠；失败保留当前候选与参考点，打开新照片回到校准页并收起辅助内容。

Split capture date and UTC time into separate year, month, day, hour and minute fields with automatic focus advance. Unified candidate detection, name confirmation and reference-point registration, with manual placement collapsed by default. Failures retain candidates and points; opening a new image returns to Calibration and collapses assistance.

## 0.5.5

在紧凑的固定确认栏中持续显示当前候选编号、位置及所选地名。缩小候选列表和名称列表的占用，减少滚动时丢失当前确认对象的问题。

Kept the current candidate number, position and chosen name visible in a compact pinned confirmation footer. Reduced candidate/name list space so scrolling does not obscure the object being confirmed.

## 0.5.4

集成紧凑的日期、时间和候选坑复核界面。增加候选轮廓显示选项，并调整确认面板布局；检测辅助图层与导出标注保持独立。

Integrated compact capture-time controls and crater-candidate review UI. Added a candidate-outline display option and revised confirmation-panel layout while keeping review overlays separate from exported annotations.

## 0.5.3

修复参考点搜索、竞争区域判断、工程加载与照片读取中的问题。非法工程不再替换当前编辑内容；透明图按黑底合成，16 位 RGB TIFF 保留原精度后拉伸显示，同时完善下载和启动失败处理。

Fixed reference-guided search, competing-region checks, project loading and image import. Invalid projects preserve the current editing state; transparent images use a black background, and 16-bit RGB TIFF retains source precision before display stretching. Improved download and launcher failure handling.

## 0.5.2

高程后备识别在粗匹配已有充分证据、但最终明暗检查未通过时，先尝试含地形高度的局部精修。合并重叠分块的重复候选，限制精修区域数量，再执行原有最终验证。

The terrain fallback attempts relief-aware local refinement when a coarse match has sufficient evidence but fails the final lighting check. Duplicate overlapping-tile poses are merged, refinement attempts are bounded, and the existing final validation is reapplied.

## 0.5.1

确认一两个已知地形点后，可用周围纹理辅助自动搜索比例、旋转和镜像，并验证所有参考点。增加“用参考点自动配准”，辅助找坑调整为优先入口；窗口标题加入作者署名，失败保留参考点和已有配准。

One or two confirmed terrain points can guide automatic scale, rotation and reflection search, with surrounding texture and all reference points validating the result. Added Register automatically using reference points, placed candidate detection first in the assistance workflow, and added author credit to the window title. Failures preserve points and existing registration.

## 0.4.8

环形山名称确认改为直接可见的列表，修复 Hadley C 等单个搜索结果难以选中的问题。搜索清除旧选择，Enter 可选择首项，明确选择后再确认名称与候选中心。

Replaced crater-name confirmation popups with an explicit visible list, fixing single-result selection such as Hadley C. Searching clears the old choice; Enter selects the first result, and confirmation pairs the chosen name with the candidate center.

## 0.4.7

综合投影大小、坑缘对比和区域分布选择标注，主地形优先于附属字母坑。避让后从其余候选补位，数量上限约束最终显示结果；通过空间索引优化布局计算，并集成改进后的下拉菜单与折叠设置。

Annotation selection considers projected size, rim contrast and regional distribution, with named formations ahead of lettered satellites. Reserve candidates refill layout omissions up to the final label limit. Spatial indexing accelerates layout; improved dropdowns and collapsible settings were integrated.

## 0.4.6

局部坑群识别后使用小型 LOLA DEM 精修相机与观测方向，坑缘投影考虑地形高度。增加“椭圆 / 坑缘轮廓（手绘风）”选项，默认平滑椭圆；小坑使用短引线，轮廓与设置随工程保存并用于导出。

Local crater-pattern recognition gained camera/view refinement using a small LOLA DEM, with terrain height included in rim projection. Added Ellipse / Rim contour styles, defaulting to smooth ellipses; small craters retain short leaders. Contours and styling persist in projects and exports.

## 0.4.5

集成右侧检查器与校准、标注、参考三页 UI，梳理“选地名 → 标记中心 → 校准”的手动流程。加入小型高程阴影参考后备搜索和受空间留出验证约束的视角精修；具体 UTC 时间放入默认折叠设置，并完善 moonlib 参考代码致谢。

Integrated a right-hand inspector with Calibration, Annotation and Reference pages, and clarified the select-name → mark-center → calibrate workflow. Added a small terrain-shadow fallback and spatially validated view refinement. Exact UTC controls became collapsed by default, and acknowledgements credited the moonlib reference code.

## 0.4.4

首个保存在公开 Git 仓库中的 GPL-3.0-or-later 版本。支持 LROC 纹理、月盘轮廓及坑群目录配准，手动参考点校准、疑似坑检测、标签避让、工程保存和 PNG / SVG 导出；字号按原图短边缩放，并提供中文译名、近白文字和大坑参考轮廓。

The first GPL-3.0-or-later version preserved in the public Git repository. It includes LROC texture, lunar-limb and crater-pattern registration; manual reference calibration; candidate detection; collision-aware labels; saved projects; and PNG / SVG export, with image-relative font sizing, Chinese names, near-white text and large-crater reference outlines.

## 早期原型 / Earlier prototypes（0.4.4 以前 / before 0.4.4）

早期 0.2.x 至 0.4.3 原型围绕照片载入、NASA 时刻参考图、局部月面参考点、疑似坑检测与自动配准逐步开发，同时改进中文地名、字号比例、标签布局和大坑轮廓。这一阶段尚未保留逐版本 Git 快照，不能可靠恢复每个小版本的完整改动与发布时间，因此合并概述。

Early 0.2.x–0.4.3 prototypes developed image loading, NASA time-specific references, local terrain points, crater candidates and automatic registration, alongside Chinese names, relative font sizing, label layout and large-crater outlines. Per-version Git snapshots were not retained, so complete changes and release dates for individual prototypes cannot be reliably reconstructed and are summarized together.

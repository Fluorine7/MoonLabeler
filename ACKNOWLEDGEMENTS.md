# 致谢与算法来源

MoonLabeler 作者：**Fluorine Zhu**。本项目代码采用 **GPL-3.0-or-later**，完整许可见 [LICENSE](LICENSE)；第三方代码与数据的原有条款见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

感谢 **樊仕达（10deg）** 提供 **moonlib** 代码，作为本项目月面几何研究与实现的参考。

向 **Jim Mosher 与 Henrik Bondo** 致敬。他们创建的 **Lunar Terminator Visualization Tool（LTVT）** 将月面几何、已知地形校准和高程光照模拟带给了业余观测者。

MoonLabeler 参考这些公开方法，以 Python / Qt 独立实现当前功能。当前项目没有复制 LTVT 的 Delphi 源码，也不是原作者发布的 LTVT 版本。

- [LTVT 历史](https://github.com/pavolgaj/ltvt/wiki/History-of-LTVT)
- [LTVT 源码与文档存档](https://github.com/pavolgaj/ltvt)
- 本次研究的源码版本：`fermigas/ltvt`，提交 `ae048c7b8b0e8d2945b8f67e660d105d8a8e1dcb`。

## 来源与实现对应

| 来源支持的方法或事实 | 直接来源 | 当前实现与限制 |
| --- | --- | --- |
| 确定拍摄几何后，两个已知地形可求比例、旋转和偏移；第三点可检查校准 | [LTVT 照片校准文档](https://github.com/pavolgaj/ltvt/wiki/User-Photo-Calibration-Window) | 多点相似变换最小二乘拟合；显式比较镜像；加入逐点偏差与留出检查。仍是球面模型。 |
| 高程坡度和地形遮挡可用于模拟月面光照；Lambert 与 Lommel–Seeliger 是可选模型 | [LTVT DEM 选项](https://github.com/pavolgaj/ltvt/wiki/DEM-Options) | 实现坡度法线与有限步长的太阳射线遮挡；未实现完整三维表面求交及反照率纹理。 |
| LOLA 高度为 DN × SCALING_FACTOR；半径需要再加 OFFSET | [官方 LDEM_16 标签](https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/LDEM_16.LBL) | 将高度转换为 km，相对 1737.4 km 参考球面；检查数据坐标系、采样和长度。 |
| LDEM_16 为像素中心网格，16 像素/度，约 1895.21 m/采样点 | [LRO / LOLA 官方数据目录](https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/) | 双线性插值，全球经度接缝环绕；可按需读取更高分辨率区域数据。输出像素不等于地形分辨率。 |

Lommel–Seeliger 使用 `cos(i) / (cos(i) + cos(e))`；Lambert 使用 `max(cos(i), 0)`。其中 `i` 为相对地形法线的入射角，`e` 为出射角。显示提亮和 Gamma 仅用于参考图显示，不作为测光结果。

## 其他数据与软件

疑似坑中心检测改编自 **Ram Maruboina** 的 [Lunar Crater Detector](https://github.com/rammaruboina-rgb/lunar-crater-detector/tree/0babc2a6fb3d02cfbf58aa9bafe9f44edf8dc3dd)（MIT）。使用其 OpenCV 预处理、轮廓椭圆拟合和 Hough 圆检测思路，加入可配置半径、边缘支持检查、原图/局部视野坐标、人工复核与修正流程。未集成原仓库可选的 scikit-image Hough 椭圆路径或地貌陡峭度分类。完整版权和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

自动识别的部分坑缘检测调用 OpenCV contrib 的 **EDCircles / EdgeDrawing**，致谢 C. Akinlar、C. Topal 及 OpenCV 维护者。[官方接口与算法引用](https://github.com/opencv/opencv_contrib/blob/4.x/modules/ximgproc/include/opencv2/ximgproc/edge_drawing.hpp)。它合并边缘弧段并拟合椭圆，不提供月面地名识别。

目录匹配研究了 [wdoppenberg/crater-detection](https://github.com/wdoppenberg/crater-detection) 的三坑图案识别方法，以及 [Christian、Derksen、Watkins 的论文](https://arxiv.org/abs/2009.01228)。当前独立实现使用地面已知视角下的中心三角形边长比和半径比，再验证其他坑；没有复制该仓库代码、安装 Ellipse R-CNN 或声称实现论文中的通用椭圆投影不变量。

整月盘纹理配准使用 **NASA LRO / LROC 团队**的全球纹理图。致谢 NASA Scientific Visualization Studio、**Ernie Wright（USRA）**、**Noah Petro（NASA/GSFC）**及 LROC / LOLA 团队，来源为 [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/)。源码内置的 2048×1024 JPEG 经第三方镜像重压缩，保留原分辨率；原始 URL、固定镜像提交和处理说明见 [数据来源记录](moonlabeler/data/moon_albedo_2k.provenance.json)。它用于视觉配准，不作为定量测光数据。当前用双向 SIFT、相似变换 RANSAC 和月盘范围检查恢复地图到照片的位置，不将纹理点虚构为地名。

- 月面地名：[USGS / IAU Planetary Nomenclature GIS](https://planetarynames.wr.usgs.gov/GIS_Downloads)。
- 中文地名：[国家天文科学数据中心 · 天文学名词](https://nadc.china-vo.org/astrodict/)，致谢中国天文学会天文学名词审定委员会、词表编订者和数据中心。908 对源词条与链接保存于 `moonlabeler/data/chinese_names.json`；对照原名并去掉环形山类别后缀用于紧凑标注，卫星坑按主坑译名加字母派生。词条出版与审定状态以原网站为准，并不声称覆盖所有月球地名。未收录者保留官方英文名称。
- 星历与月球姿态：[JPL DE421](https://ssd.jpl.nasa.gov/planets/eph_export.html)，通过 [Skyfield 月面参考系接口](https://rhodesmill.org/skyfield/planetary.html)计算。
- 着陆点：[NASA NSSDCA 月面人造物位置表](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_artifact_impacts.html)，感谢 NSSDCA 与 LROC 团队。采用阿波罗登月舱下降级及嫦娥着陆器坐标，DE421 平均地球 / 极轴坐标系，北纬、东经为正；内置数据记录来源日期，不包含其代码。
- 高程：[LRO / LOLA](https://lola.gsfc.nasa.gov/) 科学团队及数据生产者。
- 在线参考：[NASA SVS 2026 月相与天平动](https://svs.gsfc.nasa.gov/5587/)。
- 配准回归照片：[NASA Galileo PIA00405](https://science.nasa.gov/photojournal/earths-moon/)。它用于已知图像变换的回归测试，未用于证明独立照片识别精度。
- 界面、数值与图像处理：Qt / PySide6、NumPy、Pillow、OpenCV、Skyfield 和 PyShp。
- [wgpu-py / wgpu-native](https://github.com/pygfx/wgpu-py)：提供跨平台 GPU 执行接口；WGSL 高程光照内核由 MoonLabeler 实现。
- Apple MLX / Metal：为 Apple 芯片提供可选 GPU 计算后端；高程光照内核由 MoonLabeler 实现。

## Acknowledgements and provenance (English)

MoonLabeler is authored by **Fluorine Zhu** and released under **GNU GPL version 3 or later**. We gratefully acknowledge the researchers, amateur astronomers, software developers, and data teams whose open work made this project possible.

- **Jim Mosher and Henrik Bondo — LTVT:** Their work inspired the known-terrain calibration and DEM lighting workflows. MoonLabeler independently implements these ideas in Python / Qt; it does not include LTVT Delphi source. See the [LTVT archive](https://github.com/pavolgaj/ltvt) and the calibration and DEM references above.
- **Ram Maruboina — Lunar Crater Detector:** Parts of the OpenCV preprocessing, ellipse-fitting, and Hough-circle approach were adapted from the fixed MIT-licensed version linked above. The original copyright and full MIT permission notice are preserved in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **C. Akinlar, C. Topal, and OpenCV contributors:** EdgeDrawing / EDCircles provides partial-edge grouping and ellipse detection. This is image geometry detection, not lunar place-name identification.
- **NASA SVS, Ernie Wright, Noah Petro, LRO, LROC, and LOLA teams:** Lunar textures, elevation data, and visualization references. The bundled texture's canonical source, fixed mirror, and JPEG recompression provenance are recorded with the data.
- **USGS / IAU planetary nomenclature contributors:** Terrain names, positions, categories, and diameters.
- **NASA NSSDCA and LROC:** [Landing-location coordinates](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_artifact_impacts.html) for Apollo LM descent stages and Chang’e landers, in the DE421 mean Earth / polar axis frame (north/east positive). The bundled data retain source and retrieval dates; no upstream code is included.
- **JPL and Skyfield contributors:** Ephemerides, lunar orientation, and observing geometry.
- **樊仕达 (10deg) — moonlib:** Provided code as a reference for this project's lunar geometry research and implementation.
- **National Astronomical Data Center and Chinese astronomical terminology contributors:** Sourced Chinese names. Each imported term retains its source URL. Lettered satellites derive their names from the parent term and the original official letter; they are not presented as independently approved translations.
- **chase-kusterer/lunar_stack, wdoppenberg/crater-detection, and cosinekitty/astronomy:** Studied for image matching, crater-pattern methods, and possible future ephemeris alternatives. Their code and models are not incorporated into the current application. Scope and fixed versions are documented in [REPOSITORY_RESEARCH.md](REPOSITORY_RESEARCH.md).
- The new wide-limb fallback independently fits the lunar outer circle and compares phase and high-pass LROC albedo templates. The limb-fitting approach was informed by the lunar_stack research; no SAM, learned model, or upstream source code is included. It rejects short polar arcs and ambiguous rotations or reflections.
- **Matt Pocock and contributors to [skills](https://github.com/mattpocock/skills):** Development and debugging workflows used during development. Skills are development aids, not runtime recognition algorithms, and are not bundled here.
- **Qt / PySide6, NumPy, Pillow, OpenCV, Skyfield, PyShp, and the Python ecosystem:** The application's UI, numerical, imaging, and data-reading foundations.
- **[wgpu-py / wgpu-native](https://github.com/pygfx/wgpu-py):** Cross-platform GPU execution. The WGSL terrain-shading kernel is implemented by MoonLabeler.
- **Apple MLX / Metal:** Optional GPU execution on Apple silicon. The terrain-shading kernel is implemented by MoonLabeler.

Thank you to the lunar photographers who provided local test images. Their photographs and derived exports are not included in this public source repository.

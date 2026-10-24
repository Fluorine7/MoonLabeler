# 致谢 / Acknowledgements

MoonLabeler 作者 / Author：**Fluorine Zhu**。代码采用 [GPL-3.0-or-later](LICENSE)；第三方代码、数据和依赖的条款见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

| 贡献者 / Contributors | 贡献与来源 / Contribution |
| --- | --- |
| **蔡明翰（[Evan Tsai](https://www.facebook.com/mjrt.mj)）** | 繁体中文支持及 Windows 部分问题修复。Traditional Chinese support and Windows fixes. |
| **[sothic](https://github.com/sothic)** | [PR #15](https://github.com/Fluorine7/MoonLabeler/pull/15)：工具栏缩放、原始大小按钮及快捷键。Toolbar zoom controls, actual-size view and keyboard shortcuts. |
| **樊仕达（10deg）** | 提供 moonlib 几何代码参考、LPND 中文地名与综合地貌资料，以及旷野风主题建议。[Tsukikage 高程标注修正](https://github.com/10deg/tsukikage/commit/88c0353883864d6d3556e85625852f57415908c7)启发了本项目独立实现的高程落点修正。Geometry references, name data and map-style suggestions. |
| **Jim Mosher、Henrik Bondo — LTVT** | 已知地形校准与 DEM 光照方法参考：[照片校准](https://github.com/pavolgaj/ltvt/wiki/User-Photo-Calibration-Window)、[DEM 选项](https://github.com/pavolgaj/ltvt/wiki/DEM-Options)、[研究所用版本](https://github.com/fermigas/ltvt/tree/ae048c7b8b0e8d2945b8f67e660d105d8a8e1dcb)。Calibration and terrain-lighting references; independently implemented in Python/Qt. |
| **Ram Maruboina — Lunar Crater Detector** | [固定 MIT 版本](https://github.com/rammaruboina-rgb/lunar-crater-detector/tree/0babc2a6fb3d02cfbf58aa9bafe9f44edf8dc3dd)的预处理、椭圆拟合和 Hough 圆检测思路用于疑似坑检测；版权与完整许可保留在第三方声明中。Adapted crater-candidate detection. |
| **C. Akinlar、C. Topal、OpenCV 贡献者** | [EdgeDrawing / EDCircles](https://github.com/opencv/opencv_contrib/blob/4.x/modules/ximgproc/include/opencv2/ximgproc/edge_drawing.hpp) 坑缘检测。Rim detection. |
| **NASA SVS、Ernie Wright（USRA）、Noah Petro（NASA/GSFC）、LRO / LROC / LOLA 团队** | [月面纹理](https://svs.gsfc.nasa.gov/4720/)、[高程数据](https://lola.gsfc.nasa.gov/)与[月相参考](https://svs.gsfc.nasa.gov/5587/)。纹理重压缩来源见[随数据保存的记录](moonlabeler/data/moon_albedo_2k.provenance.json)。Lunar textures, elevation and visual references. |
| **USGS / IAU、LPND、NADC 与地名资料整理者** | [地形目录](https://planetarynames.wr.usgs.gov/GIS_Downloads)、[LPND 中文译名](https://lpnd.bao.ac.cn/#/search?is=1)与[NADC 旧译名别名](https://nadc.china-vo.org/astrodict/)。Name catalogues and translations. |
| **Virtual Moon Atlas 维护者** | 综合快照中的[扩展地貌与分类资料](https://www.ap-i.net/avl/en/start)。Supplemental reference data. |
| **JPL 与 Skyfield 贡献者** | [DE421 星历](https://ssd.jpl.nasa.gov/planets/eph_export.html)与[月面参考系计算](https://rhodesmill.org/skyfield/planetary.html)。Ephemerides and lunar geometry. |
| **NASA NSSDCA、LROC 与 Galileo 团队** | [阿波罗 / 嫦娥位置](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_artifact_impacts.html)及[Galileo 回归测试图片](https://science.nasa.gov/photojournal/earths-moon/)。Landing coordinates and test imagery. |
| **Zelda Dungeon** | [旷野之息交互地图](https://www.zeldadungeon.net/breath-of-the-wild-interactive-map/)提供主题审美参考；本项目等高线由 LOLA DEM 生成。Map-style reference. |
| **chase-kusterer、wdoppenberg、Christian / Derksen / Watkins、cosinekitty** | 月缘、坑群和星历方法参考：[lunar_stack](https://github.com/chase-kusterer/lunar_stack)、[crater-detection](https://github.com/wdoppenberg/crater-detection)、[Astronomy Engine](https://github.com/cosinekitty/astronomy)。Method references. |
| **Matt Pocock 与 skills 贡献者** | [开发与调试工作流](https://github.com/mattpocock/skills)。Development workflows. |
| **Python、Qt / PySide6、NumPy、Pillow、imagecodecs、OpenCV、Skyfield、PyShp、Astropy、wgpu-py / wgpu-native、Apple MLX / Metal 贡献者** | 界面、数值计算、图像处理和可选 GPU 后端。Runtime foundations; individual licences are listed in the third-party notices. |

感谢提供实拍测试照片的月面摄影者。私人照片与派生导出不包含在公开仓库中。
Thanks to the lunar photographers who supplied local test images; their private photographs and exports are excluded from this repository.

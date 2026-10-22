# Third-party code notices

MoonLabeler code: Copyright (c) 2026 **Fluorine Zhu**, licensed under **GPL-3.0-or-later**. See [LICENSE](LICENSE). This license does not replace upstream copyright notices or blanket-relicense third-party data.

MoonLabeler 代码版权属于 **Fluorine Zhu**，采用 GPL v3.0 或更新版本。第三方改编代码的原始声明保留如下；外部数据及依赖沿用其原有条款。

## Lunar Crater Detector

Parts of `moonlabeler/craters.py` are adapted from the preprocessing, contour
ellipse fitting and Hough-circle approach in
[rammaruboina-rgb/lunar-crater-detector](https://github.com/rammaruboina-rgb/lunar-crater-detector/tree/0babc2a6fb3d02cfbf58aa9bafe9f44edf8dc3dd).
The integration adds user-defined radius limits, edge support checks, ROI and
original-image coordinates, duplicate filtering and the Qt review workflow.

MIT License

Copyright (c) 2025 Ram Maruboina

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## LROC lunar texture data

`moonlabeler/data/moon_albedo_2k.jpg` is a 2048×1024 JPEG derivative of
[NASA SVS CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/)'s `lroc_color_2k.jpg`.
Credit: NASA's Scientific Visualization Studio; Ernie Wright (USRA);
Noah Petro (NASA/GSFC); NASA LRO, LROC and LOLA science teams.
The polar portions of the original map use lower-resolution LOLA albedo.
This is a visual color texture, not a quantitative reflectance product.

NASA's original server was unavailable from this environment. The copy was
retrieved from Maxwell Lee's `physics-lab` repository at fixed commit
`b820546ec256c40a8a5adc2123805cfcf02c4338`, whose texture
[SOURCES.md](https://github.com/MaxwellLee/physics-lab/blob/b820546ec256c40a8a5adc2123805cfcf02c4338/assets/textures/SOURCES.md)
documents JPEG recompression at the original dimensions. It is **not claimed
to be byte-identical** to NASA's original. No code from that repository was
copied. Canonical and fixed mirror URLs are recorded alongside the image in
`moon_albedo_2k.provenance.json`.

## Nomenclature, translations, ephemerides, and elevation

- `moonlabeler/data/catalog.json` contains factual terrain-name catalogue fields from [USGS / IAU Planetary Nomenclature](https://planetarynames.wr.usgs.gov/GIS_Downloads).
- `moonlabeler/data/lunar_chinese_names.json` preserves the 2026-10-16 `lunar_nomenclature(1).json` snapshot supplied by 樊仕达 (10deg). Its 10,431 records contain 9,040 Chinese captions (9,031 labelled [LPND](https://lpnd.bao.ac.cn/#/search?is=1), plus 9 separately sourced additions) and 1,391 English placeholders. Original wording, source fields, coordinates, classifications and notes are preserved. The companion provenance file distinguishes actual Chinese coverage from the supplied `named` and `coverage_percent` metadata. Source attribution follows the supplied file; individual upstream records were not independently re-fetched. Some rows retain earlier NADC links as historical references, not sources for the LPND wording.
- Supplemental records and classification attributed to [Virtual Moon Atlas](https://www.ap-i.net/avl/en/start) are retained in that supplied snapshot as reference data. They do not replace or extend the active USGS/IAU registration catalogue or the separate landing-site layer. No VMA software code is incorporated.
- `moonlabeler/data/chinese_names.json` retains the earlier [National Astronomical Data Center terminology service](https://nadc.china-vo.org/astrodict/) snapshot for search aliases and missing-entry fallback. LPND wording takes precedence when present. Compact satellite labels are formatting choices; parent-derived translations are flagged separately.
- `moonlabeler/data/landing_sites.json` contains factual Apollo descent-stage and Chang’e lander positions from [NASA NSSDCA’s lunar spacecraft table](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_artifact_impacts.html), credited to NSSDCA and LROC. Coordinates are DE421 mean Earth / polar axis, north/east positive; west longitudes are stored negative. Source updated 2025-08-13, checked 2026-10-12. No source code is imported.
- JPL DE421 ephemerides and LOLA elevation products are downloaded separately at runtime and cached locally. They are not included in this source repository.
- `examples/nasa-galileo.jpg` is sourced from [NASA Galileo PIA00405](https://science.nasa.gov/photojournal/earths-moon/). It supports transformed-image registration tests, not a general recognition-rate claim.
- The bundled `examples/synthetic-moon.png` and its demo engineering files are explicitly generated examples. Third-party photographers' local test images and derived exports are excluded from publication.

Data origin and credit remain separate from the GPL licensing of application code. NASA names and credits do not imply endorsement.

## Runtime dependencies

Most dependencies are installed separately. OpenCV is the exception: the application wheel contains its private minimal native build, with upstream notices. Other licenses accompany the dependency distributions:

The standalone Windows ZIP and macOS App also bundle their Python runtime and runtime dependencies. The macOS App preserves their distribution metadata and license directories in `Contents/Resources`, with CPython's `LICENSE.txt` under `licenses/python`. Its Qt 6.12 frameworks come from the official Qt SDK; the required PySide/Shiboken bindings are rebuilt locally from [Qt for Python v6.12.0, commit f50facb83fc3dc5f3240c854668c7a6dd93871b2](https://github.com/pyside/pyside-setup/tree/f50facb83fc3dc5f3240c854668c7a6dd93871b2) for macOS 14.4 ARM64. Build instructions and the compatibility scope are recorded in [the macOS App guide](docs/macos-app.md). Qt source is available from [Qt's 6.12.0 source archive](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/).

- Qt / PySide6 — [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html).
- NumPy — [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt).
- Pillow — [Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE).
- imagecodecs (high-bit-depth RGB TIFF decoding) — [BSD-3-Clause license and bundled-library notices](https://github.com/cgohlke/imagecodecs/blob/v2026.10.10/LICENSE). Only its TIFF decoder is used; its wheel retains the upstream native-library notices.
- OpenCV 4.14.0 / opencv_contrib — compiled from pinned source into the private `_moonlabeler_opencv` extension, using array-processing modules and an EdgeDrawing-only contrib subset. [Apache-2.0 license](https://github.com/opencv/opencv/blob/4.14.0/LICENSE). Original source headers and algorithm bodies are preserved; a small generated header/CMake module selects EdgeDrawing without the other contrib dependencies. The wheel includes OpenCV/contrib, BSD, SoftFloat/fdlibm, KAZE/AKAZE, MSCR and zlib notices next to the native binary. No upstream opencv-python wheel is bundled.
- Skyfield — [Skyfield license](https://github.com/skyfielders/python-skyfield/blob/master/LICENSE).
- PyShp — [PyShp license](https://github.com/GeospatialPython/pyshp/blob/master/LICENSE.TXT).
- Astropy (optional FITS support) — [Astropy license](https://github.com/astropy/astropy/blob/main/LICENSE.rst).
- MLX / MLX Metal (optional Apple silicon GPU acceleration) — Copyright © 2023 Apple Inc., [MIT license](https://github.com/ml-explore/mlx/blob/main/LICENSE). The terrain kernel is MoonLabeler code; MLX supplies Metal compilation and execution.

- wgpu-py (optional cross-platform GPU execution) — [BSD-2-Clause license](https://github.com/pygfx/wgpu-py/blob/main/LICENSE), Copyright (c) 2019–2023 Almar Klein, Korijn van Golen. Its native backend [wgpu-native](https://github.com/gfx-rs/wgpu-native) retains its own bundled MIT / Apache-2.0 notices. The WGSL terrain kernel is MoonLabeler code.

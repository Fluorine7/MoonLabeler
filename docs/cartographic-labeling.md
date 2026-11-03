# 月面线状地形的曲线标注：资料与建议

检索日期：2026-11-03。范围：QGIS 3.44/PAL、MapLibre GL JS、ArcGIS Pro Maplex 的官方文档和源码；文字整形接口补充采用 Qt 官方文档。以下将已核实行为与本项目建议分开。源码链接固定到检索时的提交；建议部分为本项目的推导，不是各引擎的统一规范。

## 已核实的做法

**1. 文字基线可以概化，地形几何不必改变。** Maplex 的 River placement 明确会概化河流急弯，再沿较平滑的线排字，并允许文字跨越不止一个弯。公开文档没有给出其具体平滑算法。QGIS 的标注 Geometry Generator 可独立生成标注几何，官方例子直接用 `smooth($geometry, …)` 为河流标注创造空间；这不等于所有 PAL 曲线标注都会自动平滑。[Maplex River placement](https://doc.esri.com/en/arcgis-pro/latest/help/mapping/text/label-using-the-river-placement-style-for-line-features.html)、[QGIS Geometry Generator](https://docs.qgis.org/3.44/en/docs/user_manual/style_library/label_settings.html#geometry-generator)

**2. 应选一段适合排字的路径，而非强制覆盖整条线。** QGIS PAL 沿线尝试多个起点，也可构造线上、上方、下方偏移路径；普通候选先通过长度、角度、允许区域等条件，再按平均相邻文字转角、偏离首选锚点的距离及位置偏好增加代价。它同时保留候选供后续冲突处理，不能把某个局部最低代价当作完整排版算法。[PAL 候选生成及代价](https://github.com/qgis/QGIS/blob/f858abd610beb7413f458e2b5206cee8d2e2d6cb/src/core/pal/feature.cpp#L1494-L1790)

MapLibre 沿线取候选锚点，并检查文字是否能完整落在线内；`checkMaxAngle` 累加一个与字形大小有关的滑动窗口中的**绝对转角**，超限便拒绝该候选。这能发现局部来回折线，不能仅用首尾方向差代替；该检查函数也没有修改或平滑输入线。[候选锚点](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/get_anchors.ts#L67-L164)、[角度窗口检查](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/check_max_angle.ts)

**3. 曲线上的基本单位是字形或文字簇，不是必须保持笔直的整个英文词。** QGIS 按 grapheme 切分和测宽，为每个 grapheme 产生位置与角度；MapLibre 保存 positioned glyph/grapheme，再逐个把横向偏移映射到投影后的路径。两者都不能据此概括为“英文整词保持刚性”。[QGIS 文字度量](https://github.com/qgis/QGIS/blob/f858abd610beb7413f458e2b5206cee8d2e2d6cb/src/core/labeling/qgstextlabelfeature.cpp)、[QGIS 曲线文字放置](https://github.com/qgis/QGIS/blob/f858abd610beb7413f458e2b5206cee8d2e2d6cb/src/core/textrenderer/qgstextrendererutils.cpp#L194-L381)、[MapLibre 逐字形沿线投影](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/projection.ts#L469-L552)

**但“先排字”并不自动等于保留完整词的 kerning/连字。** 上述 QGIS 实现逐 grapheme 测宽；MapLibre 的普通排字按 `metrics.advance + spacing` 推进。它们不是本项目必须照抄的完整文字整形示范。Qt 明确说明 kerning 开启时单字宽度不能简单相加，现代字体完整整形应使用 `QTextLayout`；`glyphRuns()` 可取实际字形及位置，连字也可能对应多个原始字符。[MapLibre advance 累加](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/shaping.ts#L617-L650)、[Qt kerning](https://doc.qt.io/qt-6/qfont.html#setKerning)、[Qt 完整整形](https://doc.qt.io/qt-6/qrawfont.html#advancesForGlyphIndexes)、[Qt glyph runs 与连字](https://doc.qt.io/qt-6/qglyphrun.html)

**4. 需要区别内弯、外弯及整体正向。** QGIS 对相邻 grapheme 的有符号转角分别施加 concave/convex 限制，失败则丢弃放置；还会统计倒置文字并尝试反向放置。MapLibre 也在投影后检查首尾字形决定翻转。内弯更易挤字是我们需要检查的几何问题，不能仅有一项整句旋转角限制。[QGIS 转角与翻转](https://github.com/qgis/QGIS/blob/f858abd610beb7413f458e2b5206cee8d2e2d6cb/src/core/textrenderer/qgstextrendererutils.cpp#L282-L378)、[MapLibre 翻转](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/projection.ts#L430-L508)

MapLibre 样式规范的 `text-max-angle` 默认值为 45°，它是该引擎的参数默认值，**不是适合月面中英双语的美学标准**；PAL 的代价权重同理。[MapLibre text-max-angle](https://maplibre.org/maplibre-style-spec/layers/#text-max-angle)

**5. 双行曲排存在先例，但双语层级没有统一答案。** Maplex 支持曲线标注堆叠，最多两行，并有分隔位置与对齐选项。该文档并未规定“中文主行、英文小字副行”，也未证明英文应按整个词刚性旋转。这些应明确作为本项目的版式选择。[Maplex Stack labels](https://doc.esri.com/en/arcgis-pro/latest/help/mapping/text/stack-labels.html)

**6. 排得下与读得正都依赖最终显示空间。** MapLibre 把路径投影到 label plane 后沿线放置字形，并在当前相机位置检查文字是否放得下；这意味着不能仅在经纬度空间决定弯曲质量。月面靠边缘投影压缩后尤其需要重新评价。[MapLibre 坐标空间与投影](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/projection.ts#L41-L94)、[当前视角的首尾放置检查](https://github.com/maplibre/maplibre-gl-js/blob/2b68611a4e2d4f7f076f6c6ebf758e2d53f91471/src/symbol/projection.ts#L342-L386)

## 对 MoonLabeler 的实现建议（推导与设计选择）

核心流程建议为：**保留原始地形 → 生成标注专用基线候选 → 选择可读的局部弧段 → 完整整形 → 按字形簇沿线放置 → 碰撞与正向检查 → 降级。** 这是结合上面证据提出的方案，下面的优化项与取舍不是某款引擎的公开默认算法。

1. **替换“全线强二次拟合”的单一解。** 在照片/排版坐标中按弧长重采样，产生几条不同平滑强度、不同起点的局部基线；用带偏离约束的平滑样条或现有局部平滑抑制小锯齿，保留地形的大弯。约束基线与原路径的距离，以免大幅抄近路。全局二次拟合只有极少自由度，容易抹掉本来需要保留的多个弯；提高其强度无法同时解决选段与字形间距。

2. **以实际排版长度选段。** 从完整整形取得中文、英文各自行宽，在路径上尝试多个长度足够的区间及少量法向偏移。先拒绝急折、明显倒字、缺段、自交及字形重叠；再综合惩罚局部累计转角、转角变化的抖动、偏离地形与首选锚点、其他标签冲突。对弯曲本身不作一刀切惩罚，否则最优解会再次趋向直线。平滑尺度、偏离容限与检测窗口使用字号/字高等排版尺度，避免依赖源路径采样密度。

3. **完整整形，局部旋转。** 对每行完整 `QTextLayout` 一次，缓存字形、字体、位置和文字簇映射；将整形后的横坐标映射为基线弧长，按局部方向放置，保留簇内相对位置与原有字距。组合附加符号和连字不能从中拆开。当前“整词绘制”可保留为兼容降级，但长词会呈现直段拼接，不能作为最终曲排原则。

4. **双语作为一个候选整体判断。** 可继续中文上、英文小字下，但两行应共享候选区间和正向，保留各自自然字宽及字号。不要把短中文强拉伸到长英文宽度。两条法向偏移基线应各自按弧长排字：内外偏移后的长度不同，直接复制同一组参数位置会产生挤压/松散。检查两行间及各自行内的字形/描边边界；急弯偏移线形成尖角或自交就换候选。

5. **失败有可预测的退路。** 先换弧段、再尝试允许偏离范围内的更平缓基线，仍不适合就改为局部切向直排或普通双语标注加引线；保持全名。不要通过无上限缩字、强拉字距或把每个字分别翻正来硬塞。Maplex 的替代表达、缩写、截断是显式策略，不构成本项目自动删改地名的理由。[Maplex fitting 策略](https://pro.arcgis.com/en/pro-app/3.4/help/mapping/text/abbreviate-and-truncate-labels.htm)

6. **按项目的坐标约定缓存与导出。** 若文字和照片随画布一起等比缩放，普通查看缩放可复用排版；若字号恒定于屏幕，或投影、视图旋转、导出排版尺度改变，则重评可用弧段与重叠。预览、PNG、SVG 共用同一份字形放置结果，避免各自重排。以长英文词、组合音标、中英双行、S 形路径、内弯挤字和月缘压缩作有区分力的视觉样例；不把某个固定角度当作验收本身。

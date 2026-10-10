# 环形山识别与星历候选项目

2026-10-10 根据下列仓库的固定源码版本核对 README、许可和与任务有关的关键源码，并非逐文件审阅全部仓库。Lunar Crater Detector 的 OpenCV 检测路径已改编接入，作为疑似中心辅助。0.4.0 另使用 OpenCV EDCircles 和独立实现的目录三坑搜索接通自动名称识别；未直接集成其余三个仓库的代码或深度学习模型。OpenCV 依赖改为 contrib 版本。

## 检测与名称识别

检测器输出图片中的像素中心、大小或椭圆，不等于确定该环形山的官方名称。名称识别还需要将多个检测结果与月面目录匹配，再验证其他地形是否同时落在正确位置。高倍局部照片中的阴影、山脊和不完整坑缘会影响检测。

| 项目及版本 | 已核实的实现 | 对 MoonLabeler 的适用判断 |
| --- | --- | --- |
| [chase-kusterer/lunar_stack](https://github.com/chase-kusterer/lunar_stack/tree/96d22ac21320582673af564aecd9392aa1196a53) | 面向地面拍摄的月球视频对齐、叠加。SAM 分割亮面、RANSAC 圆拟合调整尺度、LoG 寻找斑点、匹配中心位置并修正旋转。参考地图限于八个月海中的 295 个环形山，主动避开月缘与明暗交界。 | 值得研究参考地图和检测结果匹配；目前流程依赖月盘拟合，不能直接作为无月缘局部照片的通用定位器。视频叠加暂非标注工具的主要需求。 |
| [rammaruboina-rgb/lunar-crater-detector](https://github.com/rammaruboina-rgb/lunar-crater-detector/tree/0babc2a6fb3d02cfbf58aa9bafe9f44edf8dc3dd) | CLAHE、Canny、形态学、Hough 圆/椭圆及轮廓拟合，输出像素椭圆参数。没有月面地名目录匹配。实际入口是 `process_image` 等函数；README 中的 `CraterDetector` 类示例与此版本代码不符。 | 最适合轻量的“疑似坑中心”辅助原型，用户确认后用于参考点。不能直接自动填地名。需移除固定像素筛选并适配高倍视野；原依赖约束 NumPy <2，与当前环境不能直接合并。 |
| [wdoppenberg/crater-detection](https://github.com/wdoppenberg/crater-detection/tree/1365817fb62247378bb04085d41a2216a666ac25) | 月球轨道地形导航，Ellipse R-CNN 检测；三座近似共面环形山的投影不变量用于目录识别。训练示例为模拟单目轨道相机影像；训练数据生成使用 SurRender。 | 三坑图案识别与本项目的局部名称识别相关，值得进一步研究。整个模型和轨道导航管线较重，需要验证地面实拍阴影、近似共面条件和坑缘检测；不能以原仓库训练结果推断望远镜照片准确率。 |
| [cosinekitty/astronomy](https://github.com/cosinekitty/astronomy/tree/865d3da7d8112bbc7911238052c6af4aaf877181) | Astronomy Engine，无外部运行依赖；提供地心月球位置、天平动、观测者向量及 IAU 2015 自转轴模型。项目给出的总体位置精度目标约为一角分，这不是月面投影误差或天平动专项误差保证。 | 可研究为首次启动无星历下载的轻量备选。当前 MoonLabeler 已使用 Skyfield + JPL DE421 位置/姿态及 MOON_ME_DE421 参考系；替换前必须核对地面观测视差、经度符号和 LOLA 坐标系，并在多个日期、区域与当前实现比较。 |

上述四个仓库自身的 LICENSE 均为 MIT。若以后采用代码，需要保留各作者的版权和许可文本；模型、训练数据和第三方软件仍需分别核对。

## 实施次序

当前已完成多点校准、LOLA 局部模拟、标签布局、疑似坑辅助和自动目录识别入口。三张用户实拍已通过自动按钮到导出流程：阿里斯塔克斯 / 蛇谷七坑匹配、低坑缘对比整月盘 LROC 纹理配准、Clavius 区域七坑匹配。Clavius 案例暴露了仅用独立命名坑生成三角形、四独立命名坑门槛、局部邻域挤掉大坑关系和小碎片稀释候选共识的问题；现增加多尺度卫星坑搜索及至少七个大候选的验证。图案搜索仍是地面视角的启发式相似变换，不等同于 wdoppenberg 的完整椭圆不变量。lunar_stack 的图像参考匹配思路支持增加纹理路线，但没有复制其视频模型代码；内置纹理来自 NASA LROC 全球图，运行不需要访问 SVS。Astronomy Engine 仍为备用研究方向，当前继续使用 JPL DE421。三张成功照片不能给出通用准确率；同一照片的旋转、裁剪和镜像回归只能证明变换处理。

## Matt Pocock skills

也核对了 [mattpocock/skills](https://github.com/mattpocock/skills/tree/49dd158d1076134a641b33efb035946536778336) 中的 `tdd`、`diagnosing-bugs`、`code-review`、`improve-codebase-architecture` 和 `grill-with-docs`。按用户授权，已安装 `tdd` 与 `diagnosing-bugs` 到本机 Codex skills 目录；本轮自动识别修复使用了 `diagnosing-bugs`。其余 skills 未安装。这些 skills 提供开发与排错流程，不提供月面识别算法。

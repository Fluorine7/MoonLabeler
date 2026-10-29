# MoonLabeler 工程与配准格式

`.moonlabel` 是 UTF-8 JSON。识别或手动配准后点击“保存工程”，即可得到文件；下次用“打开工程”恢复，无须重新识别。交给其他软件时，需要同时提供原照片。

可先读取仓库中的[合成示例工程](../examples/demo.moonlabel)。它是新增元数据之前的 v2 文件，也在兼容范围内。

本文是 MoonLabeler 的读取约定，可用于 [Tsukikage](https://github.com/10deg/tsukikage) 等月面地图。Tsukikage 的照片导入由对方实现；本文不表示其当前版本已支持导入。

## 版本与兼容

- 根节点的 `format` 必须为 `"MoonLabeler"`，`version` 必须为整数 `2`，不是应用版本号。
- 本次新增 `image_size`、`coordinate_system`，不改变已有字段或格式版本。旧版 MoonLabeler 会忽略新字段；新版本继续读取旧工程。
- 读取者应忽略不使用的字段；遇到未知格式版本或坐标约定应拒绝套用旧公式。
- 旧工程没有 `image_size` 或值为 `null` 时，从原照片读取尺寸；没有 `coordinate_system` 时，使用下述约定。

## 识别排除区域

可选的 `recognition_mask` 存储 `enabled` 布尔值及按顺序应用的 `operations`。缺少该字段的旧工程没有手动排除区域。操作坐标与 `image_size` 一致，均为原图像素：

- `{"kind": "polygon", "points": [[x, y], ...]}`：排除闭合多边形，至少三个顶点；重叠区域取并集。
- `{"kind": "paint", "points": [[x, y], ...], "radius": r}`：圆头画笔沿折线涂抹排除区域，半径为原图像素；单个点表示圆形笔触，后续笔触与已有区域取并集。
- `{"kind": "erase", "points": [[x, y], ...], "radius": r}`：沿折线擦除已有排除区域，圆头半径为原图像素；单个点表示圆形橡皮擦。

后面的操作覆盖前面的操作，最多 128 次操作、每次 2048 个点、共 16384 个点。该字段仅控制识别采样，不改变已保存的配准、标签或原照片有效范围。地图贴图及标注导出忽略它；界面显示开关与蒙版启用状态独立。

## 标注文字不透明度

可选的 `style.label_opacity` 为 0～1 的数值，默认 1（完全不透明）。普通与艺术样式共用此值，只控制地名、着陆点文字及其描边，不改变引线、坑缘、照片或地图图层。旧工程缺少字段时保持原来的外观。预览、PNG 和 SVG 均应用此值；滑块实时更新，不重新识别或排版。

## 地图需要的字段

| 字段 | 含义 |
| --- | --- |
| `image_path` | 照片路径，相对工程文件所在目录。新文件使用 `/`；旧 Windows 文件可能使用 `\`。跨盘保存可能是绝对路径，转移到其他电脑后可让用户重选照片 |
| `image_size` | `[宽, 高]`，单位像素，已经应用 EXIF 方向或 FITS 上下翻转。不是缩放后的预览尺寸 |
| `geometry` | 已配准视角的 `observer`、`right`、`north`、`sun` 四个三维单位向量，以及 `distance_km`、`utc` |
| `matrix` | 2×3 仿射矩阵，将归一化投影坐标变为照片像素；已经包含旋转、缩放、平移和可能的镜像 |
| `automatic_recognition.lens_distortion` | 可选的径向畸变：`center: [cx, cy]`、`scale`（像素）、`k`（无量纲，0～0.6）。缺失或 `null` 表示无畸变 |
| `projection_surface` | `"sphere"` 使用参考球面，`"terrain"` 使用地形高度。旧字段缺失时，`automatic_recognition.refinement.relief_aware == true` 表示 terrain，否则 sphere |
| `utc`、`observer` | 工程填写的时间及地球上拍摄地点。时间可能由用户估计，不代表从照片测出的时间 |

`geometry` 或 `matrix` 为 `null` 表示尚未配准，不能贴图。地图读取不需要 `style`、`anchors`、`labels`，也不需要重新运行识别、下载星历或加载 MoonLabeler。

**使用保存的 `geometry` 和 `matrix`。** `geometry` 可能经过图像微调；不能用 `utc` 重算后替换，也不能用诊断字段 `automatic_recognition.refinement.base_geometry` 代替它。`sun` 表示几何模型中的太阳方向，不用于裁掉照片范围。

## 坐标约定

新工程的 `coordinate_system` 为：

```json
{
  "body": "Moon",
  "frame": "MOON_ME",
  "latitude_type": "planetocentric",
  "longitude_direction": "east",
  "angle_unit": "degree",
  "reference_radius_km": 1737.4,
  "projection": "finite_distance_perspective",
  "pixel_origin": "top_left",
  "pixel_axes": ["right", "down"],
  "pixel_center_offset": [0.5, 0.5]
}
```

月面坐标使用平均地球／极轴系（ME），不是地球的 WGS84，也不是月球 PA 系。北纬、东经为正；经度按 360° 周期处理。三维单位向量为 `(cos(lat) cos(lon), cos(lat) sin(lon), sin(lat))`，X 指向 0° 经度，Y 指向东经 90°，Z 指向北极。

照片坐标是显示原图的连续坐标：左上角 `(0, 0)`，向右为 X、向下为 Y，第一个像素中心为 `(0.5, 0.5)`。向以整数作为像素中心的采样器（例如 OpenCV remap）传坐标时，减去 `0.5`。不要再次根据北向旋转照片，镜像也已在矩阵中。

工程不内嵌照片；`image_path` 始终指向原照片，艺术配色和标签没有烘焙进去。读取照片时保留其 ICC 色彩管理；像素位置与艺术主题、标签显隐、地图受光阈值无关。

普通照片先应用 EXIF 方向；FITS 使用首个有效图像 HDU，将 FITS 的行方向上下翻转后显示。地图读取者需采用相同方向并核对尺寸。不要把裁剪、缩放或旋转后的照片直接配给旧工程；尺寸相同也不保证内容相同。新工程打开时会检查尺寸，但不做整文件哈希。

## 月面 → 照片

设月面单位向量为 `s`，参考半径 `R = 1737.4 km`，观测距离为 `D = geometry.distance_km`。

1. sphere 使用 `v = s`；terrain 使用 `v = (1 + h/R) s`，其中 `h` 是相对参考球面的高度，单位 km。
2. `q = R/D`，`depth = dot(v, observer)`，`denom = 1 - q*depth`。
3. 投影坐标 `u = dot(v, right)/denom`，`w = -dot(v, north)/denom`。
4. `p = matrix @ [u, w, 1]`，得到理想照片坐标。
5. 若有畸变，`d = (p-center)/scale`，实际照片坐标为 `p + k*d*dot(d,d)*scale`。

仅保留 `depth > q*dot(v,v)` 且最终坐标位于照片范围内的点。判断范围时使用畸变后的坐标。

terrain 的贴图应由读取者提供同一坐标系的 DEM 高度；不提供高度的球面贴图只能算近似，尤其是月缘和极区。上述可见性是几何视界判断，不处理山峰互相遮挡。`terrain.dem_path` 是源电脑的数据路径，不是 DEM 内容或可自动下载的地址。

## 最小读取示例

下面仅依赖 Python 标准库。`moon_to_photo` 可直接用于地图逐像素反查原照片；`photo_to_sphere` 用于估计照片位置和范围，明确以参考球面求交。示例不导入 MoonLabeler，也不读取或执行工程中的代码。

```python
import json
import math
from pathlib import Path


def read_registration(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != "MoonLabeler" or type(data.get("version")) is not int or data["version"] != 2:
        raise ValueError("Unsupported MoonLabeler format")
    if data.get("geometry") is None or data.get("matrix") is None:
        raise ValueError("Photo has not been registered")
    expected = {
        "body": "Moon", "frame": "MOON_ME", "latitude_type": "planetocentric",
        "longitude_direction": "east", "angle_unit": "degree",
        "reference_radius_km": 1737.4, "projection": "finite_distance_perspective",
        "pixel_origin": "top_left", "pixel_axes": ["right", "down"],
        "pixel_center_offset": [0.5, 0.5],
    }
    if "coordinate_system" in data and any(data["coordinate_system"].get(k) != v for k, v in expected.items()):
        raise ValueError("Unsupported coordinate system")
    return data


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def moon_to_photo(data, lat_deg, lon_deg, height_km=None):
    g, m = data["geometry"], data["matrix"]
    refinement = data.get("automatic_recognition", {}).get("refinement") or {}
    surface = data.get("projection_surface", "terrain" if refinement.get("relief_aware") is True else "sphere")
    if surface not in ("sphere", "terrain"):
        raise ValueError("Unsupported projection surface")
    if surface == "terrain" and height_km is None:
        raise ValueError("Terrain projection requires DEM height in km")
    radius = 1 + (height_km if surface == "terrain" else 0)/1737.4
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    v = [radius*math.cos(lat)*math.cos(lon), radius*math.cos(lat)*math.sin(lon), radius*math.sin(lat)]
    q, depth = 1737.4/g["distance_km"], dot(v, g["observer"])
    if depth <= q*dot(v, v):
        return None
    uv = [dot(v, g["right"])/(1-q*depth), -dot(v, g["north"])/(1-q*depth), 1]
    x, y = (dot(row, uv) for row in m)
    lens = data.get("automatic_recognition", {}).get("lens_distortion")
    if lens:
        dx, dy = (x-lens["center"][0])/lens["scale"], (y-lens["center"][1])/lens["scale"]
        factor = lens["k"]*(dx*dx+dy*dy)*lens["scale"]
        x, y = x+factor*dx, y+factor*dy
    if data.get("image_size"):
        width, height = data["image_size"]
        if not (0 <= x < width and 0 <= y < height):
            return None
    return x, y


def photo_to_sphere(data, x, y):
    if data.get("image_size"):
        width, height = data["image_size"]
        if not (0 <= x < width and 0 <= y < height):
            return None
    lens = data.get("automatic_recognition", {}).get("lens_distortion")
    if lens and lens["k"]:
        dx, dy = (x-lens["center"][0])/lens["scale"], (y-lens["center"][1])/lens["scale"]
        measured = math.hypot(dx, dy)
        r = min(measured, (measured/lens["k"])**(1/3))
        for _ in range(12):
            r -= (r+lens["k"]*r**3-measured)/(1+3*lens["k"]*r*r)
        ratio = r/measured if measured else 1
        x, y = lens["center"][0]+dx*ratio*lens["scale"], lens["center"][1]+dy*ratio*lens["scale"]
    (a, b, tx), (c, d, ty) = data["matrix"]
    det = a*d-b*c
    if abs(det) < 1e-10:
        raise ValueError("Invalid registration matrix")
    u, w = (d*(x-tx)-b*(y-ty))/det, (-c*(x-tx)+a*(y-ty))/det
    g = data["geometry"]
    distance = g["distance_km"]/1737.4
    ray = [-o+(u*right-w*north)/distance for o, right, north in zip(g["observer"], g["right"], g["north"])]
    discriminant = distance*distance-dot(ray, ray)*(distance*distance-1)
    if discriminant < 0:
        return None  # Sky outside the lunar limb.
    length = (distance*distance-1)/(distance+math.sqrt(discriminant))
    v = [distance*o+length*r for o, r in zip(g["observer"], ray)]
    return math.degrees(math.asin(max(-1, min(1, v[2])))), math.degrees(math.atan2(v[1], v[0]))
```

此示例展示格式和计算，不是完整的外部文件校验器。产品接入还应检查数值有限、矩阵为可逆 2×3、向量为正交单位基、距离大于月球半径、尺寸为正整数，限制读取文件大小；不要把无效配准当有效图层。

## 在地图上贴照片

以 Tsukikage 的等距圆柱地图为例，整幅地图宽 `W`、高 `H` 时，像素中心对应 `lon = 360*(i+0.5)/W-180`、`lat = 90-180*(j+0.5)/H`。瓦片需先加上其在整幅地图中的偏移。

逐个地图像素调用 `moon_to_photo`，有返回值时采样原照片，返回 `None` 时透明。这样自然包含镜像、旋转、部分月面和月缘裁切，不会把黑色天空拉伸到月面上；月面上的阴影仍属于照片内容。实现时可批量计算并按瓦片缓存。

整月照片常常四角全在天空中，因此不能只用照片四角求经纬度，也不能把经纬度最小／最大值当成贴图矩形。求覆盖范围时应对“可见月面且投影落在照片内”的区域取边界，并处理跨 ±180° 经线及包含极点的情况。无需依赖 PNG/SVG 中的照片区域示意图。

`labels` 只保存手工编辑，不是完整地名列表。`labels[id].position` 是文字位置，`anchors[].pixel` 是手动参考点；两者都不能当作地形经纬度。需要地名的地图可继续使用自己的目录。

## 接入检查

- 保存、关闭、重开工程，原照片、配准矩阵和手工编辑不变。
- 试整月、局部、镜像、极区及带目镜畸变的照片；球面内的像素做正反变换应回到原位置。
- 天空和背面透明，夜面不因 `sun` 或艺术图层的受光阈值而被当作“没有配准数据”。
- 读取旧工程时接受缺失的新字段；原照片找不到时由用户定位，不猜测别的文件。

实现依据：[MoonLabeler 几何](../moonlabeler/geometry.py)、[工程读写](../moonlabeler/project.py)、[畸变模型](../moonlabeler/eyepiece.py)；对接参考：[Tsukikage 地图服务](https://github.com/10deg/tsukikage/blob/ac788c5df047977e1c4262599e6625e2ab996bf4/web/map_server.py)、[ME 坐标](https://github.com/10deg/tsukikage/blob/ac788c5df047977e1c4262599e6625e2ab996bf4/src/moonlib/frames.py)。

照片地图联动建议来自樊仕达（10deg）。

English: `.moonlabel` is a UTF-8 JSON project, format version 2. Read the saved camera geometry, affine matrix and optional radial distortion; do not recompute them from the timestamp. `image_size` and `coordinate_system` are optional, additive fields. Distribute the original photo alongside the project. The Python example maps lunar coordinates to photo pixels without importing MoonLabeler. Tsukikage's importer is implemented separately.

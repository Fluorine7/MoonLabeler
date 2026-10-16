# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Public data downloads, cached locally; photographs never leave the machine."""
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
import io
import json
import mmap
import re
import ssl
import struct
import zipfile

import certifi
import cv2
import numpy as np
from PIL import Image, ImageOps

USGS_URL = "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip"
NASA_2026 = "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/"
PACKAGE_DATA = Path(__file__).parent / "data"
CHINESE = {
    "Copernicus": "哥白尼", "Tycho": "第谷", "Plato": "柏拉图", "Kepler": "开普勒",
    "Aristarchus": "阿里斯塔克斯", "Eratosthenes": "厄拉多塞", "Archimedes": "阿基米德",
    "Clavius": "克拉维斯", "Gassendi": "伽桑狄", "Ptolemaeus": "托勒密",
    "Alphonsus": "阿方索", "Arzachel": "阿尔扎赫尔", "Theophilus": "西奥菲勒斯",
    "Cyrillus": "西里尔", "Catharina": "凯瑟琳", "Posidonius": "波希多尼",
    "Langrenus": "朗格努斯", "Petavius": "佩塔维乌斯", "Schickard": "席卡德",
    "Mare Imbrium": "雨海", "Mare Serenitatis": "澄海", "Mare Tranquillitatis": "静海",
    "Mare Crisium": "危海", "Mare Fecunditatis": "丰富海", "Mare Nectaris": "酒海",
    "Mare Nubium": "云海", "Mare Humorum": "湿海", "Oceanus Procellarum": "风暴洋",
    "Sinus Iridum": "虹湾", "Montes Apenninus": "亚平宁山脉", "Vallis Alpes": "阿尔卑斯月谷",
}
COMMON_FEATURES = frozenset(CHINESE)


@lru_cache(maxsize=2)
def _translation_tables(data_directory):
    legacy = json.loads((data_directory/"chinese_names.json").read_text(encoding="utf-8"))
    primary = json.loads((data_directory/"lunar_chinese_names.json").read_text(encoding="utf-8"))
    return primary, legacy


def _compact_chinese(name, entry):
    text = entry["zh"]
    satellite = re.fullmatch(r"(.+) ([A-Z])", name)
    if satellite:
        # Only strip structural crater notation, never retranslate the name.
        parts = re.fullmatch(r"(.+?)(?:坑)?\s*([A-Z])(?:坑)?", text.replace("[", "").replace("]", ""))
        if parts and parts[2] == satellite[2]:
            return parts[1]+" "+parts[2]
    return text


def _chinese_entry(translations, name):
    """Mixed catalogues use English captions for entries still awaiting translation."""
    entry = translations.get(name)
    return entry if entry and re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", entry.get("zh", "")) else None


def translate_catalog(features):
    """Prefer supplied LPND names; retain legacy translations as search aliases."""
    primary, legacy = _translation_tables(PACKAGE_DATA)
    translations, old_translations = primary["names"], legacy["names"]
    lpnd_url = next((url for url in primary["source_urls"] if urlparse(url).hostname == "lpnd.bao.ac.cn"),
                    "https://lpnd.bao.ac.cn/#/search?is=1")
    for feature in features:
        name = feature["name"]
        satellite = re.fullmatch(r"(.+) ([A-Z])", name)
        aliases = set(feature.get("name_zh_aliases", []))
        aliases.update(filter(None, (feature.get("name_zh"), CHINESE.get(name))))
        previous = _chinese_entry(old_translations, name)
        old_parent = _chinese_entry(old_translations, satellite[1]) if satellite else None
        if previous:
            aliases.add(previous["zh"])
        elif old_parent:
            aliases.add(old_parent["zh"]+" "+satellite[2])
        entry = _chinese_entry(translations, name)
        authority = primary
        derived = False
        if entry is None and satellite:
            entry = _chinese_entry(translations, satellite[1])
            derived = entry is not None
        if entry is None:
            authority = legacy
            entry = previous or old_parent
            derived = previous is None and old_parent is not None
        if entry:
            translated = _compact_chinese(satellite[1] if derived else name, entry)
            feature["name_zh"] = translated+" "+satellite[2] if derived else translated
            source = entry.get("source", authority["source"])
            # Some supplied LPND rows retain NADC URLs from the older table.
            # Those are historical references, not evidence for the new wording.
            feature["name_zh_source"] = (lpnd_url if source.startswith("LPND")
                                         else entry.get("url", ""))
            feature["name_zh_source_name"] = source
            feature.pop("name_zh_derived", None)
            if derived:
                feature["name_zh_derived"] = True
                feature.pop("name_zh_term", None)
            else:
                feature["name_zh_term"] = entry.get("term_zh", entry["zh"])
                aliases.update((entry["zh"], feature["name_zh_term"]))
        elif name in CHINESE:
            feature["name_zh"] = CHINESE[name]
        aliases.discard(feature.get("name_zh", ""))
        if aliases:
            feature["name_zh_aliases"] = sorted(aliases)
    return features


def feature_search_text(feature):
    return " ".join([feature["name"], feature.get("name_zh", ""), *feature.get("name_zh_aliases", [])])


class DataDownloadError(ValueError):
    """A data download failed without changing the current image/registration."""


def download_error_message(url, error):
    host = urlparse(url).hostname or "数据服务"
    reason = str(getattr(error, "reason", error)).lower()
    if isinstance(error, HTTPError):
        detail = f"HTTP {error.code}"
    elif "handshake" in reason and ("timed out" in reason or "timeout" in reason):
        detail = "HTTPS 握手超时"
    elif "certificate" in reason:
        detail = "HTTPS 证书验证失败"
    elif "timed out" in reason or "timeout" in reason:
        detail = "连接或读取超时"
    else:
        detail = "连接未完成"
    message = f"无法下载 {host} 的参考数据：{detail}。"
    if host == "svs.gsfc.nasa.gov":
        message += ("\n\n其他网站能打开，并不表示这条 NASA HTTPS 连接已连通。"
                    "可检查代理中此域名的线路，或在浏览器打开 https://svs.gsfc.nasa.gov/5587/。"
                    "\n\n当前照片和已有配准仍保留。局部月面可直接切到“地形点”，"
                    "选择至少三处已知环形山中心配准，无需下载 NASA 影像。")
    return message


def download(url, destination, force=False):
    destination = Path(destination)
    if destination.exists() and not force:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        request = Request(url, headers={"User-Agent": "MoonLabeler/0.3 (lunar photo annotation)"})
        with urlopen(request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())) as source:
            try:
                expected = int(source.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                expected = None
            if expected is not None and expected < 0:
                expected = None
            received = 0
            with temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                    received += len(chunk)
            if expected is not None and received != expected:
                host = urlparse(url).hostname or "数据服务"
                raise DataDownloadError(f"无法下载 {host} 的参考数据：数据不完整"
                                        f"（收到 {received} 字节，应为 {expected} 字节）。请重试。")
        temporary.replace(destination)
    except (URLError, TimeoutError, ssl.SSLError) as exc:
        raise DataDownloadError(download_error_message(url, exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def refresh_catalog(cache, force=True):
    import shapefile

    archive = download(USGS_URL, Path(cache) / "moon-nomenclature.zip", force=force)
    with zipfile.ZipFile(archive) as z:
        filename = next(n for n in z.namelist() if n.lower().endswith(".dbf"))
        reader = shapefile.Reader(dbf=io.BytesIO(z.read(filename)), encoding="utf-8")
        records = [r.as_dict() for r in reader.iterRecords()]
    features = []
    for record in records:
        if record["approval"] != "Adopted by IAU":
            continue
        # Field names are checked against the actual USGS export.
        name = str(record["name"])
        features.append({"id": record["link"].rstrip("/").rsplit("/", 1)[-1], "name": name,
                         "name_zh": CHINESE.get(name, ""),
                         "lat": float(record["center_lat"]),
                         "lon": (float(record["center_lon"]) + 180) % 360 - 180,
                         "diameter": float(record["diameter"] or 0),
                         "kind": str(record["type"]),
                         "approved": str(record.get("approval", ""))})
    destination = Path(cache) / "catalog.json"
    write_json(destination, {"source": USGS_URL, "downloaded_utc": datetime.now(timezone.utc).isoformat(),
                             "features": features})
    return translate_catalog(features)


def load_catalog(cache):
    for path in (Path(cache) / "catalog.json", PACKAGE_DATA / "catalog.json"):
        if path.exists():
            return translate_catalog(json.loads(path.read_text(encoding="utf-8"))["features"])
    raise ValueError("缺少地名目录，请先下载 USGS 地名。")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _read_high_depth_tiff(path, orientation):
    if orientation == 1:
        return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    # The TIFF decoder applies orientation internally even with UNCHANGED;
    # rotating non-square 16-bit data also fails in some OpenCV versions.
    # Neutralize that tag in a private mapping, never in the original file.
    with path.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_COPY) as encoded:
        order = "<" if encoded[:2] == b"II" else ">"
        version = struct.unpack_from(order+"H", encoded, 2)[0]
        if version == 42:
            offset = struct.unpack_from(order+"I", encoded, 4)[0]
            count = struct.unpack_from(order+"H", encoded, offset)[0]
            start, entry_size, count_type, value_offset = offset+2, 12, "I", 8
        elif version == 43:
            offset = struct.unpack_from(order+"Q", encoded, 8)[0]
            count = struct.unpack_from(order+"Q", encoded, offset)[0]
            start, entry_size, count_type, value_offset = offset+8, 20, "Q", 12
        else:
            raise ValueError("无法读取 TIFF 方向信息。")
        for entry in range(start, start+entry_size*count, entry_size):
            tag, kind = struct.unpack_from(order+"HH", encoded, entry)
            if tag == 274 and kind == 3 and struct.unpack_from(order+count_type, encoded, entry+4)[0] == 1:
                struct.pack_into(order+"H", encoded, entry+value_offset, 1)
                break
        else:
            raise ValueError("无法读取 TIFF 方向信息。")
        pixels = np.frombuffer(encoded, np.uint8)
        try:
            return cv2.imdecode(pixels, cv2.IMREAD_UNCHANGED)
        finally:
            del pixels


def read_image(path):
    path = Path(path)
    orientation = 1
    if path.suffix.lower() in (".fits", ".fit", ".fts"):
        try:
            from astropy.io import fits
        except ImportError as exc:
            raise ValueError("FITS 需要 Astropy：在虚拟环境运行 pip install astropy。") from exc
        with fits.open(path) as hdus:
            array = next((np.asarray(hdu.data).copy() for hdu in hdus
                          if hdu.data is not None and hdu.data.ndim >= 2), None)
        if array is None:
            raise ValueError("FITS 没有可显示的图像。")
        array = np.squeeze(array)
        if array.ndim == 3 and array.shape[0] in (3, 4):
            array = np.moveaxis(array, 0, -1)
        array = np.flipud(array)
    else:
        with Image.open(path) as raw:
            bits = raw.tag_v2.get(258, (8,)) if raw.format == "TIFF" else (8,)
            bits = (bits,) if isinstance(bits, int) else bits
            if raw.mode == "RGB" and max(bits) > 8:
                # Pillow exposes RGB TIFF as 8-bit even when the source is 16-bit.
                # Decode original samples before the common display stretch.
                orientation = raw.getexif().get(274, 1)
                array = _read_high_depth_tiff(path, orientation)
                if array is None or array.ndim != 3 or array.shape[2] != 3 or array.dtype.itemsize < 2:
                    raise ValueError("无法读取高位深 RGB TIFF 的原始像素。")
                array = cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
            else:
                raw = ImageOps.exif_transpose(raw)
                if raw.mode in ("I", "F", "I;16", "I;16B", "I;16L"):
                    array = np.asarray(raw).copy()
                else:
                    if "A" in raw.getbands() or "transparency" in raw.info:
                        # Hidden RGB values must not become bright lunar foreground.
                        rgba = raw.convert("RGBA")
                        raw = Image.alpha_composite(Image.new("RGBA", raw.size, (0, 0, 0, 255)), rgba)
                    return np.asarray(raw.convert("RGB")).copy()
    if array.ndim not in (2, 3) or (array.ndim == 3 and array.shape[-1] not in (3, 4)):
        raise ValueError("仅支持二维灰度或 RGB 图像；请先从数据立方体中提取图像。")
    finite = array[np.isfinite(array)]
    if not finite.size:
        raise ValueError("图像没有有效的像素。")
    low, high = np.percentile(finite, [0.2, 99.8])
    array = np.nan_to_num(array.astype(float), nan=low, posinf=high, neginf=low)
    array = np.uint8(np.clip((array-low) / max(high-low, 1e-9), 0, 1) * 255)
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    if orientation != 1:
        display = Image.fromarray(array)
        display.getexif()[274] = orientation
        array = np.asarray(ImageOps.exif_transpose(display)).copy()
    return np.ascontiguousarray(array[:, :, :3])


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href")


def nasa_reference(utc, cache):
    """Fetch the 2026 hourly geocentric reference from the official frame set."""
    from .geometry import geometry_from_nasa

    utc = utc.astimezone(timezone.utc)
    if utc.year != 2026:
        raise ValueError("当前 NASA 自动参考支持 2026 年；其他年份可选择已校准的本地参考工程。")
    hour = utc.replace(minute=0, second=0, microsecond=0)
    index = int((hour - datetime(2026, 1, 1, tzinfo=timezone.utc)).total_seconds() // 3600)
    root = Path(cache) / "nasa-2026"
    data = json.loads(download(NASA_2026 + "mooninfo_2026.json", root / "mooninfo.json").read_text())
    record = data[index]
    directory = NASA_2026 + "frames/3840x2160_16x9_30p/plain/"
    links = Links()
    listing = download(directory, root / "frames.html").read_text()
    links.feed(listing)
    sample = next((u for u in links.hrefs if re.search(r"moon\.\d+\.(tif|png|jpg)$", u)), None)
    if sample is None:
        raise ValueError("NASA 参考影像目录格式已改变。请使用本地参考工程。")
    frame_url = re.sub(r"moon\.\d+", f"moon.{index+1:04d}", urljoin(directory, sample))
    image_path = download(frame_url, root / Path(frame_url).name)
    geometry = geometry_from_nasa(record, hour)
    with Image.open(image_path) as raw:
        rgba = np.asarray(raw.convert("RGBA"))
    cx, cy, radius = detect_reference_disk(rgba)
    # Perspective projection has a slightly enlarged apparent limb.
    apparent_radius = 1 / np.sqrt(1 - (1737.4 / geometry.distance_km)**2)
    scale = radius / apparent_radius
    matrix = np.array([[scale, 0., cx], [0., scale, cy]])
    return read_image(image_path), geometry, matrix, image_path


def detect_reference_disk(rgba):
    """Find the outline of NASA's transparent full disk; reject unsafe guesses."""
    alpha = rgba[:, :, 3]
    if np.min(alpha) == np.max(alpha):
        raise ValueError("参考图没有透明月盘边界，无法可靠确定尺度。请使用已校准参考工程。")
    mask = np.uint8(alpha > 128)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv2.contourArea)
    pts = contour[:, 0, :].astype(float)
    x, y = pts.T
    cx, cy, c = np.linalg.lstsq(np.column_stack((2*x, 2*y, np.ones(len(x)))), x*x+y*y, rcond=None)[0]
    radius = float(np.sqrt(c + cx*cx + cy*cy))
    deviation = np.std(np.linalg.norm(pts-[cx,cy], axis=1))
    if radius < 50 or deviation > 1.5 or cv2.contourArea(contour) < 0.9 * np.pi * radius**2:
        raise ValueError("参考图月盘轮廓不完整。请使用已校准参考工程。")
    return float(cx), float(cy), radius

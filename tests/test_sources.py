# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from urllib.error import URLError
from io import BytesIO
import ast
from pathlib import Path
import re
import struct

import cv2
import imagecodecs
import numpy as np
from PIL import Image

import pytest

from moonlabeler.sources import DataDownloadError, download, read_image


def test_nasa_tls_timeout_has_manual_fallback_and_keeps_cached_data(tmp_path, monkeypatch):
    target = tmp_path / 'mooninfo.json'
    target.write_text('existing validated cache', encoding="utf-8")
    def fail(*args, **kwargs):
        raise URLError('The handshake operation timed out')
    monkeypatch.setattr('moonlabeler.sources.urlopen', fail)
    with pytest.raises(DataDownloadError, match='HTTPS 握手超时') as exc:
        download('https://svs.gsfc.nasa.gov/vis/mooninfo.json', target, force=True)
    assert '地形点' in str(exc.value)
    assert target.read_text(encoding="utf-8") == 'existing validated cache'
    assert not target.with_suffix('.json.part').exists()


@pytest.mark.parametrize('previous', [None, b'previous complete data'])
def test_truncated_http_reply_does_not_become_cache(tmp_path, monkeypatch, previous):
    target = tmp_path / 'terrain.img'
    if previous is not None:
        target.write_bytes(previous)
    response = BytesIO(b'short')
    response.headers = {'Content-Length': '100'}
    monkeypatch.setattr('moonlabeler.sources.urlopen', lambda *args, **kwargs: response)
    with pytest.raises(DataDownloadError, match='不完整'):
        download('https://example.org/terrain.img', target, force=True)
    if previous is not None:
        assert target.read_bytes() == previous
    else:
        assert not target.exists()
    assert not target.with_suffix('.img.part').exists()


@pytest.mark.parametrize('length', [None, '5'])
def test_complete_http_reply_with_optional_length_is_cached(tmp_path, monkeypatch, length):
    target = tmp_path / 'terrain.img'
    response = BytesIO(b'valid')
    response.headers = {} if length is None else {'Content-Length': length}
    monkeypatch.setattr('moonlabeler.sources.urlopen', lambda *args, **kwargs: response)
    assert download('https://example.org/terrain.img', target) == target
    assert target.read_bytes() == b'valid'


@pytest.mark.parametrize('mode', ['RGBA', 'LA', 'P'])
def test_transparent_png_uses_black_background_not_hidden_pixel_color(tmp_path, mode):
    if mode == 'P':
        photo = Image.new('P', (20, 20), 0)
        photo.putpalette([255, 255, 255, 100, 100, 100] + [0]*762)
        photo.paste(1, (5, 5, 15, 15))
        photo.info['transparency'] = 0
    else:
        channels = len(mode)-1
        photo = Image.new(mode, (20, 20), (255,)*channels + (0,))
        photo.paste((100,)*channels + (255,), (5, 5, 15, 15))
    path = tmp_path / 'transparent.png'
    photo.save(path)
    actual = read_image(path)
    assert np.array_equal(actual[0, 0], [0, 0, 0])
    assert np.array_equal(actual[10, 10], [100, 100, 100])


def test_partly_transparent_png_is_alpha_blended(tmp_path):
    path = tmp_path / 'partial.png'
    Image.new('RGBA', (20, 20), (200, 100, 50, 128)).save(path)
    assert np.array_equal(read_image(path)[10, 10], [100, 50, 25])


def sixteen_bit_rgb_photo():
    ramp = np.tile(np.linspace(0, 1000, 100, dtype=np.uint16), (80, 1))
    return np.stack((ramp, ramp//3, ramp//10), axis=2)


def test_sixteen_bit_rgb_tiff_preserves_signal_and_rgb_order(tmp_path):
    path = tmp_path / 'linear-color.tif'
    pixels = sixteen_bit_rgb_photo()
    assert cv2.imwrite(str(path), pixels[:, :, ::-1])
    result = read_image(path)
    assert result.shape == pixels.shape and result.dtype == np.uint8
    assert result.min() == 0 and result.max() == 255
    red, green, blue = result[40, 80]
    assert red > 190 and 50 < green < 85 and blue < 30


def set_tiff_orientation(path, orientation):
    """Append a Classic/BigTIFF IFD while retaining the encoded pixel strips."""
    content = bytearray(path.read_bytes())
    order = '<' if content[:2] == b'II' else '>'
    big = struct.unpack_from(order+'H', content, 2)[0] == 43
    pointer, count_type, entry_size = ('Q', 'Q', 20) if big else ('I', 'H', 12)
    pointer_at, count_size = (8, 8) if big else (4, 2)
    pointer_size = struct.calcsize(pointer)
    offset = struct.unpack_from(order+pointer, content, pointer_at)[0]
    count = struct.unpack_from(order+count_type, content, offset)[0]
    begin = offset+count_size
    entries = [bytes(content[begin+entry_size*i:begin+entry_size*(i+1)]) for i in range(count)]
    entries = [entry for entry in entries if struct.unpack_from(order+'H', entry)[0] != 274]
    entry = struct.pack(order+'HH'+pointer, 274, 3, 1) + struct.pack(order+'H', orientation)
    entries.append(entry.ljust(entry_size, b'\0'))
    entries.sort(key=lambda entry: struct.unpack_from(order+'H', entry)[0])
    next_ifd = content[begin+entry_size*count:begin+entry_size*count+pointer_size]
    struct.pack_into(order+pointer, content, pointer_at, len(content))
    content.extend(struct.pack(order+count_type, len(entries))+b''.join(entries)+next_ifd)
    path.write_bytes(content)


@pytest.mark.parametrize('orientation', [2, 6])
def test_sixteen_bit_rgb_tiff_retains_exif_orientation(tmp_path, orientation):
    path = tmp_path / 'oriented-color.tif'
    assert cv2.imwrite(str(path), sixteen_bit_rgb_photo()[:, :, ::-1])
    original = read_image(path)
    set_tiff_orientation(path, orientation)
    source_bytes = path.read_bytes()
    expected = original[:, ::-1] if orientation == 2 else np.rot90(original, -1)
    assert np.array_equal(read_image(path), expected)
    assert path.read_bytes() == source_bytes


def test_eight_bit_jpeg_retains_exif_orientation(tmp_path):
    pixels = np.zeros((20, 30, 3), np.uint8)
    pixels[:, 15:, 0] = 200
    photo = Image.fromarray(pixels)
    exif = photo.getexif()
    exif[274] = 6
    path = tmp_path / 'oriented.jpg'
    photo.save(path, exif=exif, quality=100, subsampling=0)
    with Image.open(path) as original:
        expected = np.rot90(np.asarray(original), -1)
    assert np.array_equal(read_image(path), expected)


@pytest.fixture(autouse=True)
def forbid_opencv_file_decoders(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Encoded image bytes must not reach OpenCV codecs')
    monkeypatch.setattr(cv2, 'imread', forbidden)
    monkeypatch.setattr(cv2, 'imdecode', forbidden)


def test_application_does_not_call_opencv_file_or_video_codecs():
    violations = []
    for path in (Path(__file__).parents[1]/'moonlabeler').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            call = node.func
            if isinstance(call.value, ast.Name) and call.value.id == 'cv2':
                if call.attr.startswith(('imread', 'imdecode', 'imwrite', 'imencode')) or call.attr in {'VideoCapture', 'VideoWriter', 'FileStorage'}:
                    violations.append((path.name, node.lineno, call.attr))
    assert not violations, violations


def test_tiff_decoder_wheel_contains_fixed_libtiff():
    version = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', imagecodecs.tiff_version())
    assert version and tuple(map(int, version.groups())) >= (4, 7, 2), imagecodecs.tiff_version()


@pytest.mark.parametrize('version', ['libtiff 4.7.1', 'libtiff unknown'])
def test_source_build_with_old_or_unknown_libtiff_fails_closed(tmp_path, monkeypatch, version):
    path = tmp_path/'old-library.tif'
    path.write_bytes(imagecodecs.tiff_encode(sixteen_bit_rgb_photo()))
    monkeypatch.setattr(imagecodecs, 'tiff_version', lambda: version)
    with pytest.raises(ValueError, match='4.7.2'):
        read_image(path)


@pytest.mark.parametrize('compression', [None, 5, 8, 32773])
@pytest.mark.parametrize('planar', [False, True])
def test_rgb_tiff_compressions_and_planar_layout_preserve_pixels(tmp_path, compression, planar):
    pixels = sixteen_bit_rgb_photo()
    array = np.moveaxis(pixels, -1, 0) if planar else pixels
    path = tmp_path/'compressed.tif'
    options = dict(compression=compression, photometric='rgb', planarconfig='separate' if planar else 'contig')
    if compression in (5, 8):
        options['predictor'] = 2
    path.write_bytes(imagecodecs.tiff_encode(array, **options))
    low, high = np.percentile(pixels, [.2, 99.8])
    expected = np.uint8(np.clip((pixels.astype(float)-low)/(high-low), 0, 1)*255)
    assert np.array_equal(read_image(path), expected)


@pytest.mark.parametrize('orientation', range(1, 9))
@pytest.mark.parametrize('bigtiff,byteorder', [(False, '>'), (True, '<')])
def test_tiff_endianness_and_all_orientations_apply_once(tmp_path, orientation, bigtiff, byteorder):
    # Pillow's metadata reader supports Classic TIFF in either byte order and
    # little-endian BigTIFF. Big-endian BigTIFF fails before either decoder.
    path = tmp_path/'oriented.tif'
    path.write_bytes(imagecodecs.tiff_encode(sixteen_bit_rgb_photo(), bigtiff=bigtiff, byteorder=byteorder))
    original = read_image(path)
    set_tiff_orientation(path, orientation)
    stored = path.read_bytes()
    operations = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                  4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                  6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                  8: Image.Transpose.ROTATE_90}
    expected = np.asarray(Image.fromarray(original).transpose(operations[orientation])) if orientation != 1 else original
    assert np.array_equal(read_image(path), expected)
    assert path.read_bytes() == stored


def test_multipage_rgb_tiff_still_reads_only_first_page(tmp_path):
    pixels = sixteen_bit_rgb_photo()
    path = tmp_path/'pages.tif'
    encoded = imagecodecs.tiff_encode(np.stack((pixels, pixels[:, ::-1])))
    path.write_bytes(encoded)
    reference = tmp_path/'one-page.tif'
    reference.write_bytes(imagecodecs.tiff_encode(pixels))
    assert np.array_equal(read_image(path), read_image(reference))


def test_corrupt_tiff_keeps_current_editor_image(tmp_path):
    from PySide6.QtWidgets import QApplication
    from moonlabeler.app import MainWindow
    path = tmp_path/'bad-strip.tif'
    content = bytearray(imagecodecs.tiff_encode(sixteen_bit_rgb_photo(), compression=5))
    with Image.open(BytesIO(content)) as photo:
        start = photo.tag_v2[273][0]
        count = photo.tag_v2[279][0]
    content[start:start+count] = b'\xff'*count
    path.write_bytes(content)
    with pytest.raises(ValueError, match='原始像素'):
        read_image(path)
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    previous = np.full((40, 60, 3), 25, np.uint8)
    window.set_image(previous)
    project = window.project
    errors = []
    window.error = errors.append
    window.open_image(str(path))
    assert errors
    assert window.project is project and np.array_equal(window.image, previous)
    window.dirty = False
    window.close()


def test_high_depth_tiff_editor_project_and_png_roundtrip(tmp_path):
    from PySide6.QtWidgets import QApplication
    from moonlabeler.app import MainWindow
    path = tmp_path/'linear-color.tif'
    path.write_bytes(imagecodecs.tiff_encode(sixteen_bit_rgb_photo(), compression=8, predictor=2))
    expected = read_image(path)
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    errors = []
    window.error = errors.append
    try:
        window.open_image(str(path))
        assert not errors and np.array_equal(window.image, expected)
        # A neutral calibration satisfies the existing export prerequisite;
        # this test checks decoded pixel transport, not pose estimation.
        window.project.matrix = np.array([[1., 0., 0.], [0., 1., 0.]])
        saved = tmp_path/'edited.moonlabel'
        window.project.save(saved)
        window.open_project(str(saved))
        assert not errors and np.array_equal(window.image, expected)
        exported = tmp_path/'display.png'
        window.render_png(exported)
        with Image.open(exported) as result:
            assert np.array_equal(np.asarray(result.convert('RGB')), expected)
    finally:
        window.dirty = False
        window.close()

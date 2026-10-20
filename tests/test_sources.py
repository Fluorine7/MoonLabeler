# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from urllib.error import URLError
from io import BytesIO
import struct

import cv2
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
    """Append an IFD with orientation while retaining the original 16-bit strips."""
    content = bytearray(path.read_bytes())
    order = '<' if content[:2] == b'II' else '>'
    offset = struct.unpack_from(order+'I', content, 4)[0]
    count = struct.unpack_from(order+'H', content, offset)[0]
    entries = [bytes(content[offset+2+12*i:offset+14+12*i]) for i in range(count)]
    entries = [entry for entry in entries if struct.unpack_from(order+'H', entry)[0] != 274]
    entries.append(struct.pack(order+'HHIHH', 274, 3, 1, orientation, 0))
    entries.sort(key=lambda entry: struct.unpack_from(order+'H', entry)[0])
    next_ifd = content[offset+2+12*count:offset+6+12*count]
    struct.pack_into(order+'I', content, 4, len(content))
    content.extend(struct.pack(order+'H', len(entries))+b''.join(entries)+next_ifd)
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

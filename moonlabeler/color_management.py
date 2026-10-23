# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""An sRGB display/export copy, independent of recognition and source pixels."""
from functools import lru_cache
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps
from PySide6.QtGui import QColorSpace


def srgb_color_space():
    return QColorSpace(QColorSpace.NamedColorSpace.SRgb)


@lru_cache(maxsize=1)
def srgb_profile_bytes():
    return bytes(srgb_color_space().iccProfile())


def display_srgb(image, image_path=""):
    """Convert the source ICC encoding once; untagged display RGB assumes sRGB.

    The caller retains the untouched array for measurement and recognition.
    Colour conversion precedes artistic desaturation and sRGB overlay painting,
    so annotation colours are never transformed as if they were photo samples.
    """
    if not image_path or Path(image_path).suffix.lower() in ('.fit', '.fits', '.fts'):
        return image
    try:
        with Image.open(image_path) as source:
            encoded_profile = source.info.get('icc_profile')
            cmyk = ImageOps.exif_transpose(source).copy() if encoded_profile and source.mode == 'CMYK' else None
    except (OSError, ValueError):
        # In-memory images need not have an accessible original file.
        return image
    if not encoded_profile:
        return image
    if QColorSpace.fromIccProfile(encoded_profile) == srgb_color_space():
        return image
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(encoded_profile))
        color_space = profile.profile.xcolor_space.strip()
        base = Image.fromarray(image)
        if color_space == 'GRAY':
            base = base.convert('L')
        elif color_space == 'CMYK' and cmyk is not None:
            base = cmyk
        target = ImageCms.ImageCmsProfile(io.BytesIO(srgb_profile_bytes()))
        converted = ImageCms.profileToProfile(base, profile, target, outputMode='RGB',
                                              renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    except (ImageCms.PyCMSError, OSError, ValueError) as exc:
        raise ValueError("无法将照片的 ICC 色彩配置转换为 sRGB。") from exc
    if converted.size != (image.shape[1], image.shape[0]):
        raise ValueError("色彩转换后的照片尺寸与当前照片不一致。")
    return np.asarray(converted)

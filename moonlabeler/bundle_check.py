# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the shipped application, without an external Python installation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import traceback


def run(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"platform": sys.platform, "system": platform.mac_ver()[0] or platform.version(), "architecture": platform.machine(),
              "python": platform.python_version(), "checks": [], "success": False}
    window = None
    try:
        assert getattr(sys, "frozen", False), "Run this check inside the packaged app"
        executable = Path(sys.executable).resolve()
        bundle = executable.parents[2] if sys.platform == "darwin" else executable.parent
        if sys.platform == "darwin":
            assert bundle.suffix == ".app", bundle
        import numpy as np
        from PIL import Image
        import imagecodecs
        from astropy.io import fits
        from PySide6.QtWidgets import QApplication
        from ._opencv import cv2
        from .registration import auto_register, fit_similarity, transform_points
        from .craters import detect_crater_rims
        from .geometry import compute_geometry
        from .project import Project, export_svg
        from .app import MainWindow, ROOT, CACHE, prepare_cache

        assert Path(cv2.__file__).resolve().is_relative_to(bundle)
        assert Path(np.__file__).resolve().is_relative_to(bundle)
        assert not any(hasattr(cv2, name) for name in ("imread", "imwrite", "VideoCapture", "imshow"))
        assert callable(cv2.SIFT_create) and callable(cv2.ximgproc.createEdgeDrawing)
        report["opencv"] = cv2.__version__
        report["libtiff"] = imagecodecs.tiff_version()
        report["checks"].append("bundled Python, Qt and private codec-free OpenCV")

        prepare_cache()
        kernels = ("de421.bsp", "moon_080317.tf", "pck00008.tpc", "moon_pa_de421_1900-2050.bpc")
        assert all((CACHE / "ephemeris" / name).is_file() for name in kernels)
        compute_geometry(datetime(2026, 1, 1, tzinfo=timezone.utc), CACHE / "ephemeris")
        report["checks"].append("four bundled JPL kernels and offline lunar geometry")

        source = np.array([[0., 0], [.2, .4], [-.6, .1], [.4, -.5]])
        for mirror in (1, -1):
            expected = np.array([[150*np.cos(.7)*mirror, -150*np.sin(.7), 720],
                                 [150*np.sin(.7)*mirror, 150*np.cos(.7), 540]])
            actual, rms = fit_similarity(source, transform_points(expected, source))
            assert rms < 1e-9 and np.allclose(actual, expected)
        rng = np.random.default_rng(7)
        reference = cv2.GaussianBlur(rng.integers(0, 256, (480, 640), dtype=np.uint8), (5, 5), 1.)
        photograph = reference[80:400, 120:540].copy()
        match = auto_register(reference, photograph)
        assert match.inliers >= 12
        assert np.allclose(match.matrix, [[1., 0., -120], [0., 1., -80]], atol=.1)
        report["checks"].append("manual mirrored registration and automatic SIFT registration")

        image = np.full((360, 520), 72, np.uint8)
        cv2.circle(image, (110, 140), 35, 215, 3)
        cv2.ellipse(image, (350, 190), (60, 30), 35, 0, 360, 205, 3)
        original = image.copy()
        candidates = detect_crater_rims(image).candidates
        for x, y in ((110, 140), (350, 190)):
            assert any(np.hypot(c.x-x, c.y-y) < 5 for c in candidates)
        assert np.array_equal(image, original)
        report["checks"].append("EdgeDrawing circular and elliptical crater rims")

        from .sources import read_image
        output = report_path.parent / "exports"
        output.mkdir(exist_ok=True)
        rgb16 = rng.integers(0, 65536, (48, 64, 3), dtype=np.uint16)
        (output / "rgb16.tif").write_bytes(imagecodecs.tiff_encode(rgb16))
        assert np.array_equal(imagecodecs.tiff_decode((output / "rgb16.tif").read_bytes()), rgb16)
        assert read_image(output / "rgb16.tif").shape == rgb16.shape
        fits.writeto(output / "sample.fits", np.arange(48*64, dtype=np.float32).reshape(48, 64), overwrite=True)
        assert read_image(output / "sample.fits").shape == (48, 64, 3)
        report["checks"].append("16-bit RGB TIFF and FITS decoding")

        application = QApplication.instance() or QApplication([])
        window = MainWindow()
        errors = []
        window.error = errors.append
        window.showMaximized()
        application.processEvents()
        window.open_project(ROOT / "examples" / "demo.moonlabel")
        application.processEvents()
        assert not errors, [str(error) for error in errors]
        assert len(window.annotation_items) > 5
        saved = output / "roundtrip.moonlabel"
        window.project.save(saved)
        assert Project.load(saved).labels == window.project.labels
        window.render_png(output / "annotated.png")
        with Image.open(output / "annotated.png") as rendered:
            assert rendered.size == (1600, 1450), rendered.size
        export_svg(output / "annotated.svg", window.image, window.annotation_entries(), window.project, window.annotation_leaders())
        import xml.etree.ElementTree as ET
        assert ET.parse(output / "annotated.svg").getroot().tag.endswith("svg")
        assert (output / "annotated.svg").stat().st_size > 10000
        assert window.grab().save(str(output / "application.png"))
        report["checks"].append("Qt demo project, editable annotations, save/reopen, PNG and SVG exports")
        try:
            import wgpu
        except ImportError:
            report["wgpu"] = None
            available, detail = False, "Optional wgpu is not bundled on this platform"
        else:
            report["wgpu"] = wgpu.__version__
            from . import terrain_wgpu
            available, detail = terrain_wgpu.support()
        report["metal"] = {"available": available, "detail": detail}
        if available:
            from .geometry import Geometry
            from .terrain import ElevationMap
            from .terrain_identification import _render_terrain_atlas_cpu
            y, x = np.mgrid[:180, :360]
            dem = ElevationMap((2*np.sin(x*.12)*np.cos(y*.08)).astype(np.float32), 90, 0, 1)
            view = Geometry(np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]),
                            np.array([.3, np.sqrt(.91), 0]), 384400, "2026-01-01T00:00:00+00:00")
            gpu, projection = terrain_wgpu.render(dem, view, 269)
            cpu, expected_projection = _render_terrain_atlas_cpu(dem, view, 269)
            assert np.array_equal(projection, expected_projection)
            delta = np.abs(gpu.astype(float) - cpu)
            assert delta.mean() < .1 and np.mean(delta > 2) < .001
            report["checks"].append("Metal terrain rendering compared with CPU")
        report["success"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if window is not None:
            window.dirty = False
            window.close()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["success"] else 1

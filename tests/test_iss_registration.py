# SPDX-License-Identifier: GPL-3.0-or-later
"""Local ISS photograph: independent visible landmarks, never search inputs."""
from pathlib import Path
import numpy as np
import pytest
from moonlabeler.sources import read_image, load_catalog
from moonlabeler.registration import transform_points
from moonlabeler.craters import detect_craters

ROOT = Path(__file__).resolve().parents[1]
PHOTO = ROOT/'20250503.jpg'


def photo():
    if not PHOTO.exists():
        pytest.skip('Local photographer image is not redistributed')
    return read_image(PHOTO)


def geometry():
    from datetime import datetime
    from moonlabeler.geometry import compute_geometry
    if not (ROOT/'.cache/terrain/LDEM_16.IMG').exists() or not (ROOT/'.cache/ephemeris/de421.bsp').exists():
        pytest.skip('Cached terrain and ephemerides required')
    return compute_geometry(datetime.fromisoformat('2025-05-03T11:36:15+00:00'), ROOT/'.cache/ephemeris')


def test_iss_assisted_detection_rejects_ridge_circles_without_losing_clear_rims():
    candidates = detect_craters(photo()).candidates
    # Visually inspected before the change: ridge/overlapping-rim combinations,
    # as opposed to a single crater centered at the proposed position.
    for x, y in ((604, 444), (563, 473), (559, 483), (381, 382)):
        assert not any(np.hypot(c.x-x, c.y-y) < 5 and c.method == 'circle' for c in candidates)
    for x, y in ((409, 350), (1166, 463), (738, 698), (1059, 604)):
        assert any(np.hypot(c.x-x, c.y-y) < 7 for c in candidates)
    # Two offset circular fits to the same Colombo floor are one proposal.
    assert sum(680 < c.x < 705 and 575 < c.y < 595 and c.method == 'circle'
               for c in candidates) == 1


def test_iss_automatic_workflow_recovers_distributed_landmarks():
    from PySide6.QtWidgets import QApplication
    from moonlabeler import app as module
    from moonlabeler.project import Project
    if not (ROOT/'.cache/terrain/LDEM_16.IMG').exists():
        pytest.skip('Cached DEM required')
    application = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    errors, results = [], []
    try:
        window.project = Project(image_path=str(PHOTO), utc='2025-05-03T11:36:15+00:00')
        window.set_image(photo())
        window.sync_controls()
        window.error = errors.append
        def synchronous(title, work, success, failure):
            try:
                results.append(work())
            except ValueError as exc:
                errors.append(str(exc))
        window.run_background = synchronous
        window.identify_photo()
        assert not errors, errors
        assert results
        _, result, geometry, _, _ = results[0]
        effective = result.projection_geometry or geometry
        catalog = load_catalog(ROOT/'.cache')
        # Independent photograph positions, not provided to matching/refinement.
        landmarks = {'Pitiscus': (409, 350), 'Mutus': (332, 295),
                     'Rosenberger': (366, 387), 'Posidonius': (1166, 463),
                     'Langrenus': (738, 698), 'Macrobius': (1059, 604)}
        for name, expected in landmarks.items():
            feature = next(f for f in catalog if f['name'] == name)
            point = effective.project([feature['lat']], [feature['lon']])[0]
            actual = transform_points(result.matrix, point)[0]
            assert np.linalg.norm(actual-expected) < 8, (name, actual)
        assert result.image_inliers >= 80
        assert len(result.refinement['validation_folds']) >= 4
        assert result.refinement['validation_after_px'] < 1.5
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('transform', ['original', 'mirror', 'rotate'])
def test_limb_terrain_verification_preserves_orientation_and_exclusion_masks(transform):
    from moonlabeler.limb import identify_from_limb
    from moonlabeler.recognition_mask import PhotoMask
    image = photo()
    known = np.array([[409., 350.], [1166., 463.], [738., 698.]])
    excluded = np.array([[1061., 470.], [1153., 590.]])
    if transform == 'mirror':
        known[:, 0] = image.shape[1]-1-known[:, 0]
        excluded[:, 0] = image.shape[1]-1-excluded[:, 0]
        image = image[:, ::-1].copy()
    elif transform == 'rotate':
        known = np.column_stack((known[:, 1], image.shape[1]-1-known[:, 0]))
        excluded = np.column_stack((excluded[:, 1], image.shape[1]-1-excluded[:, 0]))
        image = np.rot90(image).copy()
    original = image.copy()
    mask = PhotoMask([{'kind': 'paint', 'points': [point.tolist()], 'radius': 22}
                      for point in excluded], image.shape)
    result = identify_from_limb(image, geometry(), cache=ROOT/'.cache', photo_mask=mask)
    features = [next(f for f in load_catalog(ROOT/'.cache') if f['name'] == name)
                for name in ('Pitiscus', 'Posidonius', 'Langrenus')]
    projected = result.projection_geometry.project([f['lat'] for f in features], [f['lon'] for f in features])[0]
    assert np.max(np.linalg.norm(transform_points(result.matrix, projected)-known, axis=1)) < 8
    assert np.array_equal(image, original)


@pytest.mark.parametrize('defect', ['sparse_fresh_points', 'clustered_fresh_points', 'bad_dense_match',
                                  'inconsistent_limb', 'missing_dem'])
def test_limb_seed_cannot_bypass_independent_terrain_verification(monkeypatch, defect):
    from moonlabeler import limb_refinement as refinement
    from moonlabeler.limb import identify_from_limb
    from moonlabeler.identification import IdentificationError
    image, view = photo(), geometry()
    actual = refinement.local_correspondences
    calls = []
    def correspondences(*args, **kwargs):
        source, target = actual(*args, **kwargs)
        calls.append(len(source))
        if len(calls) == 2:
            if defect == 'sparse_fresh_points':
                return source[:20], target[:20]
            if defect == 'clustered_fresh_points':
                keep = source[:, 0] < 400
                return source[keep], target[keep]
        return source, target
    monkeypatch.setattr(refinement, 'local_correspondences', correspondences)
    if defect == 'bad_dense_match':
        monkeypatch.setattr(refinement, 'terrain_agreement', lambda *a, **kw: (.7, .1))
    if defect == 'inconsistent_limb':
        measured_error = refinement._limb_error
        checks = []
        def inconsistent(*args):
            checks.append(True)
            return measured_error(*args) if len(checks) == 1 else 50.
        monkeypatch.setattr(refinement, '_limb_error', inconsistent)
    if defect == 'missing_dem':
        def missing(*args):
            raise OSError('DEM unavailable')
        monkeypatch.setattr(refinement, 'download_basic_dem', missing)
    with pytest.raises(IdentificationError):
        identify_from_limb(image, view, cache=ROOT/'.cache')
    if defect != 'missing_dem':
        assert len(calls) == 2

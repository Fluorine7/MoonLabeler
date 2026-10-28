# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Mapped DEM views must survive cleanup while a traceback still owns them."""
from pathlib import Path
import subprocess
import sys
import textwrap
import weakref

import numpy as np
import pytest

from moonlabeler.terrain import ElevationMap


def mapped_dem(tmp_path):
    path = tmp_path/'height.img'
    np.arange(16, dtype='<i2').reshape(4, 4).tofile(path)
    return ElevationMap(np.memmap(path, dtype='<i2', mode='r', shape=(4, 4)), 2, 0, 1)


def test_interrupt_report_can_print_dem_argument_after_cleanup(tmp_path):
    # Run in a child: the regression is a native invalid-memory access, not a
    # Python exception. A failure must not take down the rest of the test suite.
    script = textwrap.dedent('''
        from pathlib import Path
        import sys
        sys.path.insert(0, str(Path.cwd()))
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except ImportError:
            pass
        import numpy as np
        from _pytest._code import ExceptionInfo
        from moonlabeler.terrain import ElevationMap

        def interrupted_operation(data):
            assert data[0, 0] == 0
            raise KeyboardInterrupt

        path = Path(sys.argv[1])/'height.img'
        np.arange(16, dtype='<i2').reshape(4, 4).tofile(path)
        dem = ElevationMap(np.memmap(path, dtype='<i2', mode='r', shape=(4, 4)), 2, 0, 1)
        try:
            try:
                interrupted_operation(np.asarray(dem.data))
            finally:
                dem.close()
        except KeyboardInterrupt:
            report = str(ExceptionInfo.from_current().getrepr(funcargs=True))
            assert 'KeyboardInterrupt' in report
            assert 'interrupted_operation' in report
            assert 'array(' in report
            print('Interrupt report completed')
    ''')
    script_path = tmp_path/'report_interrupt.py'
    script_path.write_text(script, encoding='utf-8')
    result = subprocess.run([sys.executable, '-X', 'faulthandler', str(script_path), str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'Interrupt report completed' in result.stdout


def test_close_preserves_borrowed_views_without_copying_or_leaking(tmp_path):
    dem = mapped_dem(tmp_path)
    view = np.asarray(dem.data)[1:3, 1:3]
    owner, mapping = weakref.ref(dem.data), weakref.ref(dem.data._mmap)
    assert dem.maximum_height_km == 15
    dem.close()
    dem.close()  # Cleanup remains idempotent.
    assert dem.data is None
    assert owner() is not None and mapping() is not None and not mapping().closed
    assert np.array_equal(view, [[5, 6], [9, 10]])
    with pytest.raises(ValueError, match='已关闭'):
        dem.sample([1.5], [.5])
    with pytest.raises(ValueError, match='已关闭'):
        _ = dem.maximum_height_km
    del view
    assert owner() is None and mapping() is None


def test_close_releases_unborrowed_mapping_immediately(tmp_path):
    dem = mapped_dem(tmp_path)
    owner, mapping = weakref.ref(dem.data), weakref.ref(dem.data._mmap)
    dem.close()
    assert dem.data is None
    assert owner() is None and mapping() is None


def test_close_during_sampling_keeps_in_flight_array_alive(tmp_path, monkeypatch):
    dem = mapped_dem(tmp_path)
    expected = dem.sample([1., .5], [1., 2.])
    broadcast = np.broadcast_arrays
    def close_then_broadcast(*args, **kwargs):
        dem.close()
        return broadcast(*args, **kwargs)
    monkeypatch.setattr(np, 'broadcast_arrays', close_then_broadcast)
    assert np.array_equal(dem.sample([1., .5], [1., 2.]), expected)
    assert dem.data is None


def test_in_memory_map_also_releases_owned_data_on_close():
    dem = ElevationMap(np.zeros((4, 4)), 2, 0, 1)
    dem.close()
    assert dem.data is None
    with pytest.raises(ValueError, match='已关闭'):
        dem.sample([1.5], [.5])

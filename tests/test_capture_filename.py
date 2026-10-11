# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""WinJUPOS timestamps are UT with an optional tenth of a minute."""
import pytest
from moonlabeler.capture_time import winjupos_capture_time

@pytest.mark.parametrize('name, expected', [
    ('2026-08-31-2137_7-Moon_lapl3_ap311(1).tif', '2026-08-31T21:37:42+00:00'),
    ('Zhu-2026-08-31-2137.7-Moon.png', '2026-08-31T21:37:42+00:00'),
    ('2026-08-31-21377-Zhu-Moon.png', '2026-08-31T21:37:42+00:00'),
    ('2024-02-29-2359_9.tif', '2024-02-29T23:59:54+00:00'),
    ('2026-08-31-2137.png', '2026-08-31T21:37:00+00:00'),
    ('2026-08-31-2137_Moon.png', '2026-08-31T21:37:00+00:00'),
])
def test_standard_timestamp(name, expected):
    assert winjupos_capture_time(name).isoformat() == expected

@pytest.mark.parametrize('name', [
    '0817.png', '2026-08-31.png', '2025-02-29-2137_7.tif',
    '2026-08-31-2437_7.tif', '2026-08-31-2160_7.tif',
    '2026-08-31-2137_77.tif', '2026-08-31-213777.tif',
    '2026-08-31-2137.77.tif', '2026-08-31-2137_7x.tif',
    '/photos/2026-08-31-2137_7/untimed.png',
])
def test_no_partial_or_invalid_timestamp(name):
    assert winjupos_capture_time(name) is None

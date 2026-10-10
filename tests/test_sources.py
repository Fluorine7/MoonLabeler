# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from urllib.error import URLError

import pytest

from moonlabeler.sources import DataDownloadError, download


def test_nasa_tls_timeout_has_manual_fallback_and_keeps_cached_data(tmp_path, monkeypatch):
    target = tmp_path / 'mooninfo.json'
    target.write_text('existing validated cache')
    def fail(*args, **kwargs):
        raise URLError('The handshake operation timed out')
    monkeypatch.setattr('moonlabeler.sources.urlopen', fail)
    with pytest.raises(DataDownloadError, match='HTTPS 握手超时') as exc:
        download('https://svs.gsfc.nasa.gov/vis/mooninfo.json', target, force=True)
    assert '地形点' in str(exc.value)
    assert target.read_text() == 'existing validated cache'
    assert not target.with_suffix('.json.part').exists()

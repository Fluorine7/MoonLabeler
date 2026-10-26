# SPDX-License-Identifier: GPL-3.0-or-later
"""Release retries verify published assets and never replace them."""
import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
import subprocess
import textwrap

import pytest


@pytest.fixture
def publication(tmp_path, monkeypatch):
    workflow = Path(__file__).parents[1]/'.github/workflows/windows-build.yml'
    script = compile(textwrap.dedent(workflow.read_text(encoding='utf-8').rsplit('        run: |\n', 1)[1]),
                     str(workflow), 'exec')
    monkeypatch.chdir(tmp_path)
    Path('pyproject.toml').write_text('[project]\nversion = "0.10.2"\n', encoding='utf-8')
    archive = Path('portable/dist/MoonLabeler-0.10.2-windows-x64.zip')
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'verified portable archive fixture')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n', encoding='ascii')
    for key, value in {'GITHUB_REPOSITORY': 'Fluorine7/MoonLabeler',
                       'SOURCE_SHA': 'a'*40, 'TAG': 'v0.10.2'}.items():
        monkeypatch.setenv(key, value)
    release = {'tag_name': 'v0.10.2', 'draft': False,
               'assets': [{'name': archive.name, 'digest': 'sha256:'+digest},
                          {'name': 'MoonLabeler-0.10.2-macos-arm64.zip', 'digest': 'sha256:'+'b'*64}]}
    writes = []

    def existing(*args, **kwargs):
        return CompletedProcess(args[0], 0, json.dumps({'isDraft': release['draft'], 'assets': release['assets']}))

    def github(args, **kwargs):
        if args[1] == 'api':
            return json.dumps([release] if '?' in args[2] else release)
        if args[1:3] == ['release', 'upload']:
            writes.append(args)
            return ''
        pytest.fail(f'Unexpected release mutation: {args[1:3]}')

    monkeypatch.setattr(subprocess, 'run', existing)
    monkeypatch.setattr(subprocess, 'check_output', github)
    return script, release, writes


def test_published_release_retry_verifies_without_uploading(publication):
    script, _, writes = publication
    with pytest.raises(SystemExit) as result:
        exec(script, {})
    assert result.value.code == 0 and not writes


@pytest.mark.parametrize('mismatch', ['digest', 'extra', 'missing'])
def test_published_release_mismatch_stops_without_writing(publication, mismatch):
    script, release, writes = publication
    if mismatch == 'digest':
        release['assets'][0]['digest'] = 'sha256:'+'0'*64
    elif mismatch == 'extra':
        release['assets'].append({'name': 'debug-report.json'})
    else:
        release['assets'].pop()
    with pytest.raises(AssertionError):
        exec(script, {})
    assert not writes


def test_existing_draft_still_accepts_only_the_verified_windows_archive(publication):
    script, release, writes = publication
    release['draft'] = True
    exec(script, {})
    assert len(writes) == 1
    assert writes[0][-1] == 'portable/dist/MoonLabeler-0.10.2-windows-x64.zip'

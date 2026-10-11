# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Conservative capture-time import from WinJUPOS image filenames.

WinJUPOS 12.4.1 English help, Image measurement / Image / WinJUPOS-
Conventions, defines HHMM[.][T] in UT, where T is a tenth of a minute.
Also accept the underscore separator used by capture applications.
"""
from datetime import datetime, timezone
from pathlib import Path
import re


_STAMP = re.compile(
    r'^(?:[^-]+-)?(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-'
    r'(?P<hour>\d{2})(?P<minute>\d{2})(?:[._]?(?P<tenth>\d))?'
    r'(?=$|[-_( ]|\.[A-Za-z])'
)


def winjupos_capture_time(path):
    """Return aware UTC, or None without guessing missing/invalid components.

    Ignore directory names. Invalid numeric fractions must not fall back to a
    truncated minute-only match. A filename cannot verify the capture program's
    timezone setting; users may still correct the imported value.
    """
    name = Path(path).name
    match = _STAMP.match(name)
    if match is None:
        return None
    tail = name[match.end():]
    if tail.startswith(('_', '.')) and len(tail) > 1 and tail[1].isdigit():
        return None
    try:
        parts = {key: int(match[key]) for key in ('year', 'month', 'day', 'hour', 'minute')}
        return datetime(**parts, second=int(match['tenth'] or 0)*6, tzinfo=timezone.utc)
    except ValueError:
        return None

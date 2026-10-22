# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from moonlabeler.app import main
import os
import sys

if __name__ == "__main__":
    if getattr(sys, "frozen", False) and os.environ.get("MOONLABELER_BUNDLE_CHECK"):
        from moonlabeler.bundle_check import run
        raise SystemExit(run(os.environ["MOONLABELER_BUNDLE_CHECK"]))
    main()

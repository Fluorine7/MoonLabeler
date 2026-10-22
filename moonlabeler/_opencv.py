"""Load our private extension using the module name required by OpenCV."""
# SPDX-License-Identifier: GPL-3.0-or-later
from importlib.util import find_spec, module_from_spec, spec_from_file_location

try:
    location = find_spec('_moonlabeler_opencv.cv2')
except ModuleNotFoundError:
    location = None
if location is None:
    raise ImportError('MoonLabeler requires its minimal OpenCV build; run python -m pip install .')
spec = spec_from_file_location('cv2', location.origin)
cv2 = module_from_spec(spec)
spec.loader.exec_module(cv2)

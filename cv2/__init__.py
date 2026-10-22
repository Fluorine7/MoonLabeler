"""Compatibility name for MoonLabeler's private, codec-free OpenCV build."""
import sys
from moonlabeler._opencv import cv2

sys.modules[__name__] = cv2

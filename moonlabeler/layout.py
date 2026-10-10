# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Place labels around their objects, keeping captions and leaders separate.

Inspired by AnnotateImage's candidate relocation / local clearance strategy;
independently implemented for a lunar photograph and user-pinned captions.
"""
from dataclasses import dataclass
import math

@dataclass
class LabelBox:
    key: str
    anchor: tuple
    width: float
    height: float
    radius: float = 4.
    fixed: tuple | None = None  # Actual bounding-box top-left, in image pixels.
    force: bool = False
    outline: list | None = None


def rect_intersects(first, second, padding=0.):
    x, y, w, h = first
    a, b, c, d = second
    return x < a+c+padding and x+w+padding > a and y < b+d+padding and y+h+padding > b


def rect_distance(first, second):
    x, y, w, h = first
    a, b, c, d = second
    return math.hypot(max(a-x-w, x-a-c, 0), max(b-y-h, y-b-d, 0))


def leader_segment(anchor, rect, hole=3., outline=None):
    """Stop at the nearest caption edge, never run underneath the text."""
    x, y, w, h = rect
    ax, ay = anchor
    ex, ey = max(x, min(ax, x+w)), max(y, min(ay, y+h))
    if x < ax < x+w and y < ay < y+h:
        choices = [(x, ay), (x+w, ay), (ax, y), (ax, y+h)]
        ex, ey = min(choices, key=lambda p: math.hypot(p[0]-ax, p[1]-ay))
    length = math.hypot(ex-ax, ey-ay)
    if length <= hole:
        return (ax, ay, ax, ay)
    if outline:
        # Intersect the center-to-caption ray with the projected rim. This
        # starts the leader at the contour, without drawing over the crater.
        dx, dy = ex-ax, ey-ay
        intersections = []
        for segment in outline:
            for (px, py), (qx, qy) in zip(segment, segment[1:]):
                vx, vy = qx-px, qy-py
                cross = dx*vy-dy*vx
                if abs(cross) < 1e-10:
                    continue
                t = ((px-ax)*vy-(py-ay)*vx)/cross
                u = ((px-ax)*dy-(py-ay)*dx)/cross
                if 0 <= t <= 1 and 0 <= u <= 1:
                    intersections.append(t)
        if intersections:
            t = max(intersections)
            return (ax+t*dx, ay+t*dy, ex, ey)
        return (ex, ey, ex, ey)  # Caption inside the contour: no interior line.
    return (ax+(ex-ax)*hole/length, ay+(ey-ay)*hole/length, ex, ey)


def segment_hits_rect(segment, rect, padding=0.):
    """Liang–Barsky clipping against a rectangle interior."""
    x, y, w, h = rect
    x, y, w, h = x-padding, y-padding, w+2*padding, h+2*padding
    ax, ay, bx, by = segment
    dx, dy = bx-ax, by-ay
    low, high = 0., 1.
    for p, q in ((-dx, ax-x), (dx, x+w-ax), (-dy, ay-y), (dy, y+h-ay)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        elif p < 0:
            low = max(low, q/p)
        else:
            high = min(high, q/p)
        if low > high:
            return False
    return low < high and high > 1e-5 and low < 1-1e-5


def segments_cross(first, second):
    ax, ay, bx, by = first
    cx, cy, dx, dy = second
    def side(px, py, qx, qy, rx, ry):
        return (qx-px)*(ry-py)-(qy-py)*(rx-px)
    return side(ax, ay, bx, by, cx, cy)*side(ax, ay, bx, by, dx, dy) < -1e-8 and \
           side(cx, cy, dx, dy, ax, ay)*side(cx, cy, dx, dy, bx, by) < -1e-8


def candidate_boxes(label, gap):
    """Sixteen directions at each of three local distances."""
    ax, ay = label.anchor
    # Begin with diagonals for compact captions, then cardinal directions.
    angles = [45, -45, 135, -135, 0, 180, 90, -90,
              22.5, -22.5, 157.5, -157.5, 67.5, -67.5, 112.5, -112.5]
    rim_distances = {}
    if label.outline:
        outer = max(math.hypot(px-ax, py-ay) for segment in label.outline for px, py in segment)*2
        for angle in angles:
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            endpoint = (ax+outer*dx, ay+outer*dy, 0., 0.)
            start = leader_segment(label.anchor, endpoint, outline=label.outline)
            # An occulted arc may have no intersection in this direction.
            if start[:2] != start[2:]:
                rim_distances[angle] = math.hypot(start[0]-ax, start[1]-ay)
    for extra in (0., gap, 2.5*gap):
        for angle in angles:
            distance = rim_distances.get(angle, label.radius)+gap+extra
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            x = ax+distance*dx-(label.width if dx < -.1 else label.width/2 if abs(dx) <= .1 else 0)
            y = ay+distance*dy-(label.height if dy < -.1 else label.height/2 if abs(dy) <= .1 else 0)
            yield (x, y, label.width, label.height)


def arrange_labels(labels, width, height, gap=8.):
    """Return non-overlapping placements and temporarily omitted keys.

    Input order expresses priority. User-pinned captions are fixed obstacles.
    A forced caption can fall back to the least-conflicting candidate. Automatic
    positions are never stored as user edits, so filtering can reflow the image.
    """
    placements = {}
    leaders = {}
    # Other centers are obstacles, not their entire crater interiors. Treating
    # every large, eroded catalogue crater as a forbidden disk can leave no
    # caption space around an otherwise prominent crater on a whole-Moon map.
    marker_radius = {label.key: min(label.radius, max(4., label.height*.45)) for label in labels}
    markers = {label.key: (label.anchor[0]-marker_radius[label.key], label.anchor[1]-marker_radius[label.key],
                            2*marker_radius[label.key], 2*marker_radius[label.key]) for label in labels}
    fixed = {label.key for label in labels if label.fixed is not None}
    for label in labels:
        if label.fixed is not None:
            rect = (*label.fixed, label.width, label.height)
            placements[label.key] = rect
            leaders[label.key] = leader_segment(label.anchor, rect, outline=label.outline)

    def best_position(label):
        candidates = []
        other_rects = [rect for key, rect in placements.items() if key != label.key]
        other_lines = [line for key, line in leaders.items() if key != label.key]
        other_markers = [rect for key, rect in markers.items() if key != label.key]
        for rect in candidate_boxes(label, gap):
            x, y, w, h = rect
            if x < gap or y < gap or x+w > width-gap or y+h > height-gap:
                continue
            line = leader_segment(label.anchor, rect, outline=label.outline)
            # Captions cannot hide their own center, or other selected centers.
            if not label.force:
                # Most rejected positions hit a nearby caption or marker.
                # Stop on the first collision instead of counting every
                # conflict and performing expensive line tests unnecessarily.
                if any(rect_intersects(rect, old, gap*.65) for old in other_rects):
                    continue
                if any(rect_intersects(rect, old, gap*.3) for old in markers.values()):
                    continue
                if any(segment_hits_rect(line, old, 1) for old in other_rects):
                    continue
                if any(segment_hits_rect(old, rect, 1) or segments_cross(line, old) for old in other_lines):
                    continue
                if any(segment_hits_rect(line, old) for old in other_markers):
                    continue
                conflicts = 0
            else:
                conflicts = sum(rect_intersects(rect, old, gap*.65) for old in other_rects)
                conflicts += sum(rect_intersects(rect, old, gap*.3) for old in markers.values())
                conflicts += sum(segment_hits_rect(line, old, 1) for old in other_rects)
                conflicts += sum(segment_hits_rect(old, rect, 1) for old in other_lines)
                conflicts += sum(segments_cross(line, old) for old in other_lines)
                conflicts += sum(segment_hits_rect(line, old) for old in other_markers)
            # Like AnnotateImage, prefer locally separated captions. Limit the
            # reward so empty corners do not pull labels away from their objects.
            clearance = min((rect_distance(rect, old) for old in other_rects+other_markers), default=3*gap)
            length = math.hypot(line[2]-line[0], line[3]-line[1])
            score = conflicts*1e6 + .45*length - .8*min(clearance, 3*gap)
            candidates.append((score, rect, line))
        return min(candidates, key=lambda item: item[0]) if candidates else None

    pending = [label for label in labels if label.key not in fixed]
    # Greedy placement gives larger named features first choice.
    for label in pending:
        best = best_position(label)
        if best:
            _, placements[label.key], leaders[label.key] = best
    # Relocate existing captions and reinsert omissions, with a bounded loop.
    for _ in range(2):
        moved = False
        for label in pending:
            previous = placements.get(label.key)
            best = best_position(label)
            if best:
                _, placements[label.key], leaders[label.key] = best
                moved |= previous != placements[label.key]
        if not moved:
            break
    omitted = {label.key for label in labels if label.key not in placements}
    return placements, omitted

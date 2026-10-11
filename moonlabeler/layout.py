# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Place labels around their objects, keeping captions and leaders separate.

Candidate relocation and local clearance for lunar photographs and
user-pinned captions.
"""
from dataclasses import dataclass
from itertools import islice
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
    important: bool = False  # Reserve space before ordinary automatic labels.


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


def candidate_boxes(label, gap, *, extended=False):
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
    distances = (4*gap, 7*gap, 11*gap) if extended else (0., gap, 2.5*gap)
    for extra in distances:
        for angle in angles:
            distance = rim_distances.get(angle, label.radius)+gap+extra
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            x = ax+distance*dx-(label.width if dx < -.1 else label.width/2 if abs(dx) <= .1 else 0)
            y = ay+distance*dy-(label.height if dy < -.1 else label.height/2 if abs(dy) <= .1 else 0)
            yield (x, y, label.width, label.height)


class _SpatialIndex:
    """Conservative grid lookup; exact collision tests still decide placement."""
    def __init__(self, cell_size):
        self.cell_size = cell_size
        self.buckets = {}
        self.cells = {}
        self.values = {}

    def _cells(self, rect, padding=0.):
        x, y, w, h = rect
        size = self.cell_size
        for column in range(math.floor((x-padding)/size), math.floor((x+w+padding)/size)+1):
            for row in range(math.floor((y-padding)/size), math.floor((y+h+padding)/size)+1):
                yield column, row

    def remove(self, key):
        for cell in self.cells.pop(key, ()):
            bucket = self.buckets[cell]
            bucket.remove(key)
            if not bucket:
                del self.buckets[cell]
        self.values.pop(key, None)

    def put(self, key, rect, value=None):
        self.remove(key)
        self.cells[key] = tuple(self._cells(rect))
        self.values[key] = rect if value is None else value
        for cell in self.cells[key]:
            self.buckets.setdefault(cell, set()).add(key)

    def near(self, rect, padding=0., exclude=None):
        keys = set()
        for cell in self._cells(rect, padding):
            keys.update(self.buckets.get(cell, ()))
        keys.discard(exclude)
        # A stable order preserves deterministic floating-point scoring.
        return [self.values[key] for key in sorted(keys)]


def _line_bounds(line):
    x, y, a, b = line
    return min(x, a), min(y, b), abs(a-x), abs(b-y)


def arrange_labels(labels, width, height, gap=8., *, max_labels=None):
    """Return non-overlapping placements and temporarily omitted keys.

    Important captions reserve space before ordinary centers are considered.
    Within each group, input order expresses priority. User pins stay fixed.
    A forced caption can fall back to the least-conflicting candidate. Automatic
    positions are never stored as user edits, so filtering can reflow the image.
    With a budget, consume candidates lazily and refill omissions from reserves.
    Unused reserve centers are not obstacles and do not count as omissions.
    """
    reserve = iter(labels)
    labels = list(reserve) if max_labels is None else list(islice(reserve, max(0, max_labels)))
    placements = {}
    leaders = {}
    text_index, line_index, marker_index = (_SpatialIndex(max(32., gap*4)) for _ in range(3))

    def place(label, rect, line):
        placements[label.key], leaders[label.key] = rect, line
        text_index.put(label.key, rect)
        line_index.put(label.key, _line_bounds(line), line)
    # Other centers are obstacles, not their entire crater interiors. Treating
    # every large, eroded catalogue crater as a forbidden disk can leave no
    # caption space around an otherwise prominent crater on a whole-Moon map.
    marker_radius = {label.key: min(label.radius, max(4., label.height*.45)) for label in labels}
    markers = {label.key: (label.anchor[0]-marker_radius[label.key], label.anchor[1]-marker_radius[label.key],
                            2*marker_radius[label.key], 2*marker_radius[label.key]) for label in labels}
    fixed = {label.key for label in labels if label.fixed is not None}
    protected = {label.key for label in labels if label.important or label.force} | fixed
    for key in protected:
        marker_index.put(key, markers[key])
    for label in labels:
        if label.fixed is not None:
            rect = (*label.fixed, label.width, label.height)
            place(label, rect, leader_segment(label.anchor, rect, outline=label.outline))

    def best_position(label, *, extended=False):
        candidates = []
        for rect in candidate_boxes(label, gap, extended=extended):
            x, y, w, h = rect
            if x < gap or y < gap or x+w > width-gap or y+h > height-gap:
                continue
            line = leader_segment(label.anchor, rect, outline=label.outline)
            lx, ly, lw, lh = _line_bounds(line)
            # All intersections and the capped clearance reward lie inside
            # this neighborhood. Distant captions cannot affect the decision.
            left, top = min(x, lx), min(y, ly)
            neighborhood = (left, top, max(x+w, lx+lw)-left, max(y+h, ly+lh)-top)
            other_rects = text_index.near(neighborhood, 3*gap, label.key)
            other_lines = line_index.near(neighborhood, 3*gap, label.key)
            nearby_markers = marker_index.near(neighborhood, 3*gap)
            own_marker = markers.get(label.key)
            other_markers = [marker for marker in nearby_markers if marker is not own_marker]
            # Captions cannot hide their own center, or other selected centers.
            if not label.force:
                # Most rejected positions hit a nearby caption or marker.
                # Stop on the first collision instead of counting every
                # conflict and performing expensive line tests unnecessarily.
                if any(rect_intersects(rect, old, gap*.65) for old in other_rects):
                    continue
                if any(rect_intersects(rect, old, gap*.3) for old in nearby_markers):
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
                conflicts += sum(rect_intersects(rect, old, gap*.3) for old in nearby_markers)
                conflicts += sum(segment_hits_rect(line, old, 1) for old in other_rects)
                conflicts += sum(segment_hits_rect(old, rect, 1) for old in other_lines)
                conflicts += sum(segments_cross(line, old) for old in other_lines)
                conflicts += sum(segment_hits_rect(line, old) for old in other_markers)
            # Prefer locally separated captions. Limit the
            # reward so empty corners do not pull labels away from their objects.
            clearance = min((rect_distance(rect, old) for old in other_rects+other_markers), default=3*gap)
            length = math.hypot(line[2]-line[0], line[3]-line[1])
            score = conflicts*1e6 + .45*length - .8*min(clearance, 3*gap)
            candidates.append((score, rect, line))
        if candidates:
            return min(candidates, key=lambda item: item[0])
        # Only important captions pay for a wider search, and only after all
        # compact positions fail. Collision and image-boundary rules remain.
        if label.important and not extended:
            return best_position(label, extended=True)
        return None

    pending = [label for label in labels if label.key not in fixed]
    def arrange_group(group):
        # One placement pass and at most two local relocation passes.
        for _ in range(3):
            moved = False
            for label in group:
                previous = placements.get(label.key)
                best = best_position(label)
                if best:
                    _, rect, line = best
                    place(label, rect, line)
                    moved |= previous != placements[label.key]
            if not moved:
                break

    arrange_group([label for label in pending if label.key in protected])

    # Ordinary centers cannot veto an important caption before they even
    # have a label. Once important captions are placed, an ordinary center
    # underneath their text or leader is omitted together with its label.
    def center_conflicts(marker):
        return (any(rect_intersects(marker, rect, gap*.3) for rect in text_index.near(marker, gap*.3)) or
                any(segment_hits_rect(line, marker) for line in line_index.near(marker)))

    ordinary = []
    for label in pending:
        if label.key not in protected and not center_conflicts(markers[label.key]):
            marker_index.put(label.key, markers[label.key])
            ordinary.append(label)
    arrange_group(ordinary)
    if max_labels is not None:
        # Protect only the centers of actual annotations when filling gaps.
        # The initial pool still gets joint relocation; later candidates may
        # not displace higher-priority captions or obscure their centers.
        for key in set(markers)-placements.keys():
            marker_index.remove(key)
            del markers[key]
        def refill(candidates):
            for label in candidates:
                if len(placements) >= max_labels:
                    break
                radius = min(label.radius, max(4., label.height*.45))
                marker = (label.anchor[0]-radius, label.anchor[1]-radius, 2*radius, 2*radius)
                if not label.force and (
                    any(rect_intersects(marker, rect, gap*.3) for rect in text_index.near(marker, gap*.3)) or
                    any(segment_hits_rect(line, marker) for line in line_index.near(marker))
                ):
                    continue
                markers[label.key] = marker
                marker_index.put(label.key, marker)
                best = best_position(label)
                if best:
                    _, rect, line = best
                    place(label, rect, line)
                else:
                    markers.pop(label.key)
                    marker_index.remove(label.key)
        refill(label for label in pending if label.key not in placements)
        def remaining():
            while len(placements) < max_labels:
                label = next(reserve, None)
                if label is None:
                    break
                labels.append(label)
                yield label
        refill(remaining())
    omitted = {label.key for label in labels if label.key not in placements}
    return placements, omitted

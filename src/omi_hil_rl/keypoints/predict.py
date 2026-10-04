"""Conservative local baseline. Scores are heuristics, never probabilities.

Contour candidates have no physical identities. Named predictions require an explicit
same-episode/view reference. No fitting, propagation, learned weights or network calls.
"""
from __future__ import annotations

import platform
import time
import cv2
import numpy as np
from .storage import NAMES, now

ALGORITHM = 'reference-patches-v1'
cv2.setNumThreads(1)


def quad_valid(points):
    points = np.asarray(points, np.float32)
    return points.shape == (4, 2) and np.isfinite(points).all() and bool(cv2.isContourConvex(points)) and abs(cv2.contourArea(points)) >= 4


def candidates(gray):
    """Propose geometric boundaries, not a USB semantic detector."""
    edges = cv2.Canny(gray, 45, 110)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, .035 * perimeter, True).reshape(-1, 2)
        if not quad_valid(polygon):
            continue
        area = abs(cv2.contourArea(polygon))
        if not 12 <= area <= gray.size * .4:
            continue
        # Only cyclic vertex indices; deliberately no TL/TR physical identity assignment.
        if any(np.linalg.norm(np.mean(polygon, axis=0) - np.mean(c['vertices'], axis=0)) < 3 for c in found):
            continue
        found.append({'vertices': polygon.tolist(), 'area': float(area),
                      'reason': 'Closed convex image boundary; target identity and inner rim unconfirmed'})
    return sorted(found, key=lambda item: item['area'], reverse=True)[:16]


class ReferencePredictor:
    """Backend interface: predict(image, view, target_config, reference_image=None)."""
    def predict(self, image, view, target_config=None, reference_image=None):
        started = time.perf_counter()
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError('Expected original uint8 RGB')
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        proposal = {'algorithm': ALGORITHM, 'algorithm_version': '1', 'created_at': now(),
                    'view': view, 'target_config': target_config, 'score_semantics': 'uncalibrated normalized template similarity',
                    'candidates': candidates(gray), 'points': [], 'timing_scope': 'RGB array through preprocessing and detection; excludes file IO/HTTP/UI',
                    'environment': {'opencv': cv2.__version__, 'threads': 1, 'machine': platform.machine(), 'image_shape': list(image.shape)},
                    'warnings': ['Geometric consistency does not establish visibility or physical identity.']}
        configured = target_config and target_config.get('confirmed') and reference_image is not None
        ref_gray = cv2.cvtColor(reference_image, cv2.COLOR_RGB2GRAY) if configured else None
        reference = {p['name']: p for p in target_config['reference_points']} if configured else {}
        for name in NAMES:
            result = {'name': name, 'x': None, 'y': None, 'status': 'uncertain', 'score': None, 'alternatives': [], 'reason': 'Reference/physical identity not confirmed'}
            if configured:
                point = reference[name]
                if point['status'] != 'visible':
                    result['reason'] = 'No visible reference for this physical point; no hidden-point inference'
                else:
                    result = self._match(name, point, ref_gray, gray, target_config)
            proposal['points'].append(result)
        socket = proposal['points'][2:]
        if all(p['status'] == 'visible' for p in socket):
            polygon = [[socket[i]['x'], socket[i]['y']] for i in (0, 1, 3, 2)]
            if not quad_valid(polygon):
                for point in socket:
                    point.update(x=None, y=None, status='uncertain', reason='Rejected: crossed/degenerate socket geometry')
        a, b = proposal['points'][:2]
        if a['status'] == b['status'] == 'visible' and np.hypot(a['x'] - b['x'], a['y'] - b['y']) < 2:
            for point in (a, b):
                point.update(x=None, y=None, status='uncertain', reason='Rejected: coincident plug tips')
        proposal['elapsed_ms'] = (time.perf_counter() - started) * 1000
        return proposal

    @staticmethod
    def _match(name, point, reference, image, config):
        x, y = point['x'], point['y']
        height, width = image.shape
        radius, movement = 5, 18
        left, top = max(0, round(x) - radius), max(0, round(y) - radius)
        right, bottom = min(width, round(x) + radius + 1), min(height, round(y) + radius + 1)
        patch = reference[top:bottom, left:right]
        result = {'name': name, 'x': None, 'y': None, 'status': 'uncertain', 'score': None, 'alternatives': [], 'reason': ''}
        if patch.size < 36 or np.std(patch) < 8:
            result['reason'] = 'Weak/border reference patch; select a clearer reference'
            return result
        roi = config['plug_roi' if name.startswith('plug') else 'socket_roi']
        # Restrict local search to configured target neighborhood; no cross-episode tracking.
        sx, sy = max(0, left - movement, int(roi[0]) - radius - movement), max(0, top - movement, int(roi[1]) - radius - movement)
        ex, ey = min(width, right + movement, int(roi[2]) + radius + movement + 1), min(height, bottom + movement, int(roi[3]) + radius + movement + 1)
        search = image[sy:ey, sx:ex]
        if min(search.shape) < 1 or search.shape[0] < patch.shape[0] or search.shape[1] < patch.shape[1]:
            result['reason'] = 'Search area outside image'
            return result
        scores = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
        _, best, _, pos = cv2.minMaxLoc(scores)
        px, py = pos
        px_image, py_image = sx + px + (x - left), sy + py + (y - top)
        runner = scores.copy()
        runner[max(0, py-3):py+4, max(0, px-3):px+4] = -1
        _, second, _, second_pos = cv2.minMaxLoc(runner)
        result.update(score=float(best), alternatives=[{'x': float(px_image), 'y': float(py_image), 'score': float(best)},
                      {'x': float(sx + second_pos[0] + x - left), 'y': float(sy + second_pos[1] + y - top), 'score': float(second)}])
        if best < .82:
            result['reason'] = 'Rejected: weak local appearance match (<0.82); visibility unknown'
        elif best - second < .06:
            result['reason'] = 'Rejected: ambiguous local matches (margin <0.06)'
        elif not (0 <= px_image < width and 0 <= py_image < height):
            result['reason'] = 'Rejected: outside original image'
        else:
            result.update(x=float(px_image), y=float(py_image), status='visible', reason='Local reference match; human visibility/identity review required')
        return result

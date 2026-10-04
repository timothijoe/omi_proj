"""Validated JSON master store, optimistic concurrency and masked NPZ export."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from datetime import datetime, timezone

import numpy as np
from PIL import Image

NAMES = ('plug_tip_left', 'plug_tip_right', 'socket_top_left', 'socket_top_right',
         'socket_bottom_left', 'socket_bottom_right')
STATUSES = {'unlabeled', 'visible', 'occluded', 'out_of_frame', 'uncertain'}
SCHEMA = 'omi.six_keypoints.v1'
IMMUTABLE = ('image_id', 'image_path', 'width', 'height', 'view', 'episode_id', 'split', 'image_sha256')


class Conflict(ValueError):
    pass


def browser_safe(value):
    """Preserve nanosecond timestamps across JavaScript's 53-bit number boundary."""
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {k: browser_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [browser_safe(v) for v in value]
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def invalid(value):
        raise ValueError(f'Non-finite JSON: {value}')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), parse_constant=invalid, object_pairs_hook=unique)


def atomic_json(path, value):
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()
    fd, name = tempfile.mkstemp(prefix='.annotations-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def image_path(root, record):
    relative = Path(record['image_path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Image path must be relative and contained in project')
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Image path escapes project')
    return path


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def validate_point(point, width, height):
    if point.get('status') not in STATUSES or point.get('review_status') not in {'unreviewed', 'reviewed'}:
        raise ValueError('Unknown point status/review status')
    x, y = point.get('x'), point.get('y')
    if point['status'] == 'visible':
        if not (finite(x) and finite(y) and 0 <= x <= width - 1 and 0 <= y <= height - 1):
            raise ValueError('Visible point must have finite original-image coordinates')
    elif x is not None or y is not None:
        raise ValueError('Non-visible ground truth must use null coordinates')
    if point['status'] == 'unlabeled' and point['review_status'] != 'unreviewed':
        raise ValueError('Unlabeled point cannot be reviewed')


def validate(document, root=None):
    if document.get('schema_version') != SCHEMA or document.get('keypoint_names') != list(NAMES):
        raise ValueError('Unknown schema or keypoint names/order')
    if not isinstance(document.get('keypoint_definition_version'), str):
        raise ValueError('Missing definition version')
    if type(document.get('revision', 0)) is not int or document.get('revision', 0) < 0:
        raise ValueError('Invalid document revision')
    seen, paths = set(), set()
    for record in document['images']:
        for key in IMMUTABLE:
            if key not in record:
                raise ValueError(f'Missing {key}')
        identifier = record['image_id']
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('Duplicate/invalid image id')
        seen.add(identifier)
        if record['image_path'] in paths:
            raise ValueError('Duplicate image path')
        paths.add(record['image_path'])
        width, height = record['width'], record['height']
        if type(width) is not int or type(height) is not int or not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError('Invalid image size')
        if record['view'] not in {'external', 'wrist'} or record['split'] not in {'training', 'validation', 'test', 'development'}:
            raise ValueError('Unknown view/split')
        if not isinstance(record['episode_id'], str) or not record['episode_id']:
            raise ValueError('Invalid episode')
        if type(record.get('revision')) is not int or record['revision'] < 0:
            raise ValueError('Invalid image revision')
        points = record.get('keypoints', [])
        if [p.get('name') for p in points] != list(NAMES):
            raise ValueError('Exactly six named points in canonical order required')
        for point in points:
            validate_point(point, width, height)
        if record.get('review_status') not in {'unreviewed', 'reviewed'}:
            raise ValueError('Invalid image review status')
        if type(record.get('target_definition_confirmed')) is not bool:
            raise ValueError('Invalid target confirmation flag')
        if record['review_status'] == 'reviewed':
            if not record['target_definition_confirmed'] or not record.get('target_id'):
                raise ValueError('Target definition must be confirmed before image review')
            if any(p['review_status'] != 'reviewed' or p['status'] == 'unlabeled' for p in points):
                raise ValueError('All six points must be explicitly reviewed')
        image_path(root or '.', record)
        if root is not None:
            path = image_path(root, record)
            if digest(path) != record['image_sha256']:
                raise ValueError(f'Image hash mismatch: {identifier}')
            with Image.open(path) as image:
                image.load()
                if image.mode != 'RGB' or image.size != (width, height):
                    raise ValueError(f'Image shape/mode mismatch: {identifier}')
        if not isinstance(record.get('proposals'), list):
            raise ValueError('Proposals must be separate ordered runs')
        for run in record['proposals']:
            if not isinstance(run.get('algorithm'), str) or not isinstance(run.get('algorithm_version'), str):
                raise ValueError('Proposal algorithm/version required')
            if [p.get('name') for p in run.get('points', [])] != list(NAMES):
                raise ValueError('Proposal requires six named points')
            for point in run['points']:
                if point.get('status') not in {'visible', 'uncertain'}:
                    raise ValueError('Algorithm cannot invent physical occlusion labels')
                validate_point({**point, 'review_status': 'unreviewed'}, width, height)
                if point.get('score') is not None and not finite(point['score']):
                    raise ValueError('Invalid proposal score')
                for alternative in point.get('alternatives', []):
                    if not all(finite(alternative.get(k)) for k in ('x', 'y', 'score')):
                        raise ValueError('Invalid alternative')
            for candidate in run.get('candidates', []):
                if len(candidate.get('vertices', [])) != 4:
                    raise ValueError('Invalid candidate polygon')
                for x, y in candidate['vertices']:
                    if not (finite(x) and finite(y) and 0 <= x < width and 0 <= y < height):
                        raise ValueError('Invalid candidate coordinate')
        if any(t not in {'wrong_target', 'identity_swap', 'weak_edges', 'occlusion'} for t in record.get('failure_tags', [])):
            raise ValueError('Unknown failure tag')
    configs = document.get('target_configs', {})
    if not isinstance(configs, dict):
        raise ValueError('Invalid target configs')
    records = {r['image_id']: r for r in document['images']}
    for key, config in configs.items():
        ref = records.get(config.get('reference_image_id'))
        if ref is None or key != config_key(ref):
            raise ValueError('Reference must be in the same episode/view')
        if not isinstance(config.get('target_id'), str) or not config['target_id'].strip():
            raise ValueError('Target identity required')
        if type(config.get('confirmed')) is not bool or not isinstance(config.get('definition_note'), str):
            raise ValueError('Invalid definition confirmation')
        if config['confirmed'] and not config['definition_note'].strip():
            raise ValueError('Describe the physical corners before confirming')
        for roi in ('socket_roi', 'plug_roi'):
            box = config.get(roi)
            if not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box):
                raise ValueError('Two explicit reference ROIs required')
            x0, y0, x1, y1 = box
            if not (0 <= x0 < x1 <= ref['width'] - 1 and 0 <= y0 < y1 <= ref['height'] - 1):
                raise ValueError('Invalid reference ROI')
        points = config.get('reference_points', [])
        if [p.get('name') for p in points] != list(NAMES):
            raise ValueError('Reference requires six explicit point states')
        for point in points:
            validate_point(point, ref['width'], ref['height'])
        if config['confirmed'] and any(p['status'] == 'unlabeled' for p in points):
            raise ValueError('Resolve all reference point states before confirmation')
        for point in points:
            if point['status'] == 'visible':
                box = config['plug_roi' if point['name'].startswith('plug') else 'socket_roi']
                if not (box[0] <= point['x'] <= box[2] and box[1] <= point['y'] <= box[3]):
                    raise ValueError('Reference point outside its object ROI')
    for record in document['images']:
        if record['target_definition_confirmed']:
            config = configs.get(config_key(record))
            if not config or not config['confirmed'] or config['target_id'] != record['target_id']:
                raise ValueError('Image target confirmation disagrees with reference config')
    # Enforce JSON-serializable, finite values throughout proposals/audit as well.
    json.dumps(document, allow_nan=False)


def config_key(record):
    return json.dumps([record['episode_id'], record['view']], separators=(',', ':'))


def initialize(source, destination):
    """Copy verified input into a durable independent project; never overwrite."""
    source, destination = Path(source), Path(destination)
    doc = read_json(source / 'annotation_template.json')
    validate(doc, source)
    manifest = read_json(source / 'manifest.json')
    if manifest.get('schema_version') != 'omi.keypoint.examples.v1':
        raise ValueError('Unknown source manifest')
    entries = {r['image_id']: r for r in manifest['images']}
    if len(entries) != len(manifest['images']) or set(entries) != {r['image_id'] for r in doc['images']}:
        raise ValueError('Manifest/template image ids mismatch')
    for r in doc['images']:
        if any(entries[r['image_id']].get(k) != r[k] for k in IMMUTABLE):
            raise ValueError('Manifest/template metadata mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    for record in doc['images']:
        target = image_path(destination, record)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_path(source, record).read_bytes())
        record['provenance'] = entries[record['image_id']]
    doc.update(revision=0, target_configs={}, created_at=now(), audit=[])
    atomic_json(destination / 'manifest.json', manifest)
    atomic_json(destination / 'annotations.json', doc)
    return doc


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / 'annotations.json'
        self.lock = threading.RLock()
        self.writer = (self.root / '.writer.lock').open('a+')
        try:
            fcntl.flock(self.writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.read()
        except Exception:
            self.writer.close()
            raise

    def close(self):
        self.writer.close()

    def read(self):
        with self.lock:
            doc = read_json(self.path)
            validate(doc, self.root)
            return doc

    def commit(self, incoming, expected):
        with self.lock:
            old = self.read()
            if type(expected) is not int or expected != old['revision']:
                raise Conflict('Another window saved a newer revision; download draft before reload')
            doc = copy.deepcopy(incoming)
            for field in ('schema_version', 'keypoint_definition_version', 'keypoint_names', 'coordinate_convention'):
                if doc.get(field) != old.get(field):
                    raise ValueError('Definition/schema metadata is immutable within a project')
            if len(doc['images']) != len(old['images']):
                raise ValueError('Cannot add/remove images through editor')
            for previous, current in zip(old['images'], doc['images']):
                if any(previous[k] != current.get(k) for k in IMMUTABLE) or current.get('provenance') not in (previous.get('provenance'), browser_safe(previous.get('provenance'))):
                    raise ValueError('Image identity/provenance is immutable')
                current['provenance'] = copy.deepcopy(previous.get('provenance'))
                changed_points = current['keypoints'] != previous['keypoints']
                changed_config = doc.get('target_configs', {}).get(config_key(current)) != old.get('target_configs', {}).get(config_key(current))
                # A save containing edits cannot simultaneously certify the entire image.
                if changed_points or changed_config:
                    current['review_status'] = 'unreviewed'
                config = doc.get('target_configs', {}).get(config_key(current))
                current['target_definition_confirmed'] = bool(config and config.get('confirmed'))
                current['target_id'] = config.get('target_id') if config else None
                current['revision'] = previous['revision']
                if current != previous:
                    current['revision'] += 1
                    current['updated_at'] = now()
            doc['revision'] = old['revision'] + 1
            doc['updated_at'] = now()
            doc['audit'] = old.get('audit', []) + [{'revision': doc['revision'], 'at': doc['updated_at'],
                                                    'images': [r['image_id'] for r, p in zip(doc['images'], old['images']) if r != p]}]
            validate(doc, self.root)
            atomic_json(self.path, doc)
            return doc


def export_npz(doc):
    validate(doc)
    records = [r for r in doc['images'] if r['review_status'] == 'reviewed' and r['target_definition_confirmed']]
    points = np.zeros((len(records), 6, 2), np.float32)
    mask = np.zeros((len(records), 6), bool)
    for i, record in enumerate(records):
        for j, p in enumerate(record['keypoints']):
            if p['status'] == 'visible' and p['review_status'] == 'reviewed':
                points[i, j] = p['x'], p['y']
                mask[i, j] = True
    output = io.BytesIO()
    metadata = {'schema_version': 'omi.six_keypoints.training.v1', 'source_revision': doc.get('revision'),
                'keypoint_names': list(NAMES), 'keypoint_definition_version': doc['keypoint_definition_version'],
                'target_configs': doc.get('target_configs', {}),
                'images': [{k: r.get(k) for k in (*IMMUTABLE, 'revision', 'target_id', 'provenance')} for r in records],
                'skipped': [r['image_id'] for r in doc['images'] if r not in records]}
    np.savez_compressed(output, points=points, localization_mask=mask,
                        statuses=np.asarray([[p['status'] for p in r['keypoints']] for r in records], dtype='U16').reshape(-1, 6),
                        metadata_json=np.asarray(json.dumps(metadata, ensure_ascii=False)))
    return output.getvalue(), metadata

"""Synthetic coordinates below are test fixtures, never labels for real robot data."""
import copy
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from omi_hil_rl.keypoints.storage import (NAMES, Conflict, Store, atomic_json, config_key,
    digest, export_npz, initialize, read_json, validate)
from omi_hil_rl.keypoints.predict import ReferencePredictor, quad_valid
from omi_hil_rl.keypoints.app import predict_document
from omi_hil_rl.keypoints.evaluate import evaluate


@pytest.fixture
def project(tmp_path):
    source = tmp_path / 'source'
    (source / 'images').mkdir(parents=True)
    rng = np.random.default_rng(91)
    img = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
    Image.fromarray(img).save(source / 'images/one.png')
    record = {'image_id': 'one', 'image_path': 'images/one.png', 'width': 128, 'height': 128,
              'view': 'external', 'episode_id': 'synthetic', 'split': 'training',
              'image_sha256': digest(source / 'images/one.png'), 'revision': 0,
              'review_status': 'unreviewed', 'target_id': None, 'target_definition_confirmed': False,
              'keypoints': [dict(name=n, x=None, y=None, status='unlabeled', review_status='unreviewed', source=None) for n in NAMES],
              'proposals': []}
    doc = {'schema_version': 'omi.six_keypoints.v1', 'keypoint_definition_version': 'synthetic-v1',
           'coordinate_convention': 'pixel centers', 'keypoint_names': list(NAMES), 'images': [record]}
    atomic_json(source / 'annotation_template.json', doc)
    atomic_json(source / 'manifest.json', {'schema_version': 'omi.keypoint.examples.v1', 'images': [record]})
    dest = tmp_path / 'project'
    initialize(source, dest)
    return dest


def anchored(doc):
    record = doc['images'][0]
    positions = [(25, 70), (50, 70), (25, 25), (50, 25), (25, 45), (50, 45)]
    for point, (x, y) in zip(record['keypoints'], positions):
        point.update(x=x, y=y, status='visible', source='human', review_status='reviewed')
    config = {'target_id': 'synthetic-port', 'reference_image_id': 'one', 'confirmed': True,
              'definition_note': 'Synthetic fixture physical identity', 'reference_points': copy.deepcopy(record['keypoints']),
              'socket_roi': [15, 15, 60, 55], 'plug_roi': [15, 60, 60, 85]}
    doc['target_configs'] = {config_key(record): config}
    record.update(target_id='synthetic-port', target_definition_confirmed=True)
    return doc


def test_import_verified_and_refuses_overwrite(project):
    with pytest.raises(FileExistsError):
        initialize(project.parent / 'source', project)
    doc = read_json(project / 'annotations.json')
    assert doc['images'][0]['provenance']['image_id'] == 'one'
    validate(doc, project)


@pytest.mark.parametrize('mutation', ['nan', 'outside', 'nonvisible_coordinate', 'missing', 'duplicate_id', 'path', 'status', 'schema', 'review'])
def test_invalid_labels_rejected(project, mutation):
    doc = read_json(project / 'annotations.json')
    r = doc['images'][0]
    p = r['keypoints'][0]
    if mutation == 'nan': p.update(status='visible', x=float('nan'), y=1)
    if mutation == 'outside': p.update(status='visible', x=128, y=1)
    if mutation == 'nonvisible_coordinate': p.update(status='occluded', x=0, y=0)
    if mutation == 'missing': r['keypoints'].pop()
    if mutation == 'duplicate_id': doc['images'].append(copy.deepcopy(r))
    if mutation == 'path': r['image_path'] = '../secret.png'
    if mutation == 'status': p['status'] = 'guess'
    if mutation == 'schema': doc['schema_version'] = 'unknown'
    if mutation == 'review': r['review_status'] = 'reviewed'
    with pytest.raises(ValueError): validate(doc, project)


def test_hash_and_missing_images(project):
    path = project / 'images/one.png'
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash'): Store(project)
    path.unlink()
    with pytest.raises(FileNotFoundError): Store(project)


def test_conflict_single_writer_and_disk_corruption(project):
    store = Store(project)
    try:
        with pytest.raises(BlockingIOError): Store(project)
        old = store.read()
        store.commit(old, 0)
        with pytest.raises(Conflict): store.commit(old, 0)
        (project / 'annotations.json').write_text('{broken')
        with pytest.raises(ValueError): store.commit(old, 1)
        assert (project / 'annotations.json').read_text() == '{broken'
    finally: store.close()


def test_approval_invalidation_and_export(project):
    store = Store(project)
    try:
        doc = anchored(store.read())
        doc['images'][0]['keypoints'][1].update(x=None, y=None, status='occluded')
        saved = store.commit(doc, 0)
        assert saved['images'][0]['review_status'] == 'unreviewed'
        saved['images'][0]['review_status'] = 'reviewed'
        saved = store.commit(saved, saved['revision'])
        data, meta = export_npz(saved)
        with np.load(io.BytesIO(data), allow_pickle=False) as result:
            assert result['points'].shape == (1, 6, 2)
            assert not result['localization_mask'][0, 1]
            assert result['points'][0, 1].tolist() == [0, 0]
            assert result['statuses'][0, 1] == 'occluded'
        saved['images'][0]['keypoints'][0]['x'] += 1
        saved = store.commit(saved, saved['revision'])
        assert saved['images'][0]['review_status'] == 'unreviewed'
        data, report = export_npz(saved)
        assert report['skipped'] == ['one']
    finally: store.close()


def test_all_nonvisible_can_be_reviewed(project):
    doc = anchored(read_json(project / 'annotations.json'))
    r = doc['images'][0]
    for p in r['keypoints']: p.update(x=None, y=None, status='uncertain')
    r['review_status'] = 'reviewed'
    data, _ = export_npz(doc)
    with np.load(io.BytesIO(data), allow_pickle=False) as result:
        assert result['localization_mask'].shape == (1, 6)
        assert not result['localization_mask'].any()


def test_reference_scope_and_roi(project):
    doc = anchored(read_json(project / 'annotations.json'))
    config = next(iter(doc['target_configs'].values()))
    config['reference_image_id'] = 'not-in-project'
    with pytest.raises(ValueError, match='Reference'): validate(doc)
    config['reference_image_id'] = 'one'
    config['plug_roi'] = [0, 0, 2, 2]
    with pytest.raises(ValueError, match='outside'): validate(doc)


def test_prediction_translation_rejection_and_manual_preservation(project):
    store = Store(project)
    try:
        doc = anchored(store.read())
        image = np.asarray(Image.open(project / 'images/one.png'))
        config = next(iter(doc['target_configs'].values()))
        shifted = np.zeros_like(image)
        shifted[3:, 4:] = image[:-3, :-4]
        run = ReferencePredictor().predict(shifted, 'external', config, image)
        assert sum(p['status'] == 'visible' for p in run['points']) == 6
        for ref, out in zip(config['reference_points'], run['points']):
            assert out['x'] == pytest.approx(ref['x'] + 4)
            assert out['y'] == pytest.approx(ref['y'] + 3)
        blank = ReferencePredictor().predict(np.zeros_like(image), 'external', config, image)
        assert all(p['status'] == 'uncertain' and p['x'] is None for p in blank['points'])
        original = copy.deepcopy(doc['images'][0]['keypoints'])
        result = predict_document(store, doc)
        assert result['images'][0]['keypoints'] == original
        assert len(result['images'][0]['proposals']) == 1
        validate(result)
    finally: store.close()


def test_no_reference_never_invents_named_truth(project):
    image = np.asarray(Image.open(project / 'images/one.png'))
    run = ReferencePredictor().predict(image, 'external')
    assert len(run['points']) == 6
    assert all(p['status'] == 'uncertain' and p['x'] is None for p in run['points'])
    assert not quad_valid([[0,0], [10,10], [0,10], [10,0]])


def test_metrics_exclude_self_and_report_rejections(project):
    store = Store(project)
    try:
        doc = predict_document(store, anchored(store.read()))
        r = doc['images'][0]
        r['review_status'] = 'reviewed'
        assert evaluate(doc)['excluded_reference_self_matches'] == ['one']
        r['proposals'][-1]['reference_is_this_image'] = False
        r['proposals'][-1]['points'][0].update(x=None, y=None, status='uncertain')
        metrics = evaluate(doc)['groups']['training/external/plug_tip_left']
        assert metrics['rejected_visible_fraction'] == 1
        assert metrics['pck2_all_visible'] == 0
    finally: store.close()


def test_duplicate_json_and_nonfinite(project):
    path = project / 'bad.json'
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match='Duplicate'): read_json(path)
    path.write_text('{"a":NaN}')
    with pytest.raises(ValueError, match='Non-finite'): read_json(path)


def test_nanosecond_timestamp_browser_round_trip(project):
    from omi_hil_rl.keypoints.storage import browser_safe
    doc = read_json(project / 'annotations.json')
    timestamp = 1791035053029240832
    doc['images'][0]['provenance']['reference_ns'] = timestamp
    atomic_json(project / 'annotations.json', doc)
    store = Store(project)
    try:
        client = browser_safe(store.read())
        assert client['images'][0]['provenance']['reference_ns'] == str(timestamp)
        client['images'][0]['keypoints'][0].update(x=1.25, y=2.5, status='visible')
        saved = store.commit(client, 0)
        assert saved['images'][0]['provenance']['reference_ns'] == timestamp
        client = browser_safe(saved)
        client['images'][0]['provenance']['reference_ns'] = str(timestamp + 1)
        with pytest.raises(ValueError, match='immutable'): store.commit(client, 1)
    finally: store.close()


def test_http_local_token_and_export(project):
    from omi_hil_rl.keypoints.app import handler_for
    from http.server import ThreadingHTTPServer
    import threading
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    store = Store(project)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(store, 'test-token', 0))
    port = server.server_address[1]
    server.RequestHandlerClass = handler_for(store, 'test-token', port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{port}'
        response = json.load(urlopen(base + '/api/document'))
        doc = response['document']
        payload = json.dumps({'expected_revision': 0, 'document': doc}).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/save', data=payload))
        assert error.value.code == 403
        req = Request(base + '/api/save', data=payload, headers={'X-Annotation-Token': 'test-token'})
        assert json.load(urlopen(req))['revision'] == 1
        with pytest.raises(HTTPError) as error: urlopen(req)
        assert error.value.code == 409
        with np.load(io.BytesIO(urlopen(base + '/api/export/training').read()), allow_pickle=False) as arr:
            assert arr['points'].shape == (0, 6, 2)
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/document', headers={'Host': 'evil.example'}))
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.close()


def test_ambiguous_repeating_pattern_rejected():
    tile = np.random.default_rng(17).integers(0, 255, (8, 8, 3), dtype=np.uint8)
    image = np.tile(tile, (16, 16, 1))
    positions = [(24, 64), (48, 64), (24, 24), (48, 24), (24, 40), (48, 40)]
    points = [dict(name=n, x=x, y=y, status='visible', review_status='reviewed') for n,(x,y) in zip(NAMES,positions)]
    config = dict(confirmed=True, reference_points=points, socket_roi=[10,10,60,55], plug_roi=[10,55,60,80])
    run = ReferencePredictor().predict(image, 'external', config, image)
    assert all(p['status'] == 'uncertain' for p in run['points'])
    assert all('ambiguous' in p['reason'] for p in run['points'])

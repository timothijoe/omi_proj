"""python -m omi_hil_rl.keypoints.app {init,serve,predict,export,evaluate}."""
from __future__ import annotations

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse, parse_qs

import numpy as np
from PIL import Image
from .predict import ReferencePredictor
from .storage import Conflict, Store, atomic_json, browser_safe, config_key, export_npz, image_path, initialize

STATIC = Path(__file__).parent / 'static'


def predict_document(store, doc, ids=None):
    result = copy.deepcopy(doc)
    records = {r['image_id']: r for r in result['images']}
    if ids is not None and not set(ids) <= records.keys():
        raise ValueError('Unknown image id')
    predictor = ReferencePredictor()
    for record in result['images']:
        if ids is not None and record['image_id'] not in ids:
            continue
        config = result['target_configs'].get(config_key(record))
        reference = None
        if config and config['confirmed']:
            ref = records[config['reference_image_id']]
            if ref['split'] != record['split'] or ref['episode_id'] != record['episode_id'] or ref['view'] != record['view']:
                raise ValueError('Reference scope/split mismatch')
            reference = np.asarray(Image.open(image_path(store.root, ref)).convert('RGB'))
        image = np.asarray(Image.open(image_path(store.root, record)).convert('RGB'))
        proposal = predictor.predict(image, record['view'], config, reference)
        proposal['reference_is_this_image'] = bool(config and config['reference_image_id'] == record['image_id'])
        record['proposals'].append(proposal)
    return result


def summary(doc):
    runs = [r['proposals'][-1] for r in doc['images'] if r['proposals']]
    points = [p for run in runs for p in run['points']]
    return {'images': len(doc['images']), 'predicted_images': len(runs),
            'geometric_candidates': sum(len(r['candidates']) for r in runs),
            'named_proposals': sum(p['status'] == 'visible' for p in points), 'total_points': len(points),
            'reviewed_images': sum(r['review_status'] == 'reviewed' for r in doc['images']),
            'mean_inference_ms': float(np.mean([r['elapsed_ms'] for r in runs])) if runs else None,
            'note': 'Candidate counts are not semantic accuracy. No truth until human confirmation.'}


def handler_for(store, token, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, mime='application/json', filename=None):
            if not isinstance(body, bytes):
                body = json.dumps(browser_safe(body), ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def permitted(self):
            host = self.headers.get('Host', '')
            return host in {f'127.0.0.1:{port}', f'localhost:{port}'}

        def do_GET(self):
            try:
                if not self.permitted():
                    return self.send(403, {'error': 'Local host required'})
                url = urlparse(self.path)
                if url.path == '/api/document':
                    return self.send(200, {'document': store.read(), 'token': token})
                if url.path == '/api/image':
                    identifier = parse_qs(url.query).get('id', [''])[0]
                    record = next((r for r in store.read()['images'] if r['image_id'] == identifier), None)
                    if record is None:
                        return self.send(404, {'error': 'Unknown image'})
                    return self.send(200, image_path(store.root, record).read_bytes(), 'image/png')
                if url.path == '/api/export/draft':
                    return self.send(200, store.read(), filename='annotations.json')
                if url.path == '/api/export/training':
                    data, _ = export_npz(store.read())
                    return self.send(200, data, 'application/octet-stream', 'six_keypoints.npz')
                if url.path == '/api/export/report':
                    _, report = export_npz(store.read())
                    return self.send(200, report)
                files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'),
                         '/style.css': ('style.css', 'text/css')}
                if url.path in files:
                    name, mime = files[url.path]
                    return self.send(200, (STATIC / name).read_bytes(), mime)
                self.send(404, {'error': 'Not found'})
            except (ValueError, KeyError, OSError, TypeError) as error:
                self.send(422, {'error': str(error)})

        def do_POST(self):
            try:
                if not self.permitted() or self.headers.get('X-Annotation-Token') != token:
                    return self.send(403, {'error': 'Missing local session token'})
                origin = self.headers.get('Origin')
                if origin and origin not in {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}:
                    return self.send(403, {'error': 'Cross-origin request rejected'})
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16_000_000:
                    return self.send(413, {'error': 'Invalid request size'})
                payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
                if self.path == '/api/save':
                    return self.send(200, store.commit(payload['document'], payload['expected_revision']))
                if self.path == '/api/predict':
                    with store.lock:
                        doc = store.read()
                        if payload['expected_revision'] != doc['revision']:
                            raise Conflict('Revision conflict; save/reload before prediction')
                        result = predict_document(store, doc, payload.get('ids'))
                        return self.send(200, store.commit(result, doc['revision']))
                self.send(404, {'error': 'Not found'})
            except Conflict as error:
                self.send(409, {'error': str(error)})
            except (ValueError, KeyError, OSError, TypeError) as error:
                self.send(422, {'error': str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Local six-keypoint proposals and human review (no robot control)')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--source', type=Path, required=True)
    init.add_argument('--project', type=Path, required=True)
    for name in ('serve', 'predict', 'export', 'evaluate', 'import-draft', 'report'):
        p = sub.add_parser(name)
        p.add_argument('--project', type=Path, required=True)
        if name == 'serve':
            p.add_argument('--port', type=int, default=8765)
        elif name == 'predict':
            p.add_argument('--image-id', action='append')
        elif name == 'import-draft':
            p.add_argument('--input', type=Path, required=True)
        elif name == 'export':
            p.add_argument('--output', type=Path, required=True)
        else:
            p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'init':
        print(json.dumps(summary(initialize(args.source, args.project)), indent=2))
        return
    store = Store(args.project)
    try:
        if args.command == 'serve':
            server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(store, secrets.token_urlsafe(32), args.port))
            print(f'Open http://127.0.0.1:{args.port} · project {store.root}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.command == 'predict':
            doc = store.read()
            result = store.commit(predict_document(store, doc, args.image_id), doc['revision'])
            print(json.dumps(summary(result), indent=2))
        elif args.command == 'report':
            from .diagnostics import render_report
            render_report(store, args.output)
        elif args.command == 'import-draft':
            from .storage import read_json
            old = store.read()
            incoming = read_json(args.input)
            saved = store.commit(incoming, old['revision'])
            print(json.dumps(summary(saved), indent=2))
        elif args.command == 'export':
            data, report = export_npz(store.read())
            with args.output.open('xb') as output:
                output.write(data)
            print(json.dumps(report, indent=2))
        else:
            from .evaluate import evaluate
            if args.output.exists():
                raise ValueError('Evaluation output already exists')
            atomic_json(args.output, evaluate(store.read()))
    finally:
        store.close()


if __name__ == '__main__':
    main()

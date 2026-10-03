"""Experimental new mesh / legacy kinematic chain review, never a controller."""
import argparse
import copy
import itertools
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np

from .robot_replay_3d import build_urdf, PREFIX
from .stand_urdf_review import prepare as prepare_stand


def vertices(path):
    data = Path(path).read_bytes()
    count = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError('Expected binary STL')
    dtype = np.dtype([('normal', '<f4', (3,)), ('v', '<f4', (3, 3)), ('attr', '<u2')])
    points = np.unique(np.frombuffer(data, dtype=dtype, offset=84)['v'].reshape(-1, 3), axis=0)
    return points.astype(float)


def fit_mesh(source, target):
    """Rigid visual registration only, not robot calibration. No scale/reflection."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(7)
    source = source[rng.choice(len(source), min(1800, len(source)), replace=False)]
    tree = cKDTree(target)
    center = (target.max(0) + target.min(0)) / 2
    source_center = (source.max(0) + source.min(0)) / 2
    candidates = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            rot = np.eye(3)[list(perm)] * np.array(signs)[:, None]
            if np.linalg.det(rot) < 0:
                continue
            pos = center - rot @ source_center
            for _ in range(35):
                placed = source @ rot.T + pos
                distances, ids = tree.query(placed)
                good = distances <= np.quantile(distances, .85)
                a, b = placed[good], target[ids[good]]
                ac, bc = a.mean(0), b.mean(0)
                u, _, vt = np.linalg.svd((a-ac).T @ (b-bc))
                step = vt.T @ u.T
                if np.linalg.det(step) < 0:
                    vt[-1] *= -1
                    step = vt.T @ u.T
                shift = bc - step @ ac
                rot, pos = step @ rot, step @ pos + shift
                if np.linalg.norm(shift) < 1e-8 and np.linalg.norm(step-np.eye(3)) < 1e-7:
                    break
            placed = source @ rot.T + pos
            d = tree.query(placed)[0]
            reverse = cKDTree(placed).query(target[::max(1, len(target)//1800)])[0]
            score = float(max(np.quantile(d, .90), np.quantile(reverse, .90)))
            candidates.append((score, rot, pos))
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def combine(legacy, stand, registrations):
    """Keep EVERY legacy joint unchanged, including its root mounting transform."""
    result = copy.deepcopy(legacy)
    for side in ('left', 'right'):
        for i in range(1, 8):
            name = PREFIX + f'{side}_link{i}'
            item = registrations[name]
            if not item['accepted']:
                continue
            link = result.find(f"link[@name='{name}']")
            for visual in link.findall('visual'):
                link.remove(visual)
            visual = copy.deepcopy(stand.find(f"link[@name='{name}']/visual"))
            visual.find('origin').set('xyz', ' '.join(map(str, item['xyz'])))
            visual.find('origin').set('rpy', ' '.join(map(str, item['rpy'])))
            link.append(visual)
    # Stand mesh only: align heights, not the arm kinematics. Mount width is
    # intentionally NOT hidden by stretching the support or moving joints.
    base = result.find(f"link[@name='{PREFIX}robot_base']")
    visual = copy.deepcopy(stand.find(f"link[@name='{PREFIX}robot_base']/visual"))
    visual.find('origin').set('xyz', '0 0 -0.90205')
    visual.find('origin').set('rpy', '0 0 0')
    # Retain legacy shoulder mounting pieces but remove the old central stand.
    base.remove(base.findall('visual')[0])
    base.append(visual)
    return result


def prepare(archive, scene, output, template):
    from scipy.spatial.transform import Rotation
    from urllib.parse import unquote, urlparse
    import yaml
    dest = prepare_stand(archive, output, template)
    stand = ET.parse(dest/'arms.urdf').getroot()
    legacy_text, _, _ = build_urdf(scene)
    legacy = ET.fromstring(legacy_text)
    registrations = {}
    for side in ('left', 'right'):
        for i in range(1, 8):
            name = PREFIX + f'{side}_link{i}'
            old_visual = legacy.find(f"link[@name='{name}']/visual")
            new_visual = stand.find(f"link[@name='{name}']/visual")
            def mesh(v):
                return vertices(unquote(urlparse(v.find('geometry/mesh').get('filename')).path))
            old, new = mesh(old_visual), mesh(new_visual)
            origin = old_visual.find('origin')
            old = old @ Rotation.from_euler('xyz', np.fromstring(origin.get('rpy'), sep=' ')).as_matrix().T
            old += np.fromstring(origin.get('xyz'), sep=' ')
            score, rot, pos = fit_mesh(new, old)
            # Conservative fallback: distinct terminal tooling is not a rigid
            # re-export of the legacy bare wrist, even if a fit appears close.
            accepted = score < .008 and i != 7
            registrations[name] = dict(accepted=accepted, p90_bidirectional_m=score,
                xyz=pos.tolist(), rpy=Rotation.from_matrix(rot).as_euler('xyz').tolist(),
                reason='visual fit only' if accepted else 'keep legacy: different geometry or uncertain fit')
            print(f'{side}{i}: {score*1000:.2f} mm, '+('new mesh' if accepted else 'legacy fallback'), file=sys.stderr, flush=True)
    result = combine(legacy, stand, registrations)
    ET.indent(result)
    text = ET.tostring(result, encoding='unicode')
    (dest/'hybrid.urdf').write_text(text)
    (dest/'publisher.yaml').write_text(yaml.safe_dump({'/**': {'ros__parameters': {
        'robot_description': text, 'publish_frequency': 30., 'use_sim_time': False}}}))
    (dest/'hybrid_report.json').write_text(json.dumps(dict(
        legacy_scene=str(Path(scene).resolve()), registrations=registrations,
        unchanged_joint_chain=True, stand_visual_offset=[0,0,-.90205],
        limitations='Visual fit not calibration; support mounts may differ; L7 legacy retained; no TCP'), indent=2))
    config = yaml.safe_load((dest/'review.rviz').read_text())
    manager = config['Visualization Manager']
    manager['Displays'][1]['Name'] = 'HYBRID: legacy chain + registered new meshes'
    manager['Views']['Current']['Focal Point']['Z'] = .25
    manager['Views']['Current']['Distance'] = 3.2
    manager['Displays'][0]['Enabled'] = False  # legacy world puts stand foot below z=0
    (dest/'review.rviz').write_text(yaml.safe_dump(config))
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive'); p.add_argument('scene'); p.add_argument('output'); p.add_argument('template')
    args = p.parse_args()
    print(prepare(args.archive, args.scene, args.output, args.template))


if __name__ == '__main__':
    main()

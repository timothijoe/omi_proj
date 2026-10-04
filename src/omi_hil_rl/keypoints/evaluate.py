"""Descriptive audited-label metrics; never claims independent generalization."""
import numpy as np
from .storage import NAMES, validate


def evaluate(doc):
    validate(doc)
    buckets = {}
    skipped = []
    self_references = []
    corrections = []
    for r in doc['images']:
        if r['review_status'] != 'reviewed' or not r['proposals']:
            skipped.append(r['image_id'])
            continue
        run = r['proposals'][-1]
        if run.get('reference_is_this_image'):
            self_references.append(r['image_id'])
            continue
        edits = 0
        for point, guess in zip(r['keypoints'], run['points']):
            group = f"{r['split']}/{r['view']}/{point['name']}"
            b = buckets.setdefault(group, {'visible': 0, 'accepted_visible': 0, 'rejected_visible': 0,
                                           'known_nonvisible': 0, 'false_visible': 0,
                                           'uncertain_truth': 0, 'errors_px': []})
            accepted = guess['status'] == 'visible'
            if point['status'] == 'visible':
                b['visible'] += 1
                if accepted:
                    error = float(np.hypot(point['x'] - guess['x'], point['y'] - guess['y']))
                    b['accepted_visible'] += 1
                    b['errors_px'].append(error)
                    edits += error > .01
                else:
                    b['rejected_visible'] += 1
                    edits += 1
            elif point['status'] in {'occluded', 'out_of_frame'}:
                b['known_nonvisible'] += 1
                b['false_visible'] += accepted
                edits += accepted
            else:
                b['uncertain_truth'] += 1  # Do not conflate uncertainty with occlusion.
        corrections.append({'image_id': r['image_id'], 'points_different_from_proposal': int(edits),
                            'review_elapsed_seconds': r.get('review_elapsed_seconds'),
                            'manual_failure_tags': r.get('failure_tags', [])})
    for b in buckets.values():
        errors = b.pop('errors_px')
        b.update(median_px=float(np.median(errors)) if errors else None,
                 p90_px=float(np.percentile(errors, 90)) if errors else None,
                 pck2_accepted=float(np.mean(np.asarray(errors) <= 2)) if errors else None,
                 pck4_accepted=float(np.mean(np.asarray(errors) <= 4)) if errors else None,
                 pck2_all_visible=sum(e <= 2 for e in errors) / b['visible'] if b['visible'] else None,
                 pck4_all_visible=sum(e <= 4 for e in errors) / b['visible'] if b['visible'] else None,
                 accepted_visible_coverage=b['accepted_visible'] / b['visible'] if b['visible'] else None,
                 rejected_visible_fraction=b['rejected_visible'] / b['visible'] if b['visible'] else None,
                 false_visible_fraction=b['false_visible'] / b['known_nonvisible'] if b['known_nonvisible'] else None)
    return {'schema_version': 'omi.six_keypoints.evaluation.v1', 'source_revision': doc.get('revision'),
            'groups': buckets, 'corrections': corrections, 'skipped_unreviewed_or_no_proposal': skipped,
            'excluded_reference_self_matches': self_references,
            'target_wrong_images': sum('wrong_target' in r.get('failure_tags', []) for r in doc['images'] if r['review_status'] == 'reviewed'),
            'identity_swap_images': sum('identity_swap' in r.get('failure_tags', []) for r in doc['images'] if r['review_status'] == 'reviewed'),
            'limitations': ['No ground truth metrics without reviewed labels.',
                           'Uncertain human labels excluded from known-occlusion denominator.',
                           'Same-image reference matches excluded. Same-episode reference use is not unseen-episode generalization.',
                           'Correction counts compare final labels with latest proposals, not recorded manual clicks.',
                           'Review time is interface elapsed time, not a controlled from-scratch speed comparison.',
                           'Wrong-target/identity-swap counts require explicit human failure tags; zero is not proof of absence.']}

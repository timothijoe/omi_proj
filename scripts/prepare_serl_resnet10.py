#!/usr/bin/env python3
"""Export the official SERL checkpoint and reference Flax outputs.

Run in a separate environment with jax==0.4.35 and flax==0.10.2.
The pickle is accepted only if it matches the audited public release digest.
Then use serl_resnet10.convert_npz in the normal PyTorch environment.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import pickle
import subprocess
import sys

import numpy as np

EXPECTED_SHA256 = '175745d43d30233eb01b5369465d1c24c11b8ee71ccb734cc1c1bca13e07f57b'
URL = 'https://github.com/rail-berkeley/serl/releases/download/resnet10/resnet10_params.pkl'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--reference-repo', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    a = p.parse_args()
    digest = hashlib.sha256(a.source.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError('Official checkpoint hash mismatch')
    sys.path.insert(0, str(a.reference_repo/'serl_launcher'))
    module = importlib.import_module('serl_launcher.vision.resnet_v1')
    with a.source.open('rb') as f:
        params = pickle.load(f)
    def flatten(tree, prefix=''):
        for key, value in tree.items():
            if isinstance(value, dict):
                yield from flatten(value, prefix+key+'/')
            else:
                yield prefix+key, np.asarray(value)
    np.savez(a.source.parent/'flax_arrays.npz', **dict(flatten(params)))
    with np.load(a.dataset/'samples.npz', allow_pickle=False) as z:
        real = np.concatenate([z['rgb'][[0, len(z['rgb'])//2, -1]],
                               z['wrist_rgb'][[0, len(z['rgb'])//2, -1]]])
    rng = np.random.default_rng(42)
    images = np.concatenate([real, rng.integers(0, 256, (2, 3, 128, 128), dtype=np.uint8),
                             np.zeros((1, 3, 128, 128), np.uint8),
                             np.full((1, 3, 128, 128), 255, np.uint8)])
    model = module.resnetv1_configs['resnetv1-10-frozen']()
    output = np.asarray(model.apply({'params': params}, images.transpose(0, 2, 3, 1), train=False))
    np.savez(a.source.parent/'flax_reference.npz', rgb=images, feature=output.transpose(0, 3, 1, 2))
    provenance = dict(url=URL, source_sha256=digest,
                      reference_commit=subprocess.check_output(['git', '-C', str(a.reference_repo), 'rev-parse', 'HEAD'], text=True).strip(),
                      source_code_sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
                      reference_inputs='six actual train RGB frames plus two random, black, white',
                      reference_shape=list(output.shape), image_pretraining='ImageNet-1K',
                      unused_checkpoint_parameters='output_head classifier',
                      normalization='RGB /255; mean .485,.456,.406; std .229,.224,.225')
    (a.source.parent/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    main()

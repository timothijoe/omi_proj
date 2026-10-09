"""Lossless, episode-local single frames shared by recorded history windows.

References describe the actual input, not the last ten actions (which can skip
observations). Frame content hashes also preserve resets, gaps and padding.
Legacy archives with embedded observation arrays remain readable.
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re

import numpy as np


VERSION = 'omi-observation-frames-v1'
HISTORY = 10


def frame_digest(frame):
    digest = hashlib.sha256()
    for key in sorted(frame):
        value = np.asarray(frame[key])
        header = json.dumps([key, value.dtype.str, list(value.shape)], separators=(',', ':')).encode()
        digest.update(len(header).to_bytes(8, 'big'))
        digest.update(header)
        digest.update(value.tobytes(order='C'))
    return digest.hexdigest()


def save_archive(path, metadata, arrays):
    """Publish only complete archives; frame files precede their references."""
    from .exchange import sync_directory
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream, metadata=np.asarray(json.dumps(metadata)), **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    sync_directory(path.parent)


class FrameWriter:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.written = set()

    def encode(self, observation, archive_directory):
        """Return a window descriptor, or None for non-history legacy inputs."""
        if (not observation or 'history_mask' not in observation or
                np.asarray(observation['history_mask']).shape != (HISTORY,) or
                any(np.asarray(v).ndim < 1 or np.asarray(v).shape[0] != HISTORY
                    for v in observation.values())):
            return None
        ids = []
        for slot in range(HISTORY):
            frame = {key: np.asarray(value[slot]) for key, value in observation.items()}
            ident = frame_digest(frame)
            if ident not in self.written:
                save_archive(self.directory / (ident + '.npz'), {}, frame)
                self.written.add(ident)
            ids.append(ident)
        return dict(version=VERSION, directory=os.path.relpath(self.directory, archive_directory), frames=ids)

    def write(self, path, metadata, observation):
        path = Path(path)
        reference = self.encode(observation, path.parent)
        metadata = dict(metadata)
        arrays = {}
        if reference is not None:
            metadata['observation_storage'] = {'observation': reference}
        elif observation is not None:
            arrays = {'observation__' + k: v for k, v in observation.items()}
        save_archive(path, metadata, arrays)


class ObservationReader:
    def __init__(self, cache_size=64):
        self.cache_size = cache_size
        self.cache = OrderedDict()

    def _frame(self, directory, ident):
        if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
            raise ValueError('invalid observation frame id')
        path = (directory / (ident + '.npz')).resolve()
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        with np.load(path, allow_pickle=False) as archive:
            frame = {key: archive[key].copy() for key in archive.files if key != 'metadata'}
        if frame_digest(frame) != ident:
            raise ValueError('observation frame hash mismatch: ' + str(path))
        if self.cache_size:
            self.cache[path] = frame
            while len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return frame

    def observation(self, archive, metadata, path, name='observation'):
        references = metadata.get('observation_storage', {})
        prefix = name + '__'
        embedded = {k[len(prefix):]: archive[k].copy() for k in archive.files if k.startswith(prefix)}
        if name not in references:
            return embedded
        if embedded:
            raise ValueError('ambiguous embedded and referenced observation')
        reference = references[name]
        if reference.get('version') != VERSION or len(reference.get('frames', [])) != HISTORY:
            raise ValueError('unsupported observation frame storage')
        directory = Path(path).parent / reference['directory']
        frames = [self._frame(directory, ident) for ident in reference['frames']]
        if not frames[0] or any(set(f) != set(frames[0]) for f in frames):
            raise ValueError('observation frame keys mismatch')
        for key in frames[0]:
            first = frames[0][key]
            if any(f[key].shape != first.shape or f[key].dtype != first.dtype for f in frames):
                raise ValueError('observation frame shape/dtype mismatch: ' + key)
        # np.stack owns its arrays; consumers cannot mutate the cached frames.
        return {key: np.stack([f[key] for f in frames]) for key in frames[0]}

    def read(self, path, name='observation'):
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive['metadata']))
            observation = self.observation(archive, metadata, path, name)
        return metadata, observation

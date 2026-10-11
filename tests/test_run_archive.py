import fcntl
import io
import json
from pathlib import Path
import tarfile

import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exchange import atomic_json, atomic_torch
from omi_hil_rl.hil.learner import run_learner
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.hil.prepare_bc_rl import prepare
from omi_hil_rl.hil.run_archive import pack, restore, verify, probe_buffer, digest
from test_cached_replay import episode


@pytest.fixture
def stopped(tmp_path):
    torch.set_num_threads(1)
    config=HILConfig(review='auto');contract=config.replay_contract()
    bc=tmp_path/'bc';bc.mkdir()
    state=SAC({'encoder':'synthetic-test'},contract).checkpoint();state['training_method']='behavior_cloning'
    atomic_torch(bc/'actor.pt',state);atomic_json(bc/'config.json',contract['config'])
    run=tmp_path/'run'
    prepare(bc,run,weights_only=True,replay_backend='cached',warmup=2,
            cache_target_gib=.06,cache_limit_gib=.12)
    episode(run,'new',contract,sources=('human','policy','human','policy'))
    run_learner(run,config,batch_size=2,updates=4,wait_seconds=10.)
    atomic_json(run/'async_state.json',dict(phase='CLOSED',error=None))
    (run/'actor.lock').touch()
    return run


def test_archive_restore_rebuild_and_resume_without_original_directory(stopped,tmp_path):
    before={str(p.relative_to(stopped)):digest(p) for p in stopped.rglob('*') if p.is_file()}
    bundle=tmp_path/'bundle'
    assert pack(stopped,bundle)['status']=='verified'
    assert verify(bundle)['run']['files']>=len(before)
    restored=tmp_path/'restored'
    restore(bundle,restored)
    assert all(digest(restored/n)==sha for n,sha in before.items())
    # The old working path must not be an implicit dependency after relocation.
    stopped.rename(tmp_path/'original_unavailable')
    result=probe_buffer(restored,cache_gib=.06,limit_gib=.12,batch_size=2)
    assert result['checkpoint_version']==4
    assert result['cache']['catalog_online']==4 and result['cache']['catalog_seed']==0
    assert result['streams']['demonstration']==2
    assert result['original_checkpoints_and_catalog_unchanged']
    config=HILConfig(**json.loads((restored/'config.json').read_text()))
    assert run_learner(restored,config,batch_size=2,updates=2,wait_seconds=10.)['updates']==6
    # Restoration/training cannot modify the archived copy.
    verify(bundle)
    with pytest.raises(ValueError,match='NEW local directory'):
        restore(bundle,restored)


def test_archive_rejects_active_run_and_nonempty_target(stopped,tmp_path):
    with (stopped/'actor.lock').open('rb') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(RuntimeError,match='in use'):
            pack(stopped,tmp_path/'blocked')
    assert not (tmp_path/'blocked').exists()
    target=tmp_path/'occupied';target.mkdir();(target/'keep').write_text('keep')
    with pytest.raises(ValueError,match='empty'):
        pack(stopped,target)
    assert (target/'keep').read_text()=='keep'


def test_archive_corruption_and_unsafe_member_never_publish_restore(stopped,tmp_path):
    bundle=tmp_path/'bundle';pack(stopped,bundle)
    with (bundle/'run.tar').open('r+b') as f:
        f.seek(7000);value=f.read(1);f.seek(7000);f.write(bytes([value[0]^1]))
    with pytest.raises((ValueError,tarfile.TarError)):
        restore(bundle,tmp_path/'corrupt')
    assert not (tmp_path/'corrupt').exists()
    with tarfile.open(bundle/'run.tar','w') as tar:
        entry=tarfile.TarInfo('run/../../escaped');entry.size=1
        tar.addfile(entry,io.BytesIO(b'x'))
    with pytest.raises(ValueError,match='unsafe archive path'):
        restore(bundle,tmp_path/'unsafe')
    assert not (tmp_path/'escaped').exists() and not (tmp_path/'unsafe').exists()

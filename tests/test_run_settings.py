import argparse
import json
from pathlib import Path

import pytest

from omi_hil_rl.hil.run_settings import parse_settings, SCHEMA, ROOT


def parser():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    p.add_argument('--episode-seconds',type=float,default=20)
    p.add_argument('--train-tactile-encoder',action='store_true')
    p.add_argument('--execute',action='store_true')
    return p


def settings(tmp_path,values):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps(dict(schema=SCHEMA,prepare=values,online={})))
    return path


@pytest.mark.parametrize('flag',['--settings','--parameter'])
def test_explicit_config_load_and_cli_override(tmp_path,capsys,flag):
    path=settings(tmp_path,dict(run='local/test',device='cuda',episode_seconds=30,train_tactile_encoder=True))
    a=parse_settings(parser(),'prepare',[flag,str(path),'--episode-seconds','45'])
    assert a.run==ROOT/'local/test' and a.device=='cuda' and a.episode_seconds==45 and a.train_tactile_encoder
    assert not a.execute and a._settings_info['sha256']
    assert 'SETTINGS_LOADED' in capsys.readouterr().out


@pytest.mark.parametrize('value',[{'typo':1},{'device':'invalid'},{'episode_seconds':'invalid'},
                                 {'train_tactile_encoder':'yes'},{'execute':True}])
def test_invalid_or_execution_settings_rejected(tmp_path,value):
    path=settings(tmp_path,dict(run='local/test',**value))
    with pytest.raises(SystemExit) as exc:parse_settings(parser(),'prepare',['--settings',str(path)])
    assert exc.value.code==2


def test_print_settings_exits_before_execution(tmp_path):
    path=settings(tmp_path,dict(run='local/test',device='cuda'))
    with pytest.raises(SystemExit) as exc:
        parse_settings(parser(),'prepare',['--settings',str(path),'--print-settings','--execute'])
    assert exc.value.code==0
    assert not (tmp_path/'local/test').exists()


def test_old_cli_still_works_without_settings():
    a=parse_settings(parser(),'prepare',['--run','old_run'])
    assert a.run==Path('old_run') and a.device=='cpu' and a._settings_info is None


def test_settings_preserve_virtual_environment_interpreter_symlink(tmp_path):
    target=tmp_path/'system-python';target.touch()
    venv=tmp_path/'venv-python';venv.symlink_to(target)
    p=parser();p.add_argument('--learner-python',type=Path)
    path=settings(tmp_path,dict(run='local/test',learner_python=str(venv)))
    a=parse_settings(p,'prepare',['--parameter',str(path)])
    assert a.learner_python==venv and a.learner_python!=target


def test_online_settings_refuse_changed_persistent_parameters(tmp_path):
    run=tmp_path/'run';run.mkdir()
    (run/'bc_initialization.json').write_text(json.dumps(dict(episode_seconds=20)))
    (run/'async_session.json').write_text('{}')
    (run/'config.json').write_text(json.dumps(dict(episode_seconds=20)))
    path=tmp_path/'bad.json'
    path.write_text(json.dumps(dict(schema=SCHEMA,prepare=dict(episode_seconds=30),online=dict(run=str(run)))))
    with pytest.raises(SystemExit) as exc:
        parse_settings(parser(),'online',['--settings',str(path),'--print-settings'])
    assert exc.value.code==2


def test_boolean_optional_choice_and_append_list(tmp_path):
    p=parser()
    p.add_argument('--image-augmentation',action=argparse.BooleanOptionalAction,default=True)
    p.add_argument('--recorded-source',action='append',type=Path,default=[])
    path=settings(tmp_path,dict(run='local/test',image_augmentation=False,recorded_source=[]))
    a=parse_settings(p,'prepare',['--settings',str(path),'--image-augmentation'])
    assert a.image_augmentation and a.recorded_source==[]


def test_environment_is_explicit_and_print_mode_does_not_apply_it(tmp_path,monkeypatch):
    from omi_hil_rl.hil import run_settings
    path=settings(tmp_path,{})
    data=json.loads(path.read_text());data['online']={'run':str(tmp_path)}
    data['environment']={'ROS_DOMAIN_ID':'13','ROS_LOCALHOST_ONLY':'0','ROS_AUTOMATIC_DISCOVERY_RANGE':'SUBNET'}
    path.write_text(json.dumps(data))
    monkeypatch.setattr(run_settings,'verify_session_settings',lambda args:None)
    monkeypatch.setenv('ROS_DOMAIN_ID','231')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY','1')
    monkeypatch.setenv('ROS_AUTOMATIC_DISCOVERY_RANGE','LOCALHOST')
    with pytest.raises(SystemExit):
        parse_settings(parser(),'online',['--settings',str(path),'--print-settings'])
    assert run_settings.os.environ['ROS_DOMAIN_ID']=='231'
    parse_settings(parser(),'online',['--settings',str(path)])
    assert run_settings.os.environ['ROS_DOMAIN_ID']=='13'


def test_selected_profile_preserves_legacy_rl_settings_except_requested_changes():
    data=json.loads((ROOT/'configs/spacepilot_bc6148_online_rl.json').read_text())
    a,b=data['prepare'],data['online']
    assert a['weights_only'] and a['recorded_source']==[]
    assert a['critic_learning_rate']==3e-4 and a['discount']==.98 and a['target_tau']==.005
    assert a['critic_actor_ratio']==2 and a['image_augmentation']
    assert a['critic_warmup_updates']==1000 and a['bc_weight']==10 and a['actor_learning_rate']==1e-5
    assert a['episode_seconds']==30 and a['max_total_episodes']==300
    assert a['train_tactile_encoder'] and not a['train_fusion_layer']
    assert b['arbitration_mode']=='after-inference' and b['reload_every_episodes']==10
    assert b['publish_every']==50 and b['max_updates_per_transition']==1
    assert b['batch_size']==64 and b['min_online']==b['min_demo']==100
    assert b['exploration_noise_std']==.05 and b['exploration_noise_clip']==.15
    assert not b['no_gripper'] and b['no_tag_follow']  # Gripper enabled; marker temporarily disabled by user.

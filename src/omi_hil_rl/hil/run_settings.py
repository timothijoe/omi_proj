"""Explicit JSON settings for preparation and online CLI; command-line overrides win."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = 'omi-online-rl-settings-v1'
ENVIRONMENT_KEYS = {'ROS_DOMAIN_ID','ROS_LOCALHOST_ONLY','ROS_AUTOMATIC_DISCOVERY_RANGE'}


def _json_safe(value):
    if isinstance(value,Path):
        return str(value)
    if isinstance(value,dict):
        return {k:_json_safe(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):
        return [_json_safe(v) for v in value]
    return value


def parse_settings(parser, section, argv=None):
    parser.add_argument('--parameter', '--settings', dest='settings', type=Path,
                        help='Load explicit prepare/online JSON settings (--settings is an alias)')
    parser.add_argument('--print-settings', action='store_true', help='Print effective settings and exit without hardware or training')
    argv = list(sys.argv[1:] if argv is None else argv)
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument('--parameter', '--settings', dest='settings', type=Path)
    selected, _ = probe.parse_known_args(argv)
    tokens, document, info = [], None, None
    if selected.settings is not None:
        try:
            path = selected.settings.resolve()
            blob = path.read_bytes()
            document = json.loads(blob)
            if (not isinstance(document, dict) or document.get('schema') != SCHEMA or
                    set(document) - {'schema','description','prepare','online','environment'} or
                    not all(isinstance(document.get(key), dict) for key in ('prepare','online'))):
                raise ValueError('Expected schema '+SCHEMA+' with prepare/online objects')
            environment = document.get('environment', {})
            if (not isinstance(environment, dict) or set(environment)-ENVIRONMENT_KEYS or
                    any(not isinstance(v,str) for v in environment.values())):
                raise ValueError('Invalid ROS environment settings')
            actions = {a.dest:a for a in parser._actions}
            for key,value in document[section].items():
                if key not in actions or key in ('help','settings','print_settings','execute','enable_policy','probe_only','initialize_from'):
                    raise ValueError('Unknown or CLI-only setting: '+key)
                action = actions[key]
                option = action.option_strings[0]
                if isinstance(action, (argparse._StoreTrueAction,argparse._StoreFalseAction,argparse.BooleanOptionalAction)):
                    if type(value) is not bool:
                        raise ValueError(key+' must be boolean')
                    parser.set_defaults(**{key:value})
                    continue
                values = value if isinstance(action,argparse._AppendAction) else [value]
                if not isinstance(values,list):
                    raise ValueError(key+' must be a list')
                for item in values:
                    if item is None or isinstance(item,(dict,list,bool)):
                        raise ValueError('Invalid scalar setting: '+key)
                    if action.type is Path:
                        # Resolving a venv's python symlink loses pyvenv.cfg and
                        # silently selects the system environment for the learner.
                        item = (os.path.abspath(ROOT/str(item)) if key == 'learner_python'
                                else str((ROOT/str(item)).resolve()))
                    tokens.append(option+'='+str(item))
            info = dict(path=str(path),sha256=hashlib.sha256(blob).hexdigest(),section=section)
        except (OSError,ValueError,TypeError) as exc:
            parser.error(str(exc))
    args = parser.parse_args(tokens+argv)
    args._settings_document = document
    args._settings_info = info
    args._settings_effective = _json_safe({k:v for k,v in vars(args).items() if not k.startswith('_')})
    if info is not None or args.print_settings:
        effective = {k:(str(v) if isinstance(v,Path) else v) for k,v in vars(args).items()
                     if not k.startswith('_')}
        print('SETTINGS_LOADED: '+json.dumps(dict(source=info,effective=effective,
              environment=document.get('environment',{}) if document else {}),ensure_ascii=False,default=str),flush=True)
        if section == 'online' and document is not None:
            print('SESSION_SETTINGS_EXPECTED: '+json.dumps(document['prepare'],ensure_ascii=False),flush=True)
            try:
                verify_session_settings(args)
            except ValueError as exc:
                parser.error(str(exc))
    if args.print_settings:
        parser.exit()
    if document is not None and section == 'online':
        os.environ.update(document.get('environment',{}))
    return args


def verify_session_settings(args):
    """Persistent setup values cannot be changed by editing an online CLI file."""
    document = getattr(args,'_settings_document',None)
    if document is None:
        return
    folder = Path(args.run)
    try:
        report = json.loads((folder/'bc_initialization.json').read_text())
        session = json.loads((folder/'async_session.json').read_text())
        config = json.loads((folder/'config.json').read_text())
    except (OSError,ValueError) as exc:
        raise ValueError('Settings require an initialized BC RL run: '+str(folder)) from exc
    expected = document['prepare']
    fields = ('critic_warmup_updates','bc_weight','actor_learning_rate','encoder_learning_rate',
              'train_tactile_encoder','train_fusion_layer','episode_seconds','max_total_episodes','weights_only',
              'critic_learning_rate','discount','target_tau','critic_actor_ratio','image_augmentation')
    for key in fields:
        if key in expected and report.get(key) != expected[key]:
            raise ValueError(f'Settings/session mismatch: {key}; prepare a NEW matching run, do not edit old checkpoints')
    for key in ('episode_seconds','max_total_episodes'):
        actual = config.get(key) if key=='episode_seconds' else session.get(key)
        if key in expected and actual != expected[key]:
            raise ValueError('Settings/session mismatch: '+key)
    if 'bc_run' in expected and Path(session['seed']).resolve() != (ROOT/expected['bc_run']).resolve():
        raise ValueError('Settings/session mismatch: BC source directory')
    if expected.get('replay_backend') == 'cached' and session.get('replay_backend') != 'omi-cached-dual-replay-v1':
        raise ValueError('Settings/session mismatch: replay backend')
    if 'cache_target_gib' in expected or 'cache_limit_gib' in expected:
        replay = json.loads((folder/'replay/manifest.json').read_text())
        for key,stored in (('cache_target_gib','cache_bytes'),('cache_limit_gib','memory_limit_bytes')):
            if key in expected and int(expected[key]*2**30) != replay[stored]:
                raise ValueError('Settings/session mismatch: '+key)
    print('SESSION_SETTINGS_VERIFIED: '+json.dumps(dict(run=str(folder.resolve()),
          episode_seconds=config['episode_seconds'],max_total_episodes=session.get('max_total_episodes'),
          train_tactile_encoder=report.get('train_tactile_encoder',False),
          train_fusion_layer=report.get('train_fusion_layer',False),
          visual_encoder_frozen=report.get('visual_encoder_frozen', True),
          weights_only=report.get('weights_only'), initial_demo_samples=report.get('samples'),
          control_mode=session.get('control_mode'), training_data_policy=session.get('training_data_policy'),
          encoder_learning_rate=report.get('encoder_learning_rate'),
          critic_warmup_updates=report['critic_warmup_updates']),ensure_ascii=False),flush=True)


def save_settings_snapshot(args, stage):
    if getattr(args,'_settings_info',None) is None:
        return
    from .exchange import atomic_json
    atomic_json(Path(args.run)/('settings_'+stage+'.json'), dict(
        source=args._settings_info, document=args._settings_document,
        effective=args._settings_effective,
        episodes_this_start=getattr(args,'episodes',None)))

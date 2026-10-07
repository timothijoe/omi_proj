"""Replay one successful episode through the policy route; never infer or learn."""
import argparse
import json
from pathlib import Path
import signal
import time
import uuid

import numpy as np

from .config import HILConfig
from omi_hil_rl.real.gamepad_control import wire_action


def load_actions(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'ready.json').read_text())
    if not manifest.get('keep') or not manifest.get('episode_success'):
        raise ValueError('requires a kept, success-labelled episode')
    config = HILConfig(**manifest['contract']['config'])
    if config.replay_contract() != manifest['contract'] or config.eef_reference != 'raw':
        raise ValueError('unsupported action/observation contract')
    rows, pose = [], None
    for i in range(manifest['count']):
        with np.load(directory/f'{i:06d}.npz', allow_pickle=False) as data:
            meta = json.loads(str(data['metadata']))
            action = data['executed_action'].copy()
            if i == 0:
                pose = data['observation__state'][-1, 7:14].copy()
        if meta['step'] != i or meta['episode'] != manifest['episode']:
            raise ValueError('episode/step mismatch')
        physical = config.physical_action(action)
        audit = meta['command_audit']
        receipt = audit['receipt']
        wire = wire_action(physical, config.sdk_convention)
        if (not receipt.get('accepted') or not receipt.get('finished') or
                receipt.get('arm') != 'A' or receipt.get('delta_frame') != 'base' or
                receipt.get('control_mode') != 'velocity_hold' or
                not np.isclose(receipt.get('nominal_duration_s', 0), 1/config.hz) or
                not np.allclose(wire, audit['wire_action'], atol=1e-5, rtol=0) or
                not np.allclose(wire, receipt['wire_action'], atol=1e-5, rtol=0) or
                not np.allclose(physical, audit['command_trace']['action_m_rad'], atol=1e-8, rtol=0)):
            raise ValueError(f'action/receipt conversion mismatch at step {i}')
        rows.append(dict(step=i, normalized=action.tolist(), physical=physical.tolist(),
                         wire=wire, send_ns=audit['command_send_ns'], source=meta['action_source']))
    if not rows or not (meta['terminated'] or meta['truncated']):
        raise ValueError('empty or incomplete episode')
    gaps = np.diff([r['send_ns'] for r in rows])/1e9
    if np.any(gaps <= 0) or np.any(gaps > .25):
        raise ValueError('nonmonotonic or >250ms source command gap; inspect before replay')
    if pose.shape != (7,) or not np.isfinite(pose).all():
        raise ValueError('invalid starting pose')
    return manifest, config, rows, pose


def check_pose(transport, expected):
    sample = transport.runtime.latest.get('eef', {})
    now = transport.node.get_clock().now().nanoseconds
    if not sample.get('accepted') or not 0 <= now-sample['receive_ns'] < 100_000_000:
        raise ValueError('fresh EEF feedback required')
    actual = np.asarray(sample['raw_eef_xyz_xyzw'])
    if (actual.shape != (7,) or not np.isfinite(actual).all() or
            np.linalg.norm(actual[3:]) < .99 or np.linalg.norm(expected[3:]) < .99):
        raise ValueError('invalid EEF pose')
    distance = np.linalg.norm(actual[:3]-expected[:3])*1000
    cosine = abs(np.dot(actual[3:], expected[3:]))/(np.linalg.norm(actual[3:])*np.linalg.norm(expected[3:]))
    angle = np.degrees(2*np.arccos(np.clip(cosine, 0, 1)))
    print(f'REPLAY_START_POSE: distance_mm={distance:.3f} angle_deg={angle:.3f}', flush=True)
    if distance > 10 or angle > 5:
        raise ValueError('starting pose differs by >10mm or >5deg; manually reset, no automatic motion')


def play(transport, config, rows, pose, emit):
    """Preserve source send intervals; never catch up with command bursts."""
    transport.wait_start()
    transport._pump()
    check_pose(transport, pose)
    # Verify policy route with a zero command before any replay movement.
    transport.last_owner = 'policy'
    ident = 'hil:'+uuid.uuid4().hex
    transport._publish(np.zeros(6), ident)
    until = time.monotonic()+1
    while ident not in transport.receipts:
        transport._pump()
        if (not transport.connected or transport.pad.buttons.get(311, False) or
                transport.events & {'success', 'manual_stop'} or time.monotonic() >= until):
            return 'handshake_cancelled_or_timeout'
    receipt = transport.receipts[ident]
    if (not receipt.get('accepted') or receipt.get('action_source') != 'policy' or
            receipt.get('control_mode') != 'velocity_hold' or receipt.get('arm') != 'A' or
            receipt.get('delta_frame') != 'base' or
            not np.isclose(receipt.get('nominal_duration_s', 0), 1/config.hz) or
            receipt.get('wire_action') != [0.]*6):
        raise ValueError('policy receiver handshake mismatch')
    check_pose(transport, pose)
    pending, acknowledged = {}, set()
    start = time.monotonic()
    for row in rows:
        due = start+(row['send_ns']-rows[0]['send_ns'])/1e9
        while True:
            transport._pump()
            if not transport.connected:
                return 'gamepad_disconnected'
            if transport.pad.buttons.get(311, False):
                return 'RB_cancelled_replay'
            if transport.events & {'success', 'manual_stop'}:
                return 'operator_stop'
            now = time.monotonic()
            for cid, sent in pending.items():
                ack = transport.receipts.get(cid)
                if ack is not None:
                    if not ack.get('accepted') and ack.get('status') != 'queue_replaced':
                        raise RuntimeError('receiver rejected replay: '+str(ack))
                    acknowledged.add(cid)
                elif cid not in acknowledged and now-sent > 1:
                    raise RuntimeError('receiver feedback absent for 1s')
            if now >= due:
                break
        if now-due > .05:
            return 'schedule_late_over_50ms_no_catchup'
        # Same conversion entry as NN policy, not manual mapping or raw wire playback.
        action = config.physical_action(row['normalized'])
        cid = 'hil:'+uuid.uuid4().hex
        transport.last_owner = 'policy'
        wire = transport._publish(action, cid)
        pending[cid] = now
        emit(dict(step=row['step'], normalized=row['normalized'], wire=wire,
                  command_id=cid, elapsed_s=now-start, lateness_ms=(now-due)*1000))
    # Source terminal action is held for one nominal period, then stopped.
    until = time.monotonic()+1/config.hz
    while time.monotonic() < until:
        transport._pump()
        if not transport.connected or transport.pad.buttons.get(311, False) or transport.events & {'success', 'manual_stop'}:
            break
    return 'sequence_finished_not_task_success'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episode', type=Path, required=True)
    p.add_argument('--policy-run', type=Path, default=Path('local/bc_episodes/bc_ready_20261007_01'))
    p.add_argument('--execute', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--gamepad', default='/dev/input/js0')
    p.add_argument('--rgb-max-age-ms', type=float, default=500.)
    p.add_argument('--log-buttons', action='store_true')
    args = p.parse_args()
    manifest, config, rows, pose = load_actions(args.episode)
    target = json.loads((args.policy_run/'config.json').read_text())
    if HILConfig(**target).replay_contract() != config.replay_contract():
        p.error('source episode differs from current policy contract')
    print('RECORDED_ACTION_REPLAY: '+json.dumps(dict(episode=manifest['episode'],
        success_label=True, steps=len(rows), neural_network=False, learner=False,
        action_contract=manifest['contract']['action_contract'], start_pose=pose.tolist(),
        timing='original send intervals; final hold=one nominal period')), flush=True)
    if not args.execute:
        for row in rows:
            print(json.dumps(row))
        print('INSPECT_ONLY: no ROS publishers; use --execute for robot replay')
        return
    if args.output is None:
        p.error('--execute requires a new --output directory')
    args.output.mkdir(parents=True, exist_ok=False)
    from .alternating import make_transport
    from .exchange import atomic_json
    atomic_json(args.output/'source.json', dict(path=str(args.episode.resolve()), manifest=manifest, rows=rows))
    recipe = json.loads((args.policy_run/'recipe.json').read_text())
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    old = signal.signal(signal.SIGTERM, interrupt)
    transport = None
    try:
        transport = make_transport(config, recipe, args)
        transport.allow_manual_reset = True
        with (args.output/'commands.jsonl').open('w', buffering=1) as log:
            def emit(value):
                log.write(json.dumps(value)+'\n')
                print('REPLAY: '+json.dumps(value), flush=True)
            try:
                reason = play(transport, config, rows, pose, emit)
            finally:
                transport.stop()
        print('REPLAY_STOP: '+reason+'; RB manual reset available; Ctrl+C exits', flush=True)
        atomic_json(args.output/'result.json', dict(reason=reason, training_ready=False))
        # Never resume the old sequence after manual intervention; restart explicitly.
        while True:
            transport.idle_tick()
            time.sleep(.005)
    except KeyboardInterrupt:
        print('REPLAY_CLOSED: interrupted', flush=True)
    finally:
        try:
            if transport is not None:
                transport.close()
        finally:
            signal.signal(signal.SIGTERM, old)


if __name__ == '__main__':
    main()

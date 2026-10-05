"""Launch real observations -> policy -> RB arbiter; preview by default."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import sys

from .gamepad_gripper import add_gripper_arguments, calibration_from_args
from .gamepad_home import add_home_arguments
from .eef_reference import EEF_REFERENCES, reference_offset
from .policy_action import POLICY_FRAME, SDK_CONVENTION


def commands(args):
    # Preview candidates use a private name, never an existing live arbiter input.
    topic='/omi/policy/candidate' if args.execute else f'/omi/policy/preview_{os.getpid()}/candidate'
    common=['--speed-mm-s',str(args.speed_mm_s),'--rotation-deg-s',str(args.rotation_deg_s)]
    actor=[sys.executable,'-m','omi_hil_rl.training.stack_shadow','--checkpoint',str(args.checkpoint),
        '--output',str(args.output/'policy'),'--duration',str(args.duration),'--device',args.device,
        '--header-mode','strict','--eef-reference',args.eef_reference,'--publish-candidates',
        '--candidate-topic',topic,'--policy-scale',str(args.policy_scale),*common]
    actor.extend(['--model-kind', getattr(args, 'model_kind', 'stack')])
    expiry = getattr(args, 'candidate_expiry', 'on')
    actor.extend(['--candidate-expiry', expiry])
    arbiter=[sys.executable,'-m','omi_hil_rl.real.gamepad_node','--device',args.gamepad,
        '--policy-topic',topic,'--frame',POLICY_FRAME,'--output-convention',SDK_CONVENTION,
        '--policy-timeout','0.1','--log',str(args.output/'selected_actions.jsonl'),*common]
    arbiter.extend(['--candidate-expiry', expiry])
    if getattr(args, 'gripper_server', None):
        for key in ('server', 'sdk_root', 'calibration', 'close_speed', 'close_position', 'close_torque', 'open_position'):
            value = getattr(args, 'gripper_' + key)
            if value is not None:
                arbiter.extend(['--gripper-' + key.replace('_', '-'), str(value)])
    if args.execute:arbiter.append('--publish')
    arbiter.extend(['--home-button-code', str(getattr(args, 'home_button_code', 308))])
    return [arbiter,actor],topic


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--model-kind',choices=('stack','passive-wrench-bc'),default='stack')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--duration',type=float,default=60.)
    p.add_argument('--device',choices=('cuda','cpu'),default='cuda')
    p.add_argument('--gamepad',default='/dev/input/js0')
    p.add_argument('--eef-reference',choices=EEF_REFERENCES,required=True,
                   help='Choose raw EEF or explicit temporary bag-baseline-v1 observation translation')
    p.add_argument('--policy-scale',type=float,default=1.)
    p.add_argument('--speed-mm-s',type=float,default=10.)
    p.add_argument('--rotation-deg-s',type=float,default=10.)
    p.add_argument('--execute',action='store_true',help='Enable final robot output; without this all selected actions are preview only')
    p.add_argument('--candidate-expiry',choices=('on','off'),default='on',
                   help='off disables candidate age rejection, not RB priority or sensor freshness checks')
    add_gripper_arguments(p)
    add_home_arguments(p)
    args=p.parse_args()
    calibration_from_args(args, p)
    if not args.checkpoint.is_file():p.error('checkpoint missing')
    if args.model_kind == 'passive-wrench-bc':
        if args.eef_reference != 'raw':p.error('wrench BC was trained with raw EEF')
        from omi_hil_rl.training.wrench_live import load_wrench_policy
        load_wrench_policy(args.checkpoint, 'cpu')  # fail before starting the publishing arbiter
    if not all(math.isfinite(v) and v>0 for v in (args.duration,args.speed_mm_s,args.rotation_deg_s)):p.error('duration/speeds must be finite and positive')
    if not math.isfinite(args.policy_scale) or not 0<args.policy_scale<=1:p.error('policy scale must be in (0,1]')
    root=Path(os.environ['OMI_PROJECT_ROOT'])
    runtime=root/'local/policy_gamepad';runtime.mkdir(parents=True,exist_ok=True)
    with (runtime/('domain-'+os.environ.get('ROS_DOMAIN_ID','13')+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:p.error('policy/gamepad launcher already running in this domain')
        args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
        children,topic=commands(args)
        (args.output/'session.json').write_text(json.dumps(dict(
            execute=args.execute,candidate_topic=topic,command_topic='/omi/action/decision',
            candidate_expiry=args.candidate_expiry,
            manual_command_topic='/omi/action/manual_decision',tactile_guard_scope='receiver_policy_only_opt_in',
            policy_frame=POLICY_FRAME,sdk_output=SDK_CONVENTION,conversion_owner='arbiter after RB selection',
            eef_reference=args.eef_reference,eef_input_offset_base_m=reference_offset(args.eef_reference).tolist(),
            policy_scale=args.policy_scale,speed_mm_s=args.speed_mm_s,rotation_deg_s=args.rotation_deg_s,
            policy_limit_mode='independent_translation_rotvec_norm_scaling_after_policy_scale',
            receiver_user_confirmed=dict(arm='left',frame=0),
            assumptions=['SDK UserFrame aligned/identity','policy EEF and receiver SDK TCP denote same physical point',
                         'sdk-x-forward-z-left is the requested installation preset, not a measured calibration'],
            commands=children),indent=2)+'\n')
        print(('EXECUTE: robot output enabled' if args.execute else 'PREVIEW: no robot command publisher')+
              '; RB held=human, released=fresh policy, disconnected=paused; '+SDK_CONVENTION,flush=True)
        from omi_sensors.cli import supervise
        if args.candidate_expiry == 'off':
            print('WARNING: candidate expiry OFF; delayed candidates may execute once. RB priority and sensor ingress checks remain enabled.',flush=True)
        return supervise(children,dict(os.environ),None)


if __name__=='__main__':raise SystemExit(main())

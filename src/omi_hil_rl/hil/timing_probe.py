"""Read live sensors and infer, never create robot command publishers or a learner."""
import argparse
import json
import time
import math
from pathlib import Path

import torch

from .config import HILConfig
from .networks import load_actor
from .ros_transport import RosTransport
from .exchange import atomic_json
from .policy_pipeline import LatestPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--simulate-receipt-ms', type=float,
                        help='test background inference with simulated command completion; NO commands sent')
    args = parser.parse_args()
    if args.seconds <= 0 or args.output.exists():
        parser.error('positive duration and a new output path required')
    if args.simulate_receipt_ms is not None and (not math.isfinite(args.simulate_receipt_ms) or args.simulate_receipt_ms <= 0):
        parser.error('simulated receipt delay must be finite and positive')
    torch.set_num_threads(2)
    config = HILConfig(**json.loads((args.run/'config.json').read_text()))
    actor, version, recipe = load_actor(args.run/'actor.pt', config.replay_contract(), 'cuda')
    transport = RosTransport(config, recipe['base_contract'], execute=False, rgb_max_age_ms=500)
    pipeline = None
    if args.simulate_receipt_ms is not None:
        def infer(obs):
            with torch.inference_mode():
                return actor.sample({k: torch.as_tensor(v, device='cuda')[None]
                                     for k, v in obs.items()}, True)[0][0].cpu().numpy()
        pipeline = transport.policy_pipeline = LatestPolicy(infer)
    next_completion = 0.
    rows = []
    last = None
    started = time.monotonic()
    try:
        while time.monotonic()-started < args.seconds:
            transport._pump()
            if pipeline is not None:
                if time.monotonic() < next_completion or not transport._handoff_ready():
                    continue
                obs, stamp = transport.latest
                candidate = pipeline.get(stamp)
                if candidate is None or stamp == last:
                    continue
                last = stamp
                now = transport.node.get_clock().now().nanoseconds
                rows.append(dict(total_age_ms=(now-stamp)/1e6,
                                 background_inference_wall_ms=candidate[1]))
                next_completion = time.monotonic()+args.simulate_receipt_ms/1000
                continue
            if transport.latest is None or transport.latest[1] == last:
                continue
            obs, last = transport.latest
            begin = transport.node.get_clock().now().nanoseconds
            t = time.monotonic_ns()
            with torch.inference_mode():
                action = actor.sample({k: torch.as_tensor(v, device='cuda')[None]
                                       for k, v in obs.items()}, True)[0].cpu().numpy()
            inference_ms = (time.monotonic_ns()-t)/1e6
            t = time.monotonic_ns()
            transport._pump()
            pump_ms = (time.monotonic_ns()-t)/1e6
            finish = transport.node.get_clock().now().nanoseconds
            row = dict(age_before_inference_ms=(begin-last)/1e6,
                       inference_wall_ms=inference_ms, pre_send_pump_ms=pump_ms,
                       total_age_ms=(finish-last)/1e6)
            rows.append(row)
            if row['total_age_ms'] >= 100:
                print(json.dumps(row), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        report = dict(robot_action_publishers=0, policy_version=version, samples=len(rows),
                      over_100ms=sum(r['total_age_ms'] >= 100 for r in rows),
                      simulated_receipt_ms=args.simulate_receipt_ms,
                      limitations='No motion, real receipts, spool or concurrent learner; sequential mode includes cold CUDA startup',
                      accepted=dict(transport.runtime.accepted), rejected=dict(transport.runtime.rejected), rows=rows)
        if pipeline is not None:
            pipeline.close()
        transport.close()
        atomic_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != 'rows'}), flush=True)


if __name__ == '__main__':
    main()

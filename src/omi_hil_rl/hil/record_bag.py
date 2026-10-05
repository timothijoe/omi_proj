"""Passive observation/command rosbag recorder; gamepad runs independently."""
import argparse
import math
import os
from pathlib import Path
import time

from .config import HILConfig, load_config
from .demo import RawBag, recording_topics
from .exchange import atomic_json
from omi_hil_rl.training.eef_bc_grid import GridProfile

DEFAULT_COMMAND_TOPIC = '/omi/controller_test/decision'


def positive_seconds(value):
    value=float(value)
    if not math.isfinite(value) or value<=0:
        raise argparse.ArgumentTypeError('duration must be positive and finite')
    return value


def record(directory, *, config=None, command_topic=DEFAULT_COMMAND_TOPIC, duration=None,
           extra_topics=(), all_topics=False):
    config=config or HILConfig(transport='ros',wrist_camera='required')
    if duration is not None and (not math.isfinite(duration) or duration<=0):
        raise ValueError('duration must be positive and finite')
    if not command_topic.startswith('/'):
        raise ValueError('command topic must be an absolute ROS topic')
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    topics=recording_topics(GridProfile(config.wrist_camera).TOPICS,
                            command_topic=command_topic,extra_topics=extra_topics)
    session=dict(version='omi-passive-gamepad-bag-v1',mode='passive_recording',
        ros_domain=os.environ.get('ROS_DOMAIN_ID'),command_topic=command_topic,
        topics=topics,all_topics=all_topics,requested_duration_s=duration,
        action_publishers=[],reads_gamepad=False,raw_bag='raw',
        training_labels_generated=False,
        action_semantics='raw wire commands from independent publishers; not verified human/accepted-command labels',
        snapshots='not generated; /omi/demo/sample is recorded only if another process publishes it',
        input_config_scope='observation topic selection only; not the external gamepad speed/frame settings',
        button_semantics='owned by external gamepad; no collector start/success/keep/discard buttons')
    atomic_json(directory/'session.json',session)
    recorder=None;started=None;reason='duration_elapsed'
    try:
        recorder=RawBag(directory,topics,all_topics=all_topics)
        started=time.monotonic()
        print(f'仅录包，不读取手柄、不发送机器人指令。\n手柄 topic: {command_topic}\n保存: {directory / "raw"}\nCtrl+C 停止录制。',flush=True)
        while duration is None or time.monotonic()-started<duration:
            recorder.check()
            delay=.1 if duration is None else min(.1,max(0.,duration-(time.monotonic()-started)))
            time.sleep(delay)
    except KeyboardInterrupt:
        reason='operator_stop'
    except BaseException:
        reason='error'
        raise
    finally:
        try:
            if recorder is not None:recorder.close()
        finally:
            session.update(stop_reason=reason,elapsed_after_ready_s=time.monotonic()-started if started is not None else None)
            atomic_json(directory/'session.json',session)
    print(f'录制结束：{directory / "raw"}\n消息统计：{directory / "raw_recording.json"}',flush=True)
    return session


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='new session directory; bag stored in raw/')
    parser.add_argument('--config',type=Path,help='observation topic selection only')
    parser.add_argument('--command-topic',default=DEFAULT_COMMAND_TOPIC,help='match independently running gamepad_test.py --topic')
    parser.add_argument('--duration',type=positive_seconds,help='stop after this many seconds; otherwise Ctrl+C')
    parser.add_argument('--raw-topic',action='append',default=[],help='additional topic, repeatable')
    parser.add_argument('--all-topics',action='store_true',help='optional; default records explicit observation/command list')
    args=parser.parse_args()
    record(args.directory,config=load_config(args.config) if args.config else None,
           command_topic=args.command_topic,duration=args.duration,extra_topics=args.raw_topic,all_topics=args.all_topics)


if __name__=='__main__':main()

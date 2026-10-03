"""Read-only grid24x16 + recorded wrist ROI + robot review. Never replay commands."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import recorded_observation as base
from .tactile_vectors import render_vector_field
from .wrist_recorded_review import prepare_model

VERSION = 'grid-recorded-review-v1'
TOPICS = {'/camera/camera/color/image_raw': 'camera',
          '/omi/wrist/color/image_roi': 'wrist_roi',
          '/tj/info/joint_feedback': 'joints', '/tj/info/eef_left': 'eef'}
TOPICS.update({f'/omi/tactile_grid24x16/{s}/{kind}': f'{s}_{"force" if kind == "wrench" else kind}'
               for s in 'ab' for kind in ('deformation', 'shear', 'depth', 'wrench')})


def decode(key, msg):
    item = base.decode(key, msg)
    expected = ((16, 24, 2) if key.endswith(('deformation', 'shear')) else
                (16, 24) if key.endswith('depth') else
                (128, 128, 3) if key == 'wrist_roi' else None)
    if expected is not None and item['value'].shape != expected:
        raise ValueError(f'{key}: expected {expected}, got {item["value"].shape}')
    return item


def vector_preview(field):
    # Repeat only for display: step16 now selects each grid value exactly once.
    # Vector amplitudes retain SDK units; this does NOT reconstruct lost detail.
    if field.shape != (16, 24, 2):
        raise ValueError('Expected 16x24x2 grid')
    display = np.repeat(np.repeat(field, 16, axis=0), 16, axis=1)
    return render_vector_field(display, step=16, scale_px_per_unit=20.,
                               deadband=.01, max_arrow_px=24.)


def render(latest, stamp, elapsed, label='GRID BAG'):
    canvas = base.render({k:v for k,v in latest.items() if not k.endswith(('deformation','shear','depth'))}, stamp, elapsed)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 16)
    except OSError:
        font = ImageFont.load_default()
    bg = (18,22,28)
    def text(x,y,value): draw.text((x,y),value,font=font,fill='#f1c46b')
    draw.rectangle((0,0,1535,53),fill=bg)
    text(10,5,f'{label[:90]} | {elapsed:.2f}s | GRID24x16 | 10Hz preview | NO CONTROL')
    text(10,28,'384 vectors/field; 20px/unit, red=clipped24px. Source ages are NOT latency; FUTURE => check clocks.')
    draw.rectangle((768,58,1535,381),fill=bg)
    text(780,58,'Wrist recorded ROI128 (enlarged ONLY; no second crop)')
    item = latest.get('wrist_roi')
    text(780,80,base.age_label(item,stamp))
    if item is not None:
        canvas.paste(Image.fromarray(item['value']).resize((278,278),Image.Resampling.NEAREST),(800,102))
    text(1140,145,'Full wrist image not used')
    for i,side in enumerate('ab'):
        for j,kind in enumerate(('deformation','shear')):
            x=(i*2+j)*384
            draw.rectangle((x,382,x+383,705),fill=bg)
            text(x+5,382,side.upper()+' '+kind+' 16x24x2')
            item=latest.get(side+'_'+kind)
            text(x+5,402,base.age_label(item,stamp))
            if item is not None:
                canvas.paste(Image.fromarray(vector_preview(item['value'])[0]),(x,430))
        x=i*384
        draw.rectangle((x,706,x+383,1029),fill=bg)
        text(x+5,706,side.upper()+' depth16x24; fixed0..0.3 (clipped)')
        item=latest.get(side+'_depth')
        text(x+5,726,base.age_label(item,stamp))
        if item is not None:
            u=np.clip(item['value']/.3,0,1)
            rgb=(np.stack((u,np.sqrt(u),1-u),axis=-1)*255).astype(np.uint8)
            canvas.paste(Image.fromarray(rgb).resize((376,251),Image.Resampling.NEAREST),(x+4,752))
        x=(i+2)*384
        draw.rectangle((x,706,x+383,1029),fill=bg)
        text(x+5,730,side.upper()+' raw not subscribed by grid viewer')
        text(x+5,755,'No raw synthesis from numeric fields')
    return canvas


def positive(value):
    result=float(value)
    if not math.isfinite(result) or result<=0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bag',type=Path,help='MCAP bag directory or ZIP containing exactly one bag')
    p.add_argument('--rate',type=positive,default=1.)
    p.add_argument('--domain',type=int,default=92)
    p.add_argument('--no-rviz',action='store_true')
    p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--strict-clock',action='store_true',help='reject source headers later than receipt; default warns and preserves them')
    p.add_argument('--duration',type=positive,help='limit playback seconds, useful for smoke testing')
    p.add_argument('--model-bundle',type=Path)
    args=p.parse_args()
    if not 0<=args.domain<=232: p.error('domain must be 0..232')
    root=Path(os.environ['OMI_PROJECT_ROOT'])
    runtime=root/'local/grid_recorded_review';runtime.mkdir(parents=True,exist_ok=True)
    # Same entry/domain cannot mix sources. Other viewers must use separate domains.
    with (runtime/f'domain-{args.domain}.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: p.error('grid viewer already running in this domain; stop it or use --domain')
        cache=base.prepare(args.bag,runtime/'cache',topics=TOPICS,
            renderer=lambda latest,stamp,elapsed: render(latest,stamp,elapsed,args.bag.parent.name+'/'+args.bag.name),
            decoder=decode,cache_version=VERSION,allow_future_headers=not args.strict_clock)
        manifest=json.loads((cache/'manifest.json').read_text())
        if not any(key.endswith(('deformation','shear','depth')) for key in manifest['counts']):
            p.error('no grid24x16 field messages; use an appropriate legacy viewer')
        report={key:manifest[key] for key in ('source','counts','recorded_topic_counts','future_headers','note')}
        print(json.dumps(report,indent=2),flush=True)
        print('Cache: '+str(cache),flush=True)
        if args.prepare_only: return 0
        model=prepare_model(args.model_bundle or root/'local/models/omi_marvin_stand_axis_corrected_v1',
                            runtime/'models',root/'scripts/recorded_observation_3d.rviz')
        from omi_sensors.cli import supervise
        rsp=subprocess.check_output(['ros2','pkg','prefix','robot_state_publisher'],text=True).strip()
        env=dict(os.environ,ROS_DOMAIN_ID=str(args.domain),ROS_LOCALHOST_ONLY='1',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
        commands=[
            [rsp+'/lib/robot_state_publisher/robot_state_publisher','--ros-args','--params-file',str(model/'publisher.yaml'),
             '-r','__ns:=/omi/replay_3d','-r','/tf:=/omi/replay_3d/tf','-r','/tf_static:=/omi/replay_3d/tf_static'],
            [sys.executable,'-m','omi_hil_rl.real.recorded_observation','view',str(cache),'--rate',str(args.rate)],
            [sys.executable,'-m','omi_hil_rl.real.stand_urdf_review','markers','--corrected']]
        if not args.no_rviz:
            commands.append(['rviz2','-d',str(model/'review.rviz'),'--ros-args',
                             '-r','/tf:=/omi/replay_3d/tf','-r','/tf_static:=/omi/replay_3d/tf_static'])
        print(f'Grid review domain{args.domain}; close RViz or Ctrl+C to stop. No hardware/control.',flush=True)
        return supervise(commands,env,args.duration)


if __name__=='__main__':
    sys.exit(main())

"""Opt-in wrist + native tactile review. No live sensors or control output."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import recorded_observation as base
from .observation import ObservationConfig, _crop_square_resize_nearest

WRIST = '/tj/dm_camera/camera/color'
VERSION = 'wrist-review-v2-legacy-roi-lanczos-128'


def wrist_preview(rgb):
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Expected RGB wrist image')
    _, (x, y, side) = _crop_square_resize_nearest(rgb, ObservationConfig().wrist_rgb_roi, (128,128))
    # Same ROI and 128px human-preview pixels as camera_panels.prepare_camera.
    small = np.asarray(Image.fromarray(rgb).crop((x,y,x+side,y+side)).resize((128,128), Image.Resampling.LANCZOS))
    return small, (x, y, side)


def render(latest, stamp, elapsed):
    canvas = base.render(latest, stamp, elapsed)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 16)
    except OSError:
        font = ImageFont.load_default()
    item = latest.get('wrist')
    for col, title in [(2, 'Wrist original + legacy ROI'), (3, 'Wrist legacy ROI 128 (enlarged)')]:
        x = col*384
        draw.rectangle((x,58,x+383,381),fill=(18,22,28))
        draw.text((x+5,58),title,font=font,fill='white')
        draw.text((x+5,78),base.age_label(item,stamp),font=font,fill='#f1c46b')
        if item is None:
            continue
        rgb = item['value']; small,(left,top,side) = wrist_preview(rgb)
        if col == 2:
            im=Image.fromarray(rgb)
            ImageDraw.Draw(im).rectangle((left,top,left+side-1,top+side-1),outline='yellow',width=5)
        else:
            im=Image.fromarray(small).resize((278,278),Image.Resampling.BILINEAR)
        im.thumbnail((376,278),Image.Resampling.BILINEAR)
        canvas.paste(im,(x+(384-im.width)//2,100+(278-im.height)//2))
    draw.rectangle((0,1130,1535,1169),fill=(18,22,28))
    draw.text((10,1132),'Wrist: legacy ROI (.500,.704,.36), Lanczos 128; NOT undistortion. Base/TCP/limits unverified.',font=font,fill='#f1c46b')
    return canvas


def prepare_model(bundle, output, template):
    """Use the named OMI derived archive; resolve mesh URIs locally, no re-flip."""
    import yaml
    bundle = Path(bundle).resolve()
    source = bundle/'urdf/omi_marvin_stand_axis_corrected_v1.urdf'
    root = ET.parse(source).getroot()
    if root.get('name') != 'omi_marvin_stand_axis_corrected_v1':
        raise ValueError('Expected named OMI corrected model, not vendor original')
    for mesh in root.findall('.//mesh'):
        prefix = 'package://omi_marvin_stand_axis_corrected_v1/'
        uri = mesh.get('filename')
        if not uri.startswith(prefix):
            raise ValueError('Unexpected mesh URI')
        path = (bundle/uri[len(prefix):]).resolve()
        if not path.is_relative_to(bundle) or not path.is_file():
            raise ValueError('Missing/unsafe mesh asset')
        mesh.set('filename',path.as_uri())
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    dest=Path(tempfile.mkdtemp(prefix='wrist-',dir=output))
    text=ET.tostring(root,encoding='unicode')
    (dest/'publisher.yaml').write_text(yaml.safe_dump({'/**':{'ros__parameters':{'robot_description':text,'publish_frequency':30.,'use_sim_time':False}}}))
    config=yaml.safe_load(Path(template).read_text())
    manager=config['Visualization Manager'];manager['Displays'][1]['Name']='OMI corrected Stand + wrist review (NO CONTROL)'
    manager['Views']['Current']['Focal Point']['Z']=.85
    manager['Displays'].append({'Class':'rviz_default_plugins/MarkerArray','Name':'L7 is NOT TCP','Enabled':True,'Value':True,
        'Topic':{'Value':'/omi/stand_review/markers','Depth':1,'Reliability Policy':'Reliable','Durability Policy':'Volatile'}})
    (dest/'review.rviz').write_text(yaml.safe_dump(config))
    (dest/'model.json').write_text(json.dumps(dict(source=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),note='Named OMI derived model; no extra sign mapping; base/TCP/limits unverified'),indent=2))
    return dest


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    c=sub.add_parser('prepare');c.add_argument('bag');c.add_argument('cache')
    c=sub.add_parser('model');c.add_argument('bundle');c.add_argument('output');c.add_argument('template')
    args=p.parse_args()
    if args.mode=='prepare':
        print(base.prepare(args.bag,args.cache,topics={**base.TOPICS,WRIST:'wrist'},renderer=render,cache_version=VERSION))
    else: print(prepare_model(args.bundle,args.output,args.template))


if __name__=='__main__':main()

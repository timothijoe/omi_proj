"""Read-only browser review of every recorded tick in a periodic RL run."""

from __future__ import annotations

import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from omi_hil_rl.real.tactile_vectors import render_vector_field


def _font(size):
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError:
        return ImageFont.load_default()


def _render_rgb(canvas, draw, obs, key, index, x, y, size, valid):
    if valid:
        pixels = np.asarray(obs[key][index])
        if pixels.shape != (3, 128, 128) or pixels.dtype != np.uint8:
            raise ValueError(f'invalid {key} frame shape or dtype')
        canvas.paste(Image.fromarray(pixels.transpose(1, 2, 0)).resize((size, size), Image.Resampling.NEAREST), (x, y))
    else:
        draw.rectangle((x, y, x + size, y + size), fill='#303943')
        draw.text((x + 5, y + size // 2), 'MISSING', fill='#ff9682', font=_font(13))


def render_observation(obs, slot):
    if not 0 <= slot < 10:
        raise ValueError('history slot must be 0..9')
    mask = np.asarray(obs['history_mask'])
    cameras = np.asarray(obs['camera_mask'])
    if mask.shape != (10,) or cameras.shape != (10, 2):
        raise ValueError('unexpected history/camera masks')
    canvas = Image.new('RGB', (1160, 1040), '#161b22')
    draw = ImageDraw.Draw(canvas)
    title, small = _font(19), _font(14)
    draw.text((18, 10), 'Recorded 10-frame observation  |  slot 9 is newest', fill='#e9eef4', font=title)
    for row, key in enumerate(('rgb', 'wrist_rgb')):
        y = 62 + row * 142
        draw.text((18, y - 23), 'External RGB' if row == 0 else 'Wrist ROI', fill='#e9c77c', font=small)
        for i in range(10):
            x = 18 + i * 112
            valid = bool(mask[i] and cameras[i, row])
            _render_rgb(canvas, draw, obs, key, i, x, y, 104, valid)
            draw.rectangle((x, y, x + 104, y + 104), outline='#f5d976' if i == slot else '#4c5b68', width=3 if i == slot else 1)
            draw.text((x + 3, y + 107), f'{i}: {"OK" if valid else "--"}', fill='#e9c77c' if i == slot else '#9eabb7', font=small)
    draw.text((18, 333), f'Selected history slot {slot}/9', fill='#e9c77c', font=title)
    for j, key in enumerate(('rgb', 'wrist_rgb')):
        x = 18 + j * 330
        draw.text((x, 360), 'External RGB' if j == 0 else 'Wrist ROI', fill='#e9eef4', font=small)
        _render_rgb(canvas, draw, obs, key, slot, x, 385, 300, bool(mask[slot] and cameras[slot, j]))
    tactile = np.asarray(obs['tactile'])
    if tactile.shape != (10, 10, 16, 24):
        raise ValueError('unexpected tactile shape')
    draw.text((685, 360), 'Tactile vectors (fixed scale)', fill='#e9eef4', font=small)
    for side in range(2):
        for field in range(2):
            channel = side * 5 + field * 2
            x, y = 685 + field * 232, 385 + side * 150
            draw.text((x, y), f'{"AB"[side]} {("deformation", "shear")[field]}', fill='#e9c77c', font=small)
            values = tactile[slot, channel:channel + 2].transpose(1, 2, 0)
            if np.isfinite(values).all():
                large = np.repeat(np.repeat(values, 8, axis=0), 8, axis=1)
                picture, _ = render_vector_field(large, step=8, scale_px_per_unit=10., deadband=.01, max_arrow_px=12.)
                canvas.paste(Image.fromarray(picture).resize((220, 120)), (x, y + 22))
            else:
                draw.text((x, y + 40), 'INVALID numeric field', fill='#ff9682', font=small)
    draw.text((18, 713), 'Depth fields: fixed display range 0..0.3 (SDK values, not physical calibration)', fill='#e9eef4', font=small)
    for side in range(2):
        x = 18 + side * 340
        values = tactile[slot, side * 5 + 4]
        if np.isfinite(values).all():
            scaled = np.clip(values / .3, 0, 1)
            colors = (np.stack((scaled, np.sqrt(scaled), 1 - scaled), axis=-1) * 255).astype(np.uint8)
            canvas.paste(Image.fromarray(colors).resize((320, 210), Image.Resampling.NEAREST), (x, 755))
            draw.text((x, 970), f'{"AB"[side]} depth | min {float(np.min(values)):.4f} max {float(np.max(values)):.4f}', fill='#e9c77c', font=small)
        else:
            draw.text((x, 780), f'{"AB"[side]} depth INVALID', fill='#ff9682', font=small)
    draw.text((18, 1008), 'READ ONLY | Images and tactile fields are exact stored observation arrays; display is enlarged.', fill='#a9b5c0', font=small)
    output = BytesIO()
    canvas.save(output, 'PNG')
    return output.getvalue()


class PeriodicReview:
    def __init__(self, run):
        self.run = Path(run).resolve()
        source = self.run / 'periodic_episodes'
        if not source.is_dir():
            raise ValueError(f'no periodic_episodes directory: {source}')
        self.episodes = []
        for directory in source.iterdir():
            if not directory.is_dir() or not (directory / 'staging.json').is_file():
                continue
            audit_path = directory / 'audit.json'
            audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
            ticks = int(audit['ticks']) if audit else len(list(directory.glob('[0-9][0-9][0-9][0-9][0-9][0-9].npz')))
            pairing_path = directory / 'pairing.json'
            pairing = json.loads(pairing_path.read_text()) if pairing_path.exists() else []
            training = {}
            if audit:
                for name in audit.get('segments', []):
                    ready_path = self.run / 'episodes' / name / 'ready.json'
                    if not ready_path.is_file():
                        continue
                    ready = json.loads(ready_path.read_text())
                    start = int(name.rsplit('-segment-', 1)[1])
                    for tick in range(start, start + int(ready['count'])):
                        training[tick] = bool((ready_path.parent / 'imported.json').exists())
            self.episodes.append(dict(directory=directory, audit=audit, ticks=ticks, pairing=pairing, training=training))
        self.episodes.sort(key=lambda item: item['directory'].stat().st_mtime)
        if not self.episodes:
            raise ValueError('no periodic episodes found')

    def catalog(self):
        return dict(run=str(self.run), episodes=[dict(
            id=item['directory'].name, ticks=item['ticks'], audited=item['audit'] is not None,
            transitions=item['audit'].get('transitions', 0) if item['audit'] else 0,
            success=item['audit'].get('success', False) if item['audit'] else False,
            success_label_recorded=item['audit'].get('success_label_recorded', False) if item['audit'] else False,
            training_ready=item['audit'].get('training_ready', False) if item['audit'] else False,
            reason=item['audit'].get('reason', 'unfinished') if item['audit'] else 'unfinished',
            excluded=item['audit'].get('excluded', {}) if item['audit'] else {},
        ) for item in self.episodes])

    def tick(self, episode, index, slot):
        if not 0 <= episode < len(self.episodes):
            raise ValueError('episode index out of range')
        item = self.episodes[episode]
        if not 0 <= index < item['ticks'] or not 0 <= slot < 10:
            raise ValueError('tick or history slot out of range')
        path = item['directory'] / f'{index:06d}.npz'
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive['metadata']))
            obs = {key.removeprefix('observation__'): archive[key].copy()
                   for key in archive.files if key.startswith('observation__')}
        present = set(obs) == {'rgb', 'wrist_rgb', 'camera_mask', 'tactile', 'state', 'history_mask'}
        if not present and obs:
            raise ValueError('incomplete stored observation')
        if bool(metadata.get('observation_present')) != present:
            raise ValueError('observation_present does not match stored arrays')
        picture = render_observation(obs, slot) if present else None
        stamp = metadata.get('observation_reference_ns')
        send = metadata.get('command_send_ns')
        return dict(episode=item['directory'].name, tick=index, slot=slot,
                    image=('data:image/png;base64,' + base64.b64encode(picture).decode()) if picture else None,
                    observation_present=present,
                    history_valid=int(np.sum(obs['history_mask'])) if present else 0,
                    camera_valid=np.sum(obs['camera_mask'], axis=0).astype(int).tolist() if present else [0, 0],
                    eef_xyz=obs['state'][slot, 7:10].astype(float).tolist() if present else None,
                    pairing=item['pairing'][index] if index < len(item['pairing']) else 'unavailable',
                    in_training=index in item['training'],
                    imported=item['training'].get(index),
                    action_source=metadata.get('action_source'), gate=metadata.get('gate'),
                    policy_version=metadata.get('policy_version'),
                    normalized_action=metadata.get('normalized_action'), wire_action=metadata.get('wire_action'),
                    observation_reference_ns=stamp, command_send_ns=send,
                    command_phase_ms=(send - stamp) / 1e6 if stamp and send else None,
                    command_id=metadata.get('command_id'))


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>RL 回合逐帧检查</title>
<style>body{margin:0;background:#151b22;color:#e6edf3;font:15px system-ui}header{position:sticky;top:0;z-index:2;background:#222b35;padding:12px 18px;border-bottom:1px solid #44515e}button,select,input{margin:4px;padding:6px}#seek{width:45vw}#image{max-width:1160px;width:100%}main{padding:16px;max-width:1300px}#summary,#detail{white-space:pre-wrap;line-height:1.5}#summary{color:#b9c8d6}#detail{color:#edcf8c}.bad{color:#ff9682}.good{color:#82dab5}</style>
<header><strong>真机 RL 原始回合逐帧检查 · 只读</strong><br>
回合 <select id="episode"></select> <button id="prev">←</button><button id="play">播放</button><button id="next">→</button>
周期 <input id="seek" type="range" min="0" value="0"><span id="position"></span>
历史帧 <select id="slot"></select><small>键盘 ← / → 切周期；当前观测中 9 为最新帧</small></header>
<main><div id="summary"></div><div id="detail"></div><img id="image" alt="当前周期的两路相机及触觉历史"><p id="empty"></p></main>
<script>
const $=id=>document.getElementById(id);let catalog, busy=false, pending=false, playing=false, timer;
for(let i=0;i<10;i++)$('slot').add(new Option(`${i} (${(i-9)*100} ms)`,i));$('slot').value=9;
function stop(){playing=false;clearTimeout(timer);$('play').textContent='播放'}
function summary(){const e=catalog.episodes[+$('episode').value];$('summary').textContent=`${catalog.run}\n回合 ${e.id} | ${e.ticks} 周期 | ${e.audited?'完整审计':'仅暂存'} | ${e.transitions} 条入池候选 | ${e.reason} | success=${e.success} | 成功奖励=${e.success_label_recorded}\n排除原因: ${JSON.stringify(e.excluded)}`}
async function show(){if(!catalog)return;if(busy){pending=true;return}busy=true;const ep=+$('episode').value,tick=+$('seek').value,slot=+$('slot').value;
 $('position').textContent=`${tick+1}/${catalog.episodes[ep].ticks}`;summary();
 try{const r=await fetch(`/tick?episode=${ep}&index=${tick}&slot=${slot}`);if(!r.ok)throw Error(await r.text());const d=await r.json();
 $('detail').textContent=`周期 ${d.tick} | ${d.observation_present?'有观测':'无观测'} | 历史 ${d.history_valid}/10 | 相机有效 外部/腕部 ${d.camera_valid.join('/')}/10 | 配对 ${d.pairing} | 训练片段 ${d.in_training?'是':'否'} | Learner导入 ${d.imported===null?'不适用':d.imported?'是':'否'}\n来源 ${d.action_source} | gate ${d.gate} | policy v${d.policy_version} | 命令相位 ${d.command_phase_ms===null?'--':d.command_phase_ms.toFixed(2)+' ms'} | EEF xyz ${JSON.stringify(d.eef_xyz)}\n归一化动作 ${JSON.stringify(d.normalized_action)}\n发送指令 ${JSON.stringify(d.wire_action)} | ID ${d.command_id}`;
 $('detail').className=d.in_training?'good':'bad';$('image').hidden=!d.image;$('empty').textContent=d.image?'':'此周期没有完整观测图像；仍保留命令和审计元数据。';if(d.image)$('image').src=d.image;
 }catch(e){stop();$('detail').textContent=String(e);$('detail').className='bad'}finally{busy=false;if(pending){pending=false;show()}else if(playing)timer=setTimeout(advance,350)}}
function advance(){if(+$('seek').value>=+$('seek').max){stop();return}$('seek').value=+$('seek').value+1;show()}
function move(n){stop();$('seek').value=Math.max(0,Math.min(+$('seek').max,+$('seek').value+n));show()}
$('prev').onclick=()=>move(-1);$('next').onclick=()=>move(1);$('play').onclick=()=>{if(playing)stop();else{playing=true;$('play').textContent='暂停';advance()}};
$('episode').onchange=()=>{stop();$('seek').max=catalog.episodes[+$('episode').value].ticks-1;$('seek').value=0;show()};$('seek').oninput=()=>{stop();show()};$('slot').onchange=()=>{stop();show()};
document.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key)||e.target.closest?.('input,select,textarea'))return;e.preventDefault();move(e.key==='ArrowLeft'?-1:1)});
fetch('/catalog').then(r=>r.json()).then(d=>{catalog=d;d.episodes.forEach((e,i)=>$('episode').add(new Option(`${i+1}: ${e.id.slice(0,8)} | ${e.ticks}周期 | ${e.transitions}可训练`,i)));$('seek').max=d.episodes[0].ticks-1;show()}).catch(e=>$('detail').textContent=String(e));
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, review, **kwargs):
        self.review = review
        super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            if url.path == '/':
                payload, kind = PAGE.encode(), 'text/html; charset=utf-8'
            elif url.path == '/catalog':
                payload, kind = json.dumps(self.review.catalog()).encode(), 'application/json'
            elif url.path == '/tick':
                query = parse_qs(url.query)
                payload = json.dumps(self.review.tick(int(query['episode'][0]), int(query['index'][0]),
                                                      int(query.get('slot', ['9'])[0]))).encode()
                kind = 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, KeyError, IndexError, FileNotFoundError) as exc:
            self.send_error(400, str(exc))

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='existing run with periodic_episodes/')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    review = PeriodicReview(args.run)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), lambda *a, **k: Handler(*a, review=review, **k))
    print(f'READ ONLY: http://127.0.0.1:{args.port}/ | {len(review.episodes)} episodes', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

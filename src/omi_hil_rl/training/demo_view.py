"""Read-only, lazy per-transition dashboard for exact demo model observations."""
import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from omi_hil_rl.hil.demo import read_demo_step
from omi_hil_rl.real.grid_recorded_review import vector_preview


class DatasetView:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        if (self.directory / 'conversion_pending.json').exists() or (self.directory.parent.parent / 'conversion_pending.json').exists():
            raise ValueError('dataset conversion is incomplete')
        paths = ([self.directory / 'demo.json'] if (self.directory / 'demo.json').exists()
                 else sorted(self.directory.glob('episodes/*/demo.json')))
        if not paths:
            paths = ([self.directory / 'dataset.json'] if (self.directory / 'dataset.json').exists()
                     else sorted(self.directory.glob('episodes/*/dataset.json')))
        self.episodes = [(p.parent, json.loads(p.read_text())) for p in paths]
        self.episodes = [(p,m) for p,m in self.episodes if m.get('keep', True) and m.get('valid', True) and m['count']]
        if not self.episodes:
            raise ValueError('no retained episodes found')

    def catalog(self):
        return dict(dataset=str(self.directory), episodes=[dict(id=m['episode'], count=m['count'],
                    synthetic=m.get('synthetic', False), diagnostic=m.get('training_allowed') is False,
                    has_next=m['version'] != 'omi-passive-command-bc-wrench-v1',
                    raw_wire=m.get('display_action')=='raw_wire', outcome=m.get('operator_outcome', 'BC; outcome unlabelled'),
                    bag=m.get('raw_bag', m.get('source_bag'))) for _,m in self.episodes])

    def frame(self, episode, step, slot=9, after=False):
        if not 0 <= episode < len(self.episodes) or not 0 <= slot < 10:
            raise ValueError('episode/history index out of range')
        directory, manifest = self.episodes[episode]
        if manifest['version'] == 'omi-passive-command-bc-wrench-v1':
            if after or not 0 <= step < manifest['count']:
                raise ValueError('BC sample has no next observation, or step out of range')
            from .passive_bc import PassiveDataset
            path = directory/f'{step:06d}.npz'
            obs, action, metadata = PassiveDataset.read(path)
            with np.load(path, allow_pickle=False) as archive:
                for key in ('wrench_receive_ns', 'wrench_header_ns'):
                    obs[key] = archive[key].copy()
            metadata.update(action_source='recorded_command_bc', command_status='RECORDED; no execution receipt',
                current_observation_audit=metadata['observation_audit'],
                observation_wrench_frame_ids=metadata['wrench_frame_ids'],
                command_audit=dict(command_receive_ns=metadata['command_receive_ns'], wire_action=metadata['wire_action']))
            return render(obs, action, metadata, manifest, step, slot, False)
        from .zero_preview import VERSION as ZERO_VERSION, load_step
        from .passive_preview import VERSION as WIRE_VERSION, load_step as load_wire
        loader = load_wire if manifest["version"] == WIRE_VERSION else (load_step if manifest["version"] == ZERO_VERSION else read_demo_step)
        obs, nxt, action, metadata = loader(directory, step, manifest)
        selected = nxt if after else obs
        return render(selected, action, metadata, manifest, step, slot, after)


def render(obs, action, meta, manifest, step, slot, after):
    has_wrench = 'wrench' in obs
    timing_audit = (meta.get('command_audit', {}).get('next_observation_status', {}) if after
                    else meta.get('current_observation_audit', {}))
    has_alignment = bool(timing_audit.get('field_alignment_history'))
    height = (1520 if has_wrench else 1350) if has_alignment else (1280 if has_wrench else 1060)
    canvas = Image.new('RGB', (1536, height), '#12161c')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('DejaVuSans.ttf', 16)
    small = ImageFont.truetype('DejaVuSans.ttf', 13)
    def text(x,y,value,color='#ead09b',tiny=False):
        draw.text((x,y),str(value),fill=color,font=small if tiny else font)
    diagnostic = manifest.get('training_allowed') is False
    raw_wire = manifest.get('display_action') == 'raw_wire'
    sdk_wire = raw_wire and manifest.get('wire_units') == 'mm,SDK_ABC_degrees'
    bc = manifest['version'] == 'omi-passive-command-bc-wrench-v1'
    label = 'REAL SENSORS / ZERO PLACEHOLDER / NOT FOR TRAINING' if diagnostic else ('SYNTHETIC / NOT HUMAN' if manifest.get('synthetic', False) else 'HUMAN DEMO')
    if bc: label = 'RECORDED COMMAND / BC ONLY / NOT AN RL TRANSITION'
    if raw_wire:label='REAL OBSERVATIONS / RECORDED WIRE / REVIEW ONLY'
    text(14,10,f'{label} | {manifest["episode"]} | step {step}/{manifest["count"]-1} | READ ONLY')
    text(14,35,f'{"NEXT observation (result)" if after else "Observation BEFORE action"} | history slot {slot}/9 ({(slot-9)*100} ms)')
    draw.line((752,62,752,canvas.height-20),fill='#495460')
    for i,key in enumerate(('rgb','wrist_rgb')):
        x=14+i*360
        valid=bool(obs['camera_mask'][slot,i]) and bool(obs['history_mask'][slot])
        text(x,65,('External RGB crop' if i==0 else 'Wrist ROI')+f' | mask={int(valid)}')
        if valid:
            canvas.paste(Image.fromarray(obs[key][slot].transpose(1,2,0)).resize((320,320),Image.Resampling.NEAREST),(x,92))
        else:
            draw.rectangle((x,92,x+320,412),outline='#666666')
            text(x+25,230,'MISSING / MASKED','#ff967b')
    scale=np.asarray(manifest['contract']['physical_action_scale'])
    units=action if raw_wire else action*scale*np.array([1000]*3+[180/np.pi]*3)
    bars=action/np.asarray(manifest['wire_display_scale']) if raw_wire else action
    text(14,442,'Recorded command: receipt unavailable' if raw_wire or bc else ('Zero placeholder: NO COMMAND SENT' if diagnostic else 'Adopted human action label'))
    text(14,467,('SDK BASE delta: XYZ mm / ABC degrees; source confirmed' if sdk_wire else 'Wire components 1..6; no inverse frame conversion assumed') if raw_wire else 'Policy-frame delta: translation mm / rotation vector deg')
    names=('dx','dy','dz','dA','dB','dC') if sdk_wire else ('wire1','wire2','wire3','wire4','wire5','wire6') if raw_wire else ('dx','dy','dz','rx','ry','rz')
    for i,name in enumerate(names):
        y=504+i*32
        unit='raw' if raw_wire and not sdk_wire else ('mm' if i<3 else 'deg')
        text(14,y,f'{name}: {units[i]:+.4f} {unit}')
        cx=460
        draw.line((cx-100,y+10,cx+100,y+10),fill='#555555',width=2)
        draw.line((cx,y,cx,y+21),fill='#dddddd')
        end=cx+int(float(bars[i])*100)
        draw.rectangle((min(cx,end),y+3,max(cx,end)+1,y+17),fill='#59ceb5')
        text(602,y,f'{bars[i]:+.4f}')
    text(14,704,'Bars: relative to each component maximum in this bag; NOT policy labels' if raw_wire else ('Bars: normalized [-1,1]; recorded BC label' if bc else 'Bars: normalized [-1,1]; not measured motion'),tiny=True)
    audit=meta.get('command_audit',{});wire=audit.get('wire_action')
    text(14,729,('Recorded wire: ' if raw_wire else 'SDK wire mm/ABC: ')+(', '.join(f'{v:+.4f}' for v in wire) if wire else 'not sent / none'),tiny=True)
    text(14,754,'Status: '+meta.get('command_status','unknown'),tiny=True)
    text(14,794,'Observation / action alignment')
    current=meta['observation_time_ns'];following=meta.get('next_observation_time_ns', current)
    sent=audit.get('command_receive_ns') if raw_wire or bc else audit.get('command_trace',{}).get('command_send_ns')
    rows=[f'obs t:      {current} ns',f'command {"RX" if raw_wire or bc else "TX"}: {sent if sent else "not sent / none"}',
          'next obs: absent (BC)' if bc else f'next obs t: {following} ns',
          'No post-command EEF requirement (BC)' if bc else f'next - obs: {(following-current)/1e6:.4f} ms',
          f'command - obs: {(sent-current)/1e6:.4f} ms' if sent else 'command timing: not sent / none',
          'EEF xyz/xyzw: ['+', '.join(f'{float(v):.4f}' for v in obs['state'][slot,7:])+']',
          'command ID: '+str(audit.get('command_id','none')),
          'source: '+meta['action_source']+' | reward: deferred / not used by BC']
    for i,row in enumerate(rows):text(14,827+i*23,row,tiny=True)
    text(14,1023,'STRICT sensor headers; command pairing uses bag receive time; REVIEW ONLY.' if raw_wire else ('DIAGNOSTIC: receive-time alignment; NOT FOR TRAINING.' if diagnostic else 'Exact dataset tensors; no commands are published.'),tiny=True)
    if has_wrench:
        text(14,1050,'Display: four decimal places; stored arrays retain full precision.',tiny=True)
        text(14,1075,'History slot 9 = latest. NEXT is a later observation, not execution proof.',tiny=True)
        text(14,1100,'Tactile panels and force/torque follow the selected history slot.',tiny=True)
    tactile=obs['tactile'][slot]
    tactile_top_offset=430 if has_wrench else 0
    for side in range(2):
        for field in range(2):
            x=782+field*376;y=65+side*249+tactile_top_offset
            start=side*5+field*2
            text(x,y,f'{"AB"[side]} {("deformation","shear")[field]} 16x24x2')
            picture=Image.fromarray(vector_preview(tactile[start:start+2].transpose(1,2,0))[0])
            canvas.paste(picture.resize((320,213),Image.Resampling.NEAREST),(x,y+27))
        x=782+side*376
        text(x,563+tactile_top_offset,f'{"AB"[side]} depth | fixed 0.0000..0.3000')
        u=np.clip(tactile[side*5+4]/.3,0,1)
        rgb=(np.stack((u,np.sqrt(u),1-u),axis=-1)*255).astype(np.uint8)
        canvas.paste(Image.fromarray(rgb).resize((320,213),Image.Resampling.NEAREST),(x,590+tactile_top_offset))
    if has_wrench:
        text(782,65,'6-axis force / torque | RAW SDK (N / Nm not verified)',tiny=True)
        reference=(following if after else current)-(9-slot)*100_000_000
        frames=meta.get(('next_observation' if after else 'observation')+'_wrench_frame_ids',[['','']]*10)
        colors=('#ff927d','#6cdca0','#74baff')
        for side in range(2):
            x=782+side*376
            valid=bool(obs['wrench_mask'][slot,side])
            rx=int(obs['wrench_receive_ns'][slot,side]);header=int(obs['wrench_header_ns'][slot,side])
            age=f'{(reference-rx)/1e6:.4f}ms' if rx else 'no sample'
            text(x,91,f'{"AB"[side]} | {"VALID" if valid else "MISSING / STALE / INVALID"}', '#6cdca0' if valid else '#ff927d')
            text(x,116,f'RX age: {age} | max 250.0000ms',tiny=True)
            text(x,137,'Frame: '+frames[slot][side][:36],tiny=True)
            text(x,158,f'Header: {header}' if header else 'Header: unavailable',tiny=True)
            text(x,179,f'Header age: {(reference-header)/1e6:.4f}ms' if header else 'Header age: --',tiny=True)
            for axis,name in enumerate(('Fx','Fy','Fz','Tx','Ty','Tz')):
                value=f'{float(obs["wrench"][slot,side,axis]):+.4f}' if valid else '--'
                text(x+(axis//3)*180,209+(axis%3)*27,f'{name}: {value}',colors[axis%3])
            for group in range(2):
                left=x;top=315+group*84;width=320;height=50
                data=obs['wrench'][:,side,group*3:group*3+3]
                good=obs['wrench_mask'][:,side].astype(bool)
                span=max(float(np.max(np.abs(data[good]))) if good.any() else 0.,.0001)
                text(left,top-23,f'{"Force" if group==0 else "Torque"} history | +/-{span:.4f} raw',tiny=True)
                draw.rectangle((left,top,left+width,top+height),outline='#495460')
                draw.line((left,top+height/2,left+width,top+height/2),fill='#495460')
                for axis in range(3):
                    for k in range(1,10):
                        if good[k-1] and good[k]:
                            draw.line((left+(k-1)*width/9,top+height/2-float(data[k-1,axis])*height/2/span,
                                       left+k*width/9,top+height/2-float(data[k,axis])*height/2/span),fill=colors[axis],width=2)
                draw.line((left+slot*width/9,top,left+slot*width/9,top+height),fill='#ffffff')
        text(782,459,'X red / Y green / Z blue; cursor = slot. Missing values show --.',tiny=True)
    timing = (audit.get('next_observation_status', {}) if after else meta.get('current_observation_audit', {}))
    history = timing.get('field_alignment_history', [])
    fields = history[slot] if len(history) == 10 else {}
    top = (1210 if has_wrench else 1060) if has_alignment else (1130 if has_wrench else 1041)
    if has_alignment:
        text(14,top,'Per-field timing | host timestamps do NOT verify synchronized exposure')
    if not fields:
        text(14,top,'Per-field timing unavailable; reconvert the bag to populate the audit.',tiny=True)
    else:
        tactile_headers = [v['header_ns'] for k,v in fields.items() if k.startswith(('a_','b_')) and v.get('header_ns')]
        if tactile_headers:
            text(14,top+27,f'Tactile host-header spread: {(max(tactile_headers)-min(tactile_headers))/1e6:.4f} ms',tiny=True)
        for i,(key,row) in enumerate(sorted(fields.items())):
            x=14+(i//6)*752; y=top+55+(i%6)*30
            header_age=row.get('header_age_ms')
            age='unknown' if header_age is None else f'{header_age:.4f}ms'
            rx_age = row.get('receive_age_ms')
            rx_text = 'missing' if rx_age is None else f'{rx_age:.4f}ms'
            text(x,y,f'{key}: RX {rx_text} | header {age} | SDK id {row.get("sdk_frame_id")}',
                 color='#ead09b' if row.get('valid') and row.get('header_within_age_limit', True) else '#ff927d',tiny=True)
    output=BytesIO();canvas.save(output,format='PNG')
    return output.getvalue()

PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Demo 观测 → 动作</title>
<style>body{margin:18px;background:#12161c;color:#eee;font:16px system-ui}header{position:sticky;top:0;background:#202831;padding:12px;z-index:1}button,select,input{margin:5px;padding:7px}#frame{width:100%;max-width:1536px}#seek{width:35%}#status{color:#ecd194;white-space:pre-wrap}</style>
<header><b>Demo 数据集：逐帧观测 → 动作</b><br>
<label>Episode <select id="ep"></select></label><button id="prev" aria-keyshortcuts="ArrowLeft">← 上一帧</button><button id="play">播放</button><button id="next" aria-keyshortcuts="ArrowRight">下一帧 →</button> <small>键盘 ← / → 切帧</small>
<input id="seek" type="range" min="0" value="0"><span id="count"></span><br>
<label>历史帧 <select id="slot"></select></label><label><input type="checkbox" id="after">查看动作后的 next observation</label>
<label>播放间隔 <select id="speed"><option value="200">200 ms</option><option value="100">100 ms</option><option value="500">500 ms</option></select></label>
<div id="status"></div></header><img id="frame" alt="数据集观测与动作"><script>
const $=id=>document.getElementById(id);let data,playing=false,busy=false,pending=false,timer;
for(let i=0;i<10;i++)$('slot').add(new Option(`${i} (${(i-9)*100} ms)`,i));$('slot').value=9;
function stop(){playing=false;clearTimeout(timer);$('play').textContent='播放'}
async function show(){if(!data)return;if(busy){pending=true;return}busy=true;const e=+$('ep').value,s=+$('seek').value,ep=data.episodes[e];
$('count').textContent=`${s+1} / ${ep.count}`;$('status').textContent=`${data.dataset}\nBag: ${ep.bag||'未录包 / synthetic'} | ${ep.outcome} | ${ep.raw_wire?'真实观测 / 实际发送值 / 待审核':ep.diagnostic?'真实观测 / 零标签诊断 / 禁止训练':(ep.synthetic?'合成测试数据':'人工示范')} `;
$('after').disabled=ep.has_next===false;if(ep.has_next===false)$('after').checked=false;
try{const r=await fetch(`/frame?episode=${e}&step=${s}&slot=${$('slot').value}&after=${+$('after').checked}`);if(!r.ok)throw Error(await r.text());
const old=$('frame').src;$('frame').src=URL.createObjectURL(await r.blob());if(old.startsWith('blob:'))URL.revokeObjectURL(old);
}catch(err){stop();$('status').textContent=String(err)}finally{busy=false;if(pending){pending=false;show()}else if(playing)timer=setTimeout(advance,+$('speed').value)}}
function advance(){if(busy)return;if(+$('seek').value>=+$('seek').max){stop();return}$('seek').value=+$('seek').value+1;show()}
function change(){stop();show()}
$('ep').onchange=()=>{stop();$('seek').max=data.episodes[+$('ep').value].count-1;$('seek').value=0;show()};
$('seek').onchange=change;$('slot').onchange=change;$('after').onchange=change;
function stepFrame(delta){if(!data)return;stop();const next=Math.max(0,Math.min(+$('seek').max,+$('seek').value+delta));if(next===+$('seek').value)return;$('seek').value=next;show()}
$('prev').onclick=()=>stepFrame(-1);$('next').onclick=()=>stepFrame(1);
document.addEventListener('keydown',event=>{
if(!data||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||!['ArrowLeft','ArrowRight'].includes(event.key))return;
const control=event.target.closest?.('input,textarea,select,[contenteditable="true"]');
if(control&&control.id!=='seek')return;
event.preventDefault();stepFrame(event.key==='ArrowLeft'?-1:1);
});
$('play').onclick=()=>{if(playing)stop();else{playing=true;$('play').textContent='暂停';advance()}};
fetch('/catalog').then(r=>r.json()).then(d=>{data=d;d.episodes.forEach((e,i)=>$('ep').add(new Option(`${i+1}: ${e.id} (${e.count})`,i)));const wanted=Number(new URLSearchParams(location.search).get('step')||0);$('seek').max=d.episodes[0].count-1;$('seek').value=Math.max(0,Math.min(+$('seek').max,Number.isFinite(wanted)?Math.floor(wanted):0));show()}).catch(e=>$('status').textContent=String(e));
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, view, **kwargs):
        self.view=view
        super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            url=urlparse(self.path)
            if url.path=='/':
                payload,kind=PAGE.encode(),'text/html; charset=utf-8'
            elif url.path=='/catalog':
                payload,kind=json.dumps(self.view.catalog()).encode(),'application/json'
            elif url.path=='/frame':
                q=parse_qs(url.query)
                payload=self.view.frame(int(q.get('episode',['0'])[0]),int(q.get('step',['0'])[0]),
                                        int(q.get('slot',['9'])[0]),bool(int(q.get('after',['0'])[0])))
                kind='image/png'
            else:
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        except (ValueError,KeyError,IndexError,FileNotFoundError) as exc:
            self.send_error(400,str(exc))

    def log_message(self,*args):
        pass


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--port',type=int,default=8766)
    p.add_argument('--export-frame',type=Path,help='write a PNG and exit (no browser needed)')
    p.add_argument('--episode',type=int,default=0)
    p.add_argument('--step',type=int,default=0)
    p.add_argument('--slot',type=int,default=9)
    p.add_argument('--next-observation',action='store_true')
    a=p.parse_args();view=DatasetView(a.dataset)
    if a.export_frame:
        with a.export_frame.open('xb') as f:f.write(view.frame(a.episode,a.step,a.slot,a.next_observation))
        print(a.export_frame);return
    server=ThreadingHTTPServer(('127.0.0.1',a.port),partial(Handler,view=view))
    print(f'Open http://127.0.0.1:{server.server_port} | read only | Ctrl-C to stop',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':
    main()

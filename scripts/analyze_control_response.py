#!/usr/bin/env python3
from pathlib import Path
import json, hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

import argparse
parser=argparse.ArgumentParser(description='Offline command/EEF response analysis; no ROS or SDK connection')
parser.add_argument('recording', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--receiver-log', type=Path)
args=parser.parse_args()
source=args.recording.resolve()
out=args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
blob=source.read_bytes();r=json.loads(blob);rows=r['rows']
c=[q for q in rows if q['kind']=='manual_command']
e=[q for q in rows if q['kind']=='eef_feedback']
j=[q for q in rows if q['kind']=='joint_feedback']
tc=np.array([q['t_s'] for q in c]);cmd=np.array([q['data'] for q in c],float)
te=np.array([q['t_s'] for q in e]);p=np.array([q['position_m'] for q in e])*1000
tj=np.array([q['t_s'] for q in j]);jv=np.degrees([q['velocities_rad_s'][:7] for q in j])
assert all(np.all(np.diff(t)>0) for t in (tc,te,tj))
assert np.isfinite(cmd).all() and np.isfinite(p).all() and np.isfinite(jv).all()
rate=r['receiver_parameters']['manual_command_rate']
# Local receive timeline; finite difference over 100 ms reduces position noise.
grid=np.arange(max(tc[0],te[0])+.1,min(tc[-1],te[-1])-.1,.01)
v=(np.interp(grid+.05,te,p[:,0])-np.interp(grid-.05,te,p[:,0]))/.1
joint_speed=np.max(np.abs(jv),axis=1)
active=np.abs(cmd[:,0])>1e-9
starts=np.flatnonzero(active & ~np.r_[False,active[:-1]])
stops=np.flatnonzero(~active & np.r_[False,active[:-1]])

def sustained_time(ts,condition,lo,hi,duration):
    for i in np.flatnonzero((ts>=lo)&(ts<=hi-duration)&condition):
        k=np.searchsorted(ts,ts[i]+duration,side='left')
        if k<len(ts) and np.all(condition[i:k+1]):return float(ts[i])
    return None

def gap_stats(ts):
    ds=np.diff(ts)*1000
    return dict(count=len(ts),median_ms=float(np.median(ds)),p95_ms=float(np.percentile(ds,95)),max_ms=float(np.max(ds)))

result=[]
for n,(aidx,bidx) in enumerate(zip(starts,stops),1):
    a,x_zero=tc[aidx],tc[bidx];sign=float(np.sign(cmd[aidx,0]))
    next_index=int(starts[n]) if n<len(starts) else len(tc)
    next_a=tc[next_index] if next_index<len(tc) else te[-1]
    last_nonzero=np.flatnonzero(np.any(cmd[aidx:next_index]!=0,axis=1))[-1]+aidx
    zero_index=last_nonzero+1
    assert zero_index < next_index
    b=tc[zero_index]
    baseline=float(np.median(p[(te>=a-.3)&(te<a),0]))
    onset=sustained_time(grid,(np.interp(grid,te,p[:,0])-baseline)*sign>=.1,a,b,.1)
    stop_times={}
    for threshold in (.2,.5,1.):
        t=sustained_time(grid,np.abs(v)<threshold,b,next_a,.2)
        stop_times[str(threshold)]=None if t is None else t-b
    jt=sustained_time(tj,joint_speed<.15,b,next_a,.2)
    # Use an early post-stop plateau, avoiding the next commanded movement.
    settle=min(b+2.,next_a-.25)
    end=float(np.median(p[(te>=settle-.2)&(te<=settle),0]))
    x0=float(np.interp(b,te,p[:,0]))
    result.append(dict(pulse=n,direction='forward' if sign>0 else 'backward',
                       command_start_s=float(a),command_x_zero_s=float(x_zero),command_zero_s=float(b),duration_s=float(x_zero-a),
                       onset_delay_s=None if onset is None else onset-a,
                       x_velocity_at_zero_mm_s=float(np.interp(b,grid,v)),
                       stop_delay_by_speed_threshold_s=stop_times,
                       joint_stop_delay_s=None if jt is None else jt-b,
                       x_travel_after_zero_05s_mm=float(np.interp(b+.5,te,p[:,0])-x0),
                       x_travel_after_zero_2s_mm=end-x0,
                       command_x_peak_mm_s=float(np.max(np.abs(cmd[aidx:bidx,0]))*rate)))

# Fit only waveform alignment, not transport latency: position finite difference
# and input ramps / dynamics make this distinct from a hardware delay measurement.
u=cmd[np.maximum(0,np.searchsorted(tc,grid,side='right')-1),0]*rate
lags=np.arange(0,.501,.01);scores=[]
for lag in lags:
    ix=np.maximum(0,np.searchsorted(tc,grid-lag,side='right')-1)
    shifted=cmd[ix,0]*rate
    mask=(grid>3)&((np.abs(shifted)>.2)|(np.abs(v)>.2))
    scores.append(float(np.corrcoef(shifted[mask],v[mask])[0,1]))
best=int(np.argmax(scores))
report=dict(source=str(source),source_sha256=hashlib.sha256(blob).hexdigest(),
            record_result=r['result'],record_errors=r['errors'],
            receive_span_s=float(rows[-1]['t_s']-rows[0]['t_s']),
            gaps={k:gap_stats(t) for k,t in [('manual_command',tc),('joint_feedback',tj),('eef_feedback',te)]},
            parameters=r['receiver_parameters'],pulses=result,
            analysis_definitions=dict(onset='signed X displacement >=0.1 mm from preceding 0.3 s median, sustained 0.1 s',
                stop='absolute X velocity below threshold sustained 0.2 s; velocity uses centered 100 ms position difference',
                joint_stop='max absolute joint velocity of left 7 joints <0.15 deg/s sustained 0.2 s',
                zero='first received all-six-zero command after the final nonzero command before the next main X pulse',
                timestamps='local monotonic subscriber receive times, not hardware release or SDK command times'),
            waveform_alignment=dict(best_lag_s=float(lags[best]),correlation=scores[best],meaning='waveform alignment only, not pure network/SDK delay'),
            limitations=['No sender hardware input time, SDK accepted target or send times',
                         'Four X pulses lasted 1.83-3.12 s, not requested half-second steps',
                         'Nonzero Y/Z and rotation components coexist; not a pure-X controlled trial',
                         'No receiver_log or receipt rows; absence does not prove zero SDK errors',
                         'Physical release timing and on-site observation are unknown',
                         'Stop delays depend on threshold; centered finite difference smooths over +/-50 ms'])
for pulse in result:
    t=np.arange(pulse['command_start_s'],pulse['command_zero_s'],.01)
    sign=1 if pulse['direction']=='forward' else -1
    pulse['estimated_x_speed_peak_mm_s']={str(window):float(np.max(sign*(np.interp(t+window/2,te,p[:,0])-np.interp(t-window/2,te,p[:,0]))/window)) for window in (.05,.1,.2)}
if args.receiver_log is not None:
    log_bytes=args.receiver_log.read_bytes()
    log_text=log_bytes.decode()
    report['receiver_log_audit']=dict(path=str(args.receiver_log.resolve()),sha256=hashlib.sha256(log_bytes).hexdigest(),sdk_rejected_count=log_text.count('SDK_REJECTED'),warn_error_count=sum('[WARN]' in line or '[ERROR]' in line for line in log_text.splitlines()),scope='Supplied receiver log only; unlogged SDK send failures are not measured')
(out/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

import subprocess
font_path=subprocess.check_output(['fc-match','-f','%{file}','Noto Sans CJK SC'],text=True).strip()
font_manager.fontManager.addfont(font_path)
plt.rcParams['font.family']=font_manager.FontProperties(fname=font_path).get_name()
plt.rcParams['axes.unicode_minus']=False
fig,ax=plt.subplots(3,1,figsize=(13,11),constrained_layout=True)
fig.suptitle('指令与末端反馈：四段前后运动',fontsize=17,fontweight='bold')
ax[0].step(tc,cmd[:,0]*rate,where='post',label='指令 X 速度（名义增量 × 10 Hz）',color='#2563eb',lw=1.6)
ax[0].plot(grid,v,label='反馈 X 速度（位置差分，100 ms 窗口）',color='#d97706',lw=1.4)
ax[0].set_ylabel('速度 (mm/s)');ax[0].legend(loc='upper right');ax[0].set_xlim(1.8,31.6)
ax[1].plot(te,p[:,0]-p[0,0],color='#0f766e',label='反馈 X 位置相对初始值')
ax[1].set_ylabel('位移 (mm)');ax[1].set_xlabel('记录器时间 (s)');ax[1].set_xlim(1.8,31.6);ax[1].legend(loc='upper right')
for item in result:
    a,b=item['command_start_s'],item['command_zero_s']
    for axis in ax[:2]:
        axis.axvspan(a,b,color='#64748b',alpha=.09)
        axis.axvline(b,color='#64748b',lw=.8,ls='--')
    ax[0].text((a+b)/2,21,str(item['pulse']),ha='center',color='#475569')
    sign=1 if item['direction']=='forward' else -1
    rel=np.arange(-.25,1.01,.01)
    ax[2].plot(rel,sign*np.interp(b+rel,grid,v),label=f"第{item['pulse']}段 / "+('前进' if sign==1 else '后退'))
ax[2].axvline(0,color='#111827',lw=1,ls='--',label='收到全零指令')
ax[2].axhline(.5,color='#94a3b8',ls=':',label='0.5 mm/s 阈值')
ax[2].set_xlim(-.25,1.);ax[2].set_xlabel('距收到全零指令的时间 (s)')
ax[2].set_ylabel('沿原运动方向速度 (mm/s)');ax[2].legend(loc='upper right',ncol=2)
for axis in ax:axis.grid(alpha=.2)
fig.text(.5,-.008,'时间为本机收到消息的时间；无 SDK 目标或硬件松手时间。灰色区间为主要动作段。',ha='center',fontsize=10)
fig.savefig(out/'response.png',dpi=170,bbox_inches='tight')
plt.close(fig)
print(json.dumps(report,ensure_ascii=False,indent=2))
print('PLOT',out/'response.png')

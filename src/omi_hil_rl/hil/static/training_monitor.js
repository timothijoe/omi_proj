'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const number = (value, digits=0) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumFractionDigits:digits,minimumFractionDigits:digits}) : '—';
const stamp = ns => ns ? new Date(ns/1e6).toLocaleString('zh-CN', {hour12:false}) : '—';
const facts = rows => '<div class="facts">'+rows.map(([name,value,wide])=>`<div class="fact ${wide?'wide':''}"><label>${esc(name)}</label><b>${esc(value)}</b></div>`).join('')+'</div>';
const stateNames = {TIMING_WARNING:'时序告警（仍采用）',LIVE:'实时',CLOSED:'已退出',FAILED:'异常退出',STALE:'心跳过期',PROGRESS_STALE:'主循环未推进',HISTORICAL:'历史快照',UNKNOWN:'未知',CLOCK_AHEAD:'时钟异常',MISSING:'未收到',REJECTED:'输入拒绝'};
const phaseNames = {INITIALIZING:'初始化',WAIT_START:'等待 Start',LOADING:'加载策略',ACTIVE:'回合进行中',SAVING:'保存与校验',EPISODE_RECORDED:'本地保存完成',EPISODE_COMMITTED:'训练片段已提交',PAUSED:'故障暂停',CLOSED:'已退出',TRAINING:'训练中',IMPORTING:'导入 / 扫描',WAITING:'等待训练数据',FAILED:'异常退出'};
function badge(el,state){el.className='pill '+(state==='LIVE'?'good':['FAILED','REJECTED'].includes(state)?'bad':['STALE','PROGRESS_STALE','CLOCK_AHEAD','TIMING_WARNING'].includes(state)?'warn':'unknown');el.textContent=stateNames[state]??state}
function pill(state){return `<span class="pill ${state==='LIVE'?'good':['REJECTED','FAILED'].includes(state)?'bad':['STALE','CLOCK_AHEAD','TIMING_WARNING'].includes(state)?'warn':'unknown'}">${esc(stateNames[state]??state)}</span>`}
let current, paused=false, chartPoints=[], lastMetricKey=null, reviewEpisode=null, reviewIndex=0, tickSequence=0;

function render(d){
  current=d;
  $('previews').classList.remove('stale-visual');
  const a=d.actor.data,l=d.learner.data,p=d.pipeline,w=d.weights,arb=a.arbitration??{},r=a.receiver??{},metrics=l.metrics??l;
  const live=d.actor.live||d.learner.live;
  badge($('connection'),live?'LIVE':'HISTORICAL');
  $('refresh-time').textContent='读取时间 '+stamp(d.now_ns);
  $('run-path').textContent=d.run;
  const warnings=[];
  if(!d.actor.live)warnings.push('Actor：'+(stateNames[d.actor.state]??d.actor.state));
  if(!d.learner.live)warnings.push('Learner：'+(stateNames[d.learner.state]??d.learner.state));
  if(p.pending)warnings.push(`${p.pending} 条 transition 等待导入`);
  if(w.version_gap>0)warnings.push(`已发布与已加载版本相差 ${w.version_gap} 次 Critic 更新`);
  if(d.errors.length)warnings.push(`${d.errors.length} 项文件读取异常`);
  $('notice').className='notice'+(warnings.length?' warning':'');
  $('notice').textContent=warnings.length ? warnings.join(' · ')+(live?'':'。下方为保存记录；不能据此判断进程正在运行。') : '状态通道已连接。逐项确认输入、回执和数据交接；链路正常与策略成功率分别评估。';
  const stages=[['01 · 原始周期',p.ticks,'已完成回合的审计 tick'],['02 · 校验有效',p.transitions,`可用率 ${p.usable_fraction===null?'—':number(p.usable_fraction*100,1)+'%'}`],['03 · 片段提交',p.ready,'ready 标记累计条数'],['04 · 已导入',p.imported,`待导入 ${number(p.pending)} 条`],['05 · Learner',l.update??metrics.update,'Critic 更新计数'],['06 · Actor 加载',w.loaded,'实际运行策略版本']];
  $('pipeline').innerHTML=stages.map(([label,value,note])=>`<div class="stage"><small>${esc(label)}</small><strong>${number(value)}</strong><span>${esc(note)}</span></div>`).join('');
  badge($('actor-badge'),d.actor.state);badge($('learner-badge'),d.learner.state);
  $('actor-body').innerHTML=facts([['阶段',phaseNames[a.phase]??a.phase],['剩余时间',a.phase==='ACTIVE'?number(a.remaining_s,1)+' s':'—'],['控制来源',a.phase==='ACTIVE'?(arb.source==='human'?'人工 / RB':arb.source==='policy'?'Policy':'—'):'回合外 / 最近记录'],['仲裁模式',({'after-inference':'推理完成后仲裁',immediate:'立即人工接管'})[a.arbitration_mode??arb.mode]??'未记录'],['门控',arb.gate],['手柄 / RB',a.gamepad?(a.gamepad.connected?'已连接':'断开')+' / '+(a.gamepad.rb?'按住':'松开'):'—'],['已完成有效回合',a.complete_episodes],['进度更新年龄',number(d.actor.progress_age_s,1)+' s'],['审计队列',a.audit_queue],['当前回合',a.episode,true]]);
  $('action-vector').innerHTML=['dx','dy','dz','A','B','C'].map((name,i)=>`<div><small>${name}</small><b>${number(arb.wire_action?.[i],4)}</b></div>`).join('');
  $('action-vector').classList.toggle('stale-visual',!d.actor.live||a.phase!=='ACTIVE');
  $('receiver-body').innerHTML=facts([['最近回执',r.status],['接收端接受',r.accepted===undefined?'—':r.accepted?'是':'否'],['实际运动确认',r.execution_confirmed===true?'回执声明已确认':'未确认'],['回执记录年龄',r.observed_ns?number((d.now_ns-r.observed_ns)/1e9,1)+' s':'—'],['命令 ID',r.command_id??arb.command_id,true]]);
  const guard=a.protection??{},guardAge=guard.observed_ns?(d.now_ns-guard.observed_ns)/1e9:null;
  const guardState=!d.actor.live||guardAge===null?'未知':guardAge>1?'状态过期':guard.enabled===false?'已关闭':guard.state??'未知';
  $('receiver-body').innerHTML+=facts([['触觉保护（只读状态）',guardState],['保护原因',guard.reason??'未收到状态；不据此判断开关'],['模型 / 人工通道',`${a.receiver_routes?.policy_topic??'—'} / ${a.receiver_routes?.manual_topic??'—'}`,true],['最近本地保存耗时',number(a.save_seconds,2)+' s']]);
  const waitingNames={waiting_for_online:'在线有效 transition 不足',waiting_for_demo:'示范数据不足',waiting_for_update_budget:'当前数据的更新额度已用完，等待新增数据'};
  $('learner-body').innerHTML=facts([['阶段',phaseNames[l.phase]??(l.waiting?'等待数据':l.phase)],['等待原因',waitingNames[l.waiting_reason]??l.waiting_reason??(l.waiting_for_online?'在线数据不足':'—')],['Critic 更新',l.update??metrics.update],['本进程 Actor 更新',l.actor_updates_this_process],['本次更新耗时',number(l.update_ms,1)+' ms'],['实际更新频率',number(l.update_hz,1)+' Hz'],['扫描 / 导入耗时',number(l.import_ms,1)+' ms'],['Critic 预热剩余',l.warmup_remaining??l.critic_warmup_remaining],['本进程新导入',number(l.imported_this_process)+' 条'],['本进程 RL 更新 / 新导入',l.imported_this_process>0?number(l.rl_updates_this_process/l.imported_this_process,2):'暂无新增数据'],['进度更新年龄',number(d.learner.progress_age_s,1)+' s']]);
  $('loss-values').textContent=`actor_loss ${number(metrics.actor_loss,6)} · BC loss ${number(metrics.bc_loss,6)} · α ${number(metrics.alpha,6)} · BC drift MSE ${number(metrics.bc_reference_mse,6)}`;
  const metricKey=(l.session??'historical')+':'+metrics.update;
  if(metricKey!==lastMetricKey&&Number.isFinite(metrics.critic_loss)){
    if(lastMetricKey&&!lastMetricKey.startsWith((l.session??'historical')+':'))chartPoints=[];
    chartPoints.push({step:metrics.update,value:metrics.critic_loss});chartPoints=chartPoints.slice(-120);lastMetricKey=metricKey;
  }
  drawChart(d.learner.live);
  $('weights').innerHTML=[['Learner 已训练',w.trained],['最近发布确认',w.published],['Actor 已加载',w.loaded]].map(([label,value])=>`<div class="version"><span>${label}</span><b>${number(value)}</b></div>`).join('');
  $('weight-details').innerHTML=facts([['检查间隔',w.reload_episodes?`每 ${w.reload_episodes} 个有效回合`:'—'],['距下次检查',w.episodes_until_check===null?'—':`${w.episodes_until_check} 个有效回合`],['最近发布',stamp(w.published_ns)],['版本间隔',number(w.version_gap)],['加载异常',a.reload_error??'未记录',true]])+'<p class="footnote">版本对应 Critic 更新次数；预热期间版本增加可不改变 Actor。历史文件没有发布心跳时显示未知。</p>';
  $('replay-backend').textContent=d.replay.backend??d.session.replay_backend??'未记录';
  const streams=d.replay.streams;
  $('replay').innerHTML=facts([['固定初始示范',number(streams.initial_demonstration)],['在线池占用',number(streams.online)],['在线人工干预',number(streams.intervention)],['示范池合计',number(streams.demonstration)],['待导入片段',number(p.pending_segments)],['最长等待',number(p.oldest_pending_s,1)+' s'],['成功奖励标签',number(p.success_labels)],['本机可用空间',number(d.disk_free_gib,1)+' GiB']])+`<div class="bar"><div style="width:${Math.max(0,Math.min(100,(p.usable_fraction??0)*100))}%"></div></div><p class="footnote">在线人工干预同时在两流中出现，不叠加为独立经验。池占用与累计导入分别计数。</p>`;
  if(d.replay.cache){const c=d.replay.cache,g=v=>number(v/2**30,3)+' GiB';$('replay').innerHTML+=facts([['内存独立样本',number(c.resident_unique)],['磁盘在线经验',number(c.catalog_online)],['磁盘初始示范',number(c.catalog_seed)],['磁盘人工干预',number(c.catalog_interventions)],['数据管线占用',g(c.managed_bytes)],['管线峰值 / 上限',g(c.peak_managed_bytes)+' / '+g(c.memory_limit_bytes)],['驻留缓存',g(c.resident_bytes)],['待登记回合',number(c.pending_episodes)],['后台加载',c.loader_error??(c.loader_busy?'进行中':'空闲'),true]])+'<p class="footnote">驻留数据供训练采样；磁盘目录保留全量经验。内存预算包括数据管线，不等于整个进程RSS。</p>';}
  $('excluded').innerHTML=Object.entries(p.excluded).sort((x,y)=>y[1]-x[1]).map(([reason,count])=>`<div class="reason"><span>${esc(reason)}</span><b>${number(count)}</b></div>`).join('')||'<p class="footnote">尚无已完成回合的排除统计。</p>';
  if(Object.keys(p.timing_diagnostics??{}).length) $('excluded').innerHTML+='<p class="footnote">时序诊断（新流程仅记录，不据此排除数据）：</p>'+Object.entries(p.timing_diagnostics).map(([reason,count])=>`<div class="reason"><span>${esc(reason)}</span><b>${number(count)}</b></div>`).join('');
  renderSensors(d);
  $('episode-count').textContent=d.episodes.length;
  renderEpisodes();
  $('event-list').innerHTML=d.events.length?d.events.map(e=>`<div class="event"><time>${esc(stamp(e.time_ns))}</time><span class="event-role">${esc(e.role)}</span><span class="event-text">${esc(e.kind)} · ${esc(e.phase??(e.version!==undefined?'v'+e.version:e.count!==undefined?e.count+' 条':e.error??''))}</span></div>`).join(''):'<div class="empty">该会话尚无监控事件。已有历史审计可在“回合与数据审阅”中查看。</div>';
  $('diagnostics').textContent=JSON.stringify({session:d.session,actor_source:d.actor.source,learner_source:d.learner.source,replay_clean:d.replay.clean,capacities:d.replay.capacities,errors:d.errors,actor_error:a.error,learner_error:l.error,sensor_monitor_error:a.sensor_monitor_error,preview_error:a.preview_error,writer_errors:[a.writer_error,l.writer_error]},null,2);
}

function renderSensors(d){
  const a=d.actor.data,rows=a.sensors??[],obs=a.observation??{};
  const sensorState=!d.actor.live?d.actor.state:!rows.length?'UNKNOWN':rows.every(s=>s.state==='LIVE')?'LIVE':obs.timing_diagnostic_only&&obs.ready?'TIMING_WARNING':'REJECTED';
  badge($('sensor-badge'),sensorState);
  $('observation-state').innerHTML=facts([['Actor 模型输入',d.actor.live?(obs.ready?'可用':'不可用'):'当前未知'],['历史有效槽位',obs.history_mask?`${obs.history_mask.filter(Boolean).length}/10`:'—'],['当前匹配候选推理',number(obs.inference_ms,2)+' ms'],['EEF xyz',obs.eef_xyz_xyzw?obs.eef_xyz_xyzw.slice(0,3).map(v=>number(v,4)).join(' / '):'—'],['窗口原因',obs.ready?(obs.timing_diagnostic_only?'latest 已构造；时序仅诊断':'完整窗口已构造'):obs.reason,true]]);
  $('sensors').innerHTML=rows.length?rows.map(s=>`<tr><td>${esc(s.key)}<small>${esc(s.topic)}</small></td><td>${pill(d.actor.live?s.state:'STALE')}</td><td>${number(s.hz,1)} Hz</td><td>${number(s.receive_age_ms,1)} ms</td><td>${number(s.header_age_ms,1)} ms</td><td>${number(s.received)} / ${number(s.accepted)}</td><td>${esc(s.reason??'—')}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">未收到 Actor 传感器遥测。更新代码后重启训练入口会自动报告；监控页面自身不启动设备。</td></tr>';
  const names={rgb:'外部相机 · 策略 ROI',wrist_rgb:'腕部相机 · 策略 ROI',a_deformation:'A · deformation',a_shear:'A · shear',a_depth:'A · depth',b_deformation:'B · deformation',b_shear:'B · shear',b_depth:'B · depth'};
  $('previews').innerHTML=Object.entries(a.preview?.images??{}).filter(([,src])=>/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(src)).map(([key,src])=>`<div class="preview ${d.actor.live?'':'stale-visual'}"><label>${esc(names[key]??key)}</label><img src="${src}" alt="${esc(names[key]??key)}"></div>`).join('');
  $('preview-note').textContent=a.preview?`${d.actor.live?'最近完整模型输入':'历史输入快照'} · 预览生成于 ${number((d.now_ns-a.preview.generated_ns)/1e9,1)} s 前 · reference_ns ${a.preview.reference_ns} · 触觉箭头隔点采样为 12×8，固定尺度；depth 范围 0..0.3，SDK 数值未作物理标定。`:'没有完整模型输入预览。';
  $('sensor-bridge').hidden=!d.sensor_bridge;
  if(d.sensor_bridge){$('bridge-note').textContent=(d.sensor_bridge.live?'实时':'过期快照')+' · 独立看板，不代表 Actor 输入门控通过';$('bridge-image').src='/sensor-dashboard.png?t='+d.now_ns;$('bridge-image').classList.toggle('stale-visual',!d.sensor_bridge.live)}
}

function renderEpisodes(){
  if(!current)return;
  const filter=$('episode-filter').value;
  const rows=current.episodes.filter(e=>filter==='all'||filter==='valid'&&e.transitions>0||filter==='excluded'&&Object.keys(e.excluded).length>0||filter==='success'&&e.success||filter==='unfinished'&&!e.audited);
  $('episode-table').innerHTML=rows.length?rows.map(e=>`<tr><td title="${esc(e.id)}">${esc(e.id.slice(0,12))}</td><td>${esc(e.audited?e.reason:'中断 / 暂存')}<small>${esc(Object.entries(e.excluded).map(([k,v])=>`${k}: ${v}`).join(' · '))}</small></td><td>${number(e.ticks)}</td><td>${number(e.transitions)}</td><td>${e.success_label_recorded?'已记录':e.success?'标记成功，未记录奖励':'未标记'}</td><td>${number(e.policy_version)}</td><td><button data-review="${esc(e.id)}" ${e.ticks?'':'disabled'}>逐帧查看 ↗</button></td></tr>`).join(''):'<tr><td colspan="7" class="empty">没有匹配的回合。</td></tr>';
}

function drawChart(live){
  const canvas=$('loss-chart'),ctx=canvas.getContext('2d'),width=canvas.width,height=canvas.height;
  ctx.clearRect(0,0,width,height);ctx.strokeStyle='#29373e';ctx.lineWidth=1;
  for(let i=1;i<4;i++){ctx.beginPath();ctx.moveTo(0,i*height/4);ctx.lineTo(width,i*height/4);ctx.stroke()}
  $('chart-caption').textContent=chartPoints.length>1?`本页观察 ${chartPoints.length} 点${live?'':' · 历史 / 过期'}`:chartPoints.length?'仅一个保存值，无趋势结论':'等待实时采样';
  if(!chartPoints.length)return;
  const values=chartPoints.map(p=>p.value),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||Math.max(Math.abs(hi)*.1,1e-6);
  const points=chartPoints.map((p,i)=>[chartPoints.length===1?width/2:15+i*(width-30)/(chartPoints.length-1),height-15-(p.value-lo)/span*(height-30)]);
  ctx.strokeStyle=live?'#81d5af':'#8d9fa5';ctx.lineWidth=2;ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();
  const [x,y]=points.at(-1);ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#8d9fa5';ctx.font='11px monospace';ctx.fillText(number(hi,6),10,12);
}

async function poll(){
  if(!paused){
    const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),4000);
    try{const response=await fetch('/api/state',{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error(await response.text());const data=await response.json();if(!paused)render(data)}
    catch(error){if(!paused){badge($('connection'),'STALE');$('notice').className='notice error';$('notice').textContent='监控连接中断；以下为上次显示数据。'+String(error);badge($('actor-badge'),'STALE');badge($('learner-badge'),'STALE');badge($('sensor-badge'),'STALE');$('previews').classList.add('stale-visual');}}
    finally{clearTimeout(deadline)}
  }
  setTimeout(poll,1000);
}
$('pause').onclick=()=>{paused=!paused;$('pause').textContent=paused?'继续刷新':'暂停刷新';if(paused){$('connection').textContent='刷新已暂停';$('connection').className='pill warn';$('notice').className='notice warning';$('notice').textContent='页面刷新已暂停，显示冻结快照；Actor 和 Learner 继续按原设置运行。'}else $('previews').classList.remove('stale-visual')};
document.querySelectorAll('.tab').forEach(button=>button.onclick=()=>{document.querySelectorAll('.panel').forEach(panel=>panel.hidden=panel.id!==button.dataset.panel);document.querySelectorAll('.tab').forEach(tab=>tab.classList.toggle('selected',tab===button))});
$('episode-filter').onchange=renderEpisodes;
for(let slot=0;slot<10;slot++)$('history-slot').add(new Option(`${slot} · ${(slot-9)*100} ms`,slot));$('history-slot').value=9;
$('episode-table').onclick=event=>{const button=event.target.closest('[data-review]');if(!button)return;reviewEpisode=current.episodes.find(e=>e.id===button.dataset.review);reviewIndex=0;$('tick-seek').max=reviewEpisode.ticks-1;$('tick-seek').value=0;$('review-title').textContent='回合 '+reviewEpisode.id;$('review').showModal();showTick()};
$('close-review').onclick=()=>{tickSequence++;$('review').close()};
$('tick-prev').onclick=()=>moveTick(-1);$('tick-next').onclick=()=>moveTick(1);
$('tick-seek').oninput=()=>{reviewIndex=+$('tick-seek').value;showTick()};$('history-slot').onchange=showTick;
function moveTick(delta){reviewIndex=Math.max(0,Math.min(reviewEpisode.ticks-1,reviewIndex+delta));$('tick-seek').value=reviewIndex;showTick()}
document.addEventListener('keydown',event=>{if(!$('review').open||event.target.closest('input,select')||!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();moveTick(event.key==='ArrowLeft'?-1:1)});
async function showTick(){
  const sequence=++tickSequence,index=reviewIndex,episode=reviewEpisode;
  $('tick-position').textContent=`${index+1} / ${episode.ticks}`;$('tick-prev').disabled=index===0;$('tick-next').disabled=index===episode.ticks-1;$('review-state').textContent='读取周期…';
  $('tick-image').hidden=true;$('tick-empty').textContent='';
  try{
    const query=new URLSearchParams({episode:episode.id,index,slot:$('history-slot').value});const response=await fetch('/api/tick?'+query);if(!response.ok)throw Error(await response.text());const data=await response.json();if(sequence!==tickSequence)return;
    $('review-state').textContent=`${data.in_training?'已导出训练片段':'未进入训练片段'} · ${data.imported===null?'无导入标记':data.imported?'已导入 Learner':'等待导入'} · ${data.pairing_is_diagnostic?'配对仅诊断：':''}${data.pairing}`;
    const {image,...details}=data;$('tick-details').textContent=JSON.stringify(details,null,2);$('tick-image').hidden=!image;if(image)$('tick-image').src=image;$('tick-empty').textContent=image?'':'此周期无完整观测图像；命令与审计元数据仍保留。';
  }catch(error){if(sequence!==tickSequence)return;$('review-state').textContent='读取失败';$('tick-details').textContent=String(error)}
}
poll();

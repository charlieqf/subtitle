"""Build an offline video/transcript comparison page with no external resources."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/research-20261109'
tracks=json.loads((OUT/'review-tracks.json').read_text(encoding='utf-8'))
labels={'tencent-large-baseline':'腾讯大模型 2.0 · 原始识别后保守清理',
        'tencent-large-filter':'腾讯大模型 2.0 · 厂商语气词过滤',
        'tencent-standard-baseline':'腾讯普通版 · 无热词',
        'tencent-standard-hotwords':'腾讯普通版 · 医学热词',
        'tencent-large-hotwords':'腾讯大模型 2.0 · 医学热词',
        'aliyun-baseline':'阿里 FunASR · 无热词',
        'aliyun-hotwords':'阿里 FunASR · 医学热词'}
template='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>医学采访字幕对照</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#182839;font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}header{padding:20px 28px;background:#12283d;color:white}h1{font-size:22px;margin:0}header p{margin:4px 0 0;color:#c7d8e5;font-size:13px}main{padding:22px;display:grid;grid-template-columns:minmax(0,1.65fr) minmax(320px,1fr);gap:20px}.box{background:white;border-radius:10px;padding:18px;box-shadow:0 2px 12px #12283d0c}.video-wrap{position:relative;background:black;aspect-ratio:16/9}video{width:100%;height:100%}#caption{position:absolute;left:5%;right:5%;bottom:13%;text-align:center;color:white;font-size:clamp(17px,1.8vw,28px);line-height:1.5;text-shadow:2px 2px 2px black,-2px -2px 2px black,2px -2px 2px black,-2px 2px 2px black;pointer-events:none;white-space:pre-line}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0}select,button,input{font:inherit;border:1px solid #c7d3dc;border-radius:6px;padding:7px;background:white}button{cursor:pointer;color:#174c70}#cues{height:69vh;overflow:auto}.cue{padding:10px 12px;border-bottom:1px solid #e5ebf0;cursor:pointer;border-left:3px solid transparent}.cue.active{background:#e7f1f9;border-left-color:#2679aa}.time{font-size:12px;color:#637d91;font-variant-numeric:tabular-nums}.note{font-size:13px;color:#60788c}.warn{background:#fff6de;padding:12px;border-radius:6px;margin-top:14px}#clock{font-variant-numeric:tabular-nums}@media(max-width:900px){main{grid-template-columns:1fr}#cues{height:45vh}}
</style><header><h1>医学采访字幕对照</h1><p>同一视频 · 切换引擎结果 · 点击字幕跳转 · 导入校对后的 SRT</p></header><main>
<section class="box"><div class="video-wrap"><video id="video" controls preload="metadata" src="../../字幕模拟视频1.mp4"></video><div id="caption"></div></div>
<div class="toolbar"><select id="track"></select><select id="speed"><option value="1">1 倍速</option><option value="0.75">0.75 倍速</option><option value="0.5">0.5 倍速</option><option value="1.25">1.25 倍速</option></select><span id="clock">00:00.000</span></div>
<div class="toolbar"><button id="back">后退 2 秒</button><button id="forward">前进 2 秒</button><label>导入 SRT <input id="file" type="file" accept=".srt" style="max-width:220px"></label></div>
<div class="warn">重点复核：00:30 围绝经期；02:00 阶段的变化；02:46–03:17 内异症与类风湿的结果分歧。这里显示的是待校对的机器字幕。</div>
<p class="note">导入与播放均在本机进行。切换结果会保留视频位置。此页面用于对照检查，不会更改源视频或云端任务。时间偏移实验结果不能替代人工音字同步验收。</p><p id="status" class="note"></p></section>
<section class="box"><div id="cues"></div></section></main><script>
const tracks=__TRACKS__,labels=__LABELS__;
const video=document.getElementById('video'),caption=document.getElementById('caption'),select=document.getElementById('track'),list=document.getElementById('cues');
let cues=[],rows=[],active=-1;
function time(ms){let s=Math.floor(ms/1000);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+'.'+String(Math.round(ms)%1000).padStart(3,'0')}
function addOption(key,label){let o=document.createElement('option');o.value=key;o.textContent=label;select.append(o)}
Object.keys(tracks).forEach(k=>addOption(k,labels[k]||k));select.value='tencent-large-baseline';
function load(){cues=tracks[select.value];list.replaceChildren();rows=[];active=-1;for(let i=0;i<cues.length;i++){let c=cues[i],row=document.createElement('div'),stamp=document.createElement('div'),text=document.createElement('div');row.className='cue';stamp.className='time';stamp.textContent=(i+1)+' · '+time(c.start_ms)+' → '+time(c.end_ms);text.textContent=c.text;row.append(stamp,text);row.onclick=()=>{video.currentTime=Math.max(0,c.start_ms/1000-.15);video.play().catch(()=>{})};rows.push(row);list.append(row)}document.getElementById('status').textContent=cues.length+' 条字幕。';tick()}
function tick(){const ms=video.currentTime*1000,index=cues.findIndex(c=>c.start_ms<=ms&&ms<c.end_ms);caption.textContent=index>=0?cues[index].text:'';document.getElementById('clock').textContent=time(ms);if(index!==active){if(active>=0)rows[active].classList.remove('active');if(index>=0){rows[index].classList.add('active');rows[index].scrollIntoView({block:'nearest'})}active=index}}
select.onchange=load;video.ontimeupdate=tick;video.onseeked=tick;document.getElementById('speed').onchange=e=>video.playbackRate=Number(e.target.value);document.getElementById('back').onclick=()=>video.currentTime=Math.max(0,video.currentTime-2);document.getElementById('forward').onclick=()=>video.currentTime=Math.min(video.duration,video.currentTime+2);
document.getElementById('file').onchange=async e=>{try{let text=await e.target.files[0].text(),parsed=[];for(const block of text.replace(/^\\uFEFF/,'').replace(/\\r/g,'').trim().split(/\\n\\s*\\n/)){let lines=block.split('\\n'),m=lines[1].match(/^(\\d+):(\\d{2}):(\\d{2}),(\\d{3}) --> (\\d+):(\\d{2}):(\\d{2}),(\\d{3})$/);if(!m)throw Error('SRT 时间格式不正确');const ms=i=>((Number(m[i])*60+Number(m[i+1]))*60+Number(m[i+2]))*1000+Number(m[i+3]);parsed.push({start_ms:ms(1),end_ms:ms(5),text:lines.slice(2).join('\\n')})}tracks.imported=parsed;if(![...select.options].some(o=>o.value==='imported'))addOption('imported','导入的校对 SRT');select.value='imported';load()}catch(error){document.getElementById('status').textContent=error.message}};
load();</script></html>'''
page=template.replace('__TRACKS__',json.dumps(tracks,ensure_ascii=False).replace('<','\\u003c')).replace('__LABELS__',json.dumps(labels,ensure_ascii=False))
(OUT/'review.html').write_text(page,encoding='utf-8')
print(OUT/'review.html')

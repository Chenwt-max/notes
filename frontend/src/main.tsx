import React, {useEffect,useRef,useState,useMemo,useLayoutEffect} from 'react';
import {createRoot} from 'react-dom/client';
import gsap from 'gsap';
import {useGSAP} from '@gsap/react';
import {BookOpen,Film,Layers3,Subtitles,Settings2,ArrowUpRight,ArrowLeft,Play,Pause,Plus,Search,Download,Check,ChevronRight,ChevronDown,X,SlidersHorizontal,Clock3,HardDrive,ShieldCheck,Sparkles,ScanLine,RotateCcw,AlertCircle,Braces,Waves} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import './style.css';
import './studio.css';
import CourseCatalog from './CourseCatalog';
import VideoPath from './VideoPath';
import ResourceControls from './ResourceControls';
import TimingPanel from './TimingPanel';
import StudyPlayer from './StudyPlayer';
import QualityReview from './QualityReview';
import NoteReader from './NoteReader';
import ConfirmDialog,{type Confirmation} from './ConfirmDialog';
import DeleteButton from './DeleteButton';
import JobList from './JobList';
import ModelPreparation from './ModelPreparation';
import HandoutInput from './HandoutInput';
import RecoveryPanel from './RecoveryPanel';
import useVisiblePolling from './useVisiblePolling';
import AppearanceSettings from './AppearanceSettings';
import './study.css';
import './glass.css';
import './workspace.css';

gsap.registerPlugin(useGSAP);
type Any = Record<string,any>;
type Visual = {id:string;kind:string;image:string;start:number;end:number;capture_ts:number;ocr:string;formulas:Any[];flags:string[];quad:number[][]|null;content_id:string;layout:string;is_representative?:boolean;appearances?:Any[];document_page?:number;untimed?:boolean;api_display?:{keep:boolean;status:string;decisions:Any[]}};
const time=(s:number)=>`${Math.floor(s/3600)>0?`${Math.floor(s/3600)}:`:''}${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(Math.floor(s)%60).padStart(2,'0')}`;
const label:Any={queued:'等待处理',starting:'正在启动',running:'处理中',pause_requested:'正在暂停',paused:'已暂停',cancelled:'已取消',needs_attention:'需要检查',materials_ready:'素材已就绪',ready:'笔记已整理',delete_requested:'正在删除',delete_failed:'清理未完成'};
const kind:Any={slides:'课件',board:'板书',screen:'整屏画面'};
const busy=(status:string)=>['running','starting','queued','pause_requested','delete_requested'].includes(status);
async function api(url:string,method='GET',body?:unknown){const r=await fetch('/api'+url,{method,signal:method==='GET'?AbortSignal.timeout(30000):undefined,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw Object.assign(Error(typeof v.detail==='string'?v.detail:v.detail?.message||'操作未完成'),{detail:v.detail});return v;}
const art=(id:string,path:string)=>`/api/artifacts/${id}/${path}`;

function MathView({latex}:{latex:string}){let result='';try{result=katex.renderToString(latex,{throwOnError:true,trust:false,displayMode:true,strict:false,maxExpand:1000});}catch{return <p className="notice">公式未能正常显示，请对照原图或修订后保存。</p>;}return <div className="math" dangerouslySetInnerHTML={{__html:result}}/>;}

function DetailPage({title,children,close,wide=false}:{title:string;children:React.ReactNode;close:()=>void;wide?:boolean}){
 return <section className={`detail-page animate-in ${wide?'wide':''}`}><div className="detail-page-head"><button className="back-link" onClick={close}><ArrowLeft size={16}/>返回上一级</button><h1>{title}</h1></div>{children}</section>;
}

function Settings({close,notify,step,go,reduceMotion,changeMotion}:{close:()=>void;notify:(s:string)=>void;step:string;go:(s:string)=>void;reduceMotion:boolean;changeMotion:(value:boolean)=>void}){
 const [value,set]=useState<Any>();const [saving,setSaving]=useState(false),[loadError,setLoadError]=useState('');
 const load=async()=>{setLoadError('');try{set({...await api('/settings'),api_key:''});}catch(e){setLoadError((e as Error).message);}};
 useEffect(()=>{if(step&&!['appearance','storage'].includes(step))void load();},[step]);
 const field=(key:string,title:string,type='text',note='')=><label className="field">{title}<input type={type} value={value?.[key]??''} min="0" step="any" onChange={e=>set({...value,[key]:type==='number'?Number(e.target.value):e.target.value})}/>{note&&<small>{note}</small>}</label>;
 const names:Any={local:'本地识别',models:'模型配置',api:'文字整理接口',budget:'费用与用量',appearance:'界面与动效',storage:'存储与清理',resources:'资源与并发'};
 return <DetailPage title={names[step]||'设置'} close={()=>step==='models'?go('local'):step?go(''):close()}>{!step?<><div className="feature-grid">{[['local','本地识别','查看字幕、课件和公式模型',ScanLine],['resources','资源与并发','选择CPU/GPU、线程和课程并发',SlidersHorizontal],['api','文字整理接口','管理接口、模型名称及密钥',Settings2],['budget','费用与用量','设置人民币和 token 上限',ShieldCheck],['appearance','界面与动效','调整界面过渡与动态反馈',Waves],['storage','存储与清理','查看精简结果并清理无引用缓存',HardDrive]].map(([id,title,desc,Icon])=><button className="feature-card" key={id as string} onClick={()=>go(id as string)}><Icon size={24}/><h2>{title as string}</h2><p>{desc as string}</p><ArrowUpRight size={17}/></button>)}</div></>:step==='storage'?<Storage notify={notify}/>:step==='appearance'?<AppearanceSettings reduced={reduceMotion} change={changeMotion}/>:value?<form className="settings-form" onSubmit={async e=>{e.preventDefault();setSaving(true);try{await api('/settings','PUT',value);notify('设置已保存');}catch(e){notify((e as Error).message);}finally{setSaving(false);}}}>
 {step==='local'&&<><p className="muted">字幕和课件筛选在本机完成，整理时 API 读取课件原图。</p><div className="model-summary"><b>Qwen3-ASR-1.7B</b><span>课堂语音与时间对齐</span><b>图像去重</b><span>合并重复与保留互补画面</span><b>{value.formula_model}</b><span>课件筛选与精简辅助</span></div><button type="button" onClick={()=>go('models')}>模型配置<ChevronRight size={16}/></button><button type="button" onClick={()=>go('resources')}>资源与并发<ChevronRight size={16}/></button></>}
 {step==='resources'&&<ResourceControls value={value} set={set}/>}
 {step==='models'&&<><p className="muted">本机提取字幕与筛选课件，文字和公式由多模态 API 看原图整理。</p><label className="field">课件筛选模型<input readOnly value={value.formula_model}/></label><p className="muted">0.9B · 为课件去重提供页面内容线索</p><div className="model-summary"><b>YOLOX-Tiny · {value.device==='cpu'?'CPU':'GPU'}</b><span>识别人像与遮挡</span><b>本地图像算法</b><span>去重、动画状态与完整性检查</span><b>Qwen3-ASR-1.7B</b><span>课堂转写与本地时间对齐</span></div><details className="context-help"><summary>识别范围与已有资料</summary><p>视频路线用 YOLOX 辅助排除教师遮挡，已有课件直接使用原页。本地图像去重后，PaddleOCR-VL 辅助分组；不再强制执行 RapidOCR 或本地公式提取。旧任务沿用原检查点。CPU/GPU 和并发在“资源与并发”中设置。</p></details></>}{step==='api'&&<><p className="muted">新任务默认在提取后整理学习笔记，按设置的费用上限调用此接口。</p>{field('base_url','接口地址','url','DeepSeek：https://api.deepseek.com')}{field('model','模型名称')}{field('api_key',value.has_key?'API 密钥（已设置，留空保留）':'API 密钥','password')}<label className="check"><input type="checkbox" checked={value.remember_key} onChange={e=>set({...value,remember_key:e.target.checked})}/>用 Windows 加密保存密钥</label><p className="muted">新任务会发送字幕与课件原图，请使用支持图片输入的模型（如 deepseek-flash）；视频与音频不上传。</p><label className="check"><input type="checkbox" checked={value.review_notes??true} onChange={e=>set({...value,review_notes:e.target.checked})}/>生成后复核笔记</label><p className="muted">整课资料就绪后统一整理和复核，再按知识主题划分章节。</p><details className="context-help"><summary>整理与复核说明</summary><p>整理直接读取课件原图，同时判断重复、非课件和动画终态；新图片流程的 DeepSeek 复核会开启低强度思考，按定义核算推导与例题；思考也计入复核输出上限和费用。整理、复核和整课分章累计受每份额度限制，缓存命中不重复收费。无法确认的页面保留，可在课件栏查看全部来源。</p></details></>}
 {step==='api'&&value.key_reentry_required&&<p className="notice">此账户无法解密之前保存的密钥，请重新填写；已有资料可以继续阅读。</p>}
 {step==='local'&&<button type="button" onClick={()=>location.hash='/prepare'}>模型准备与下载</button>}
 {step==='budget'&&<><p className="muted">每份笔记的整理、复核与分章共用总额度。</p><details className="context-help"><summary>单价与费用说明</summary><p>填写供应商当前人民币单价，可按谷时价格修改。新单价只影响后续调用，历史账目保留；超限时停止新请求。</p></details><div className="two">{field('input_price','输入单价（元 / 百万 token）','number')}{field('output_price','输出单价（元 / 百万 token）','number')}{field('budget_per_note','每份笔记最高费用（元）','number')}{field('max_output_tokens','整理输出上限','number')}{field('review_max_output_tokens','复核输出上限（含思考）','number')}{field('input_tokens_per_hour','每小时输入 token 上限','number')}{field('output_tokens_per_hour','每小时输出 token 上限','number')}</div><div className="notice"><ShieldCheck size={17}/>请求前预留费用，超时不自动重试。</div></>}
 {!['models','local'].includes(step)&&<button className="primary" disabled={saving}>{saving?'正在保存…':'保存设置'}</button>}</form>:loadError?<div className="settings-load-error" role="alert"><p>暂时无法读取设置</p><p className="muted">{loadError}</p><button onClick={()=>void load()}>重新读取</button></div>:<p role="status">正在读取设置…</p>}</DetailPage>;
}

function Storage({notify}:{notify:(s:string)=>void}){
 const [data,setData]=useState<Any>(),[cleaning,setCleaning]=useState(false),[loadError,setLoadError]=useState('');
 const load=async()=>{setLoadError('');try{setData(await api('/maintenance'));}catch(e){setLoadError((e as Error).message);}};useEffect(()=>{void load();},[]);
 const mb=(n:number)=>(n/1024/1024).toFixed(1)+' MB';
 return <div className="settings-form"><div className="form-emblem"><HardDrive size={25}/></div><h2 className="appearance-title">只保留需要的学习资料</h2><p className="muted">完成后自动清理无引用的重复图片和缓存。源视频、最终课件、字幕、修订及来源时间始终保留。</p>{data?<><div className="model-summary"><b>当前任务资料</b><span>{mb(data.bytes)}</span><b>可清理的无引用缓存</b><span>{mb(data.reclaimable)}</span></div><button disabled={cleaning||!data.reclaimable} onClick={async()=>{setCleaning(true);try{const r=await api('/maintenance/clean','POST',{});notify(`已清理 ${mb(r.deleted_bytes)}`);await load();}catch(e){notify((e as Error).message);}finally{setCleaning(false);}}}><HardDrive size={15}/>{cleaning?'正在检查引用并清理…':'清理无引用缓存'}</button><p className="muted">运行中的任务跳过清理。代表页、互补内容不会按文件日期盲目删除。</p></>:loadError?<div className="settings-load-error" role="alert"><p>暂时无法检查本地资料</p><p className="muted">{loadError}</p><button onClick={()=>void load()}>重新读取</button></div>:<p className="muted" role="status">正在检查本地资料…</p>}</div>;
}

function NewTask({library,close,refresh,notify,initial,regions,regionTime,request,refreshLibrary}:{library:Any[];close:()=>void;refresh:()=>void;notify:(s:string)=>void;initial?:Any;regions?:Any[];regionTime?:number;request:typeof api;refreshLibrary:()=>Promise<void>}){
 const [path,setPath]=useState(initial?.path||library[0]?.path||'');const [title,setTitle]=useState(initial?.title||'');const [scope,setScope]=useState('full');const [start,setStart]=useState(0);const [end,setEnd]=useState(2);const [organize,setOrganize]=useState(true);const [handout,setHandout]=useState<{mode:'video'|'file';path:string}>({mode:'video',path:''});const [saving,setSaving]=useState(false);
 return <DetailPage title={regions?'使用校准区域创建任务':'新建提取任务'} close={close}><p className="muted">选择本地视频。原视频保持原样，处理结果独立保存。</p><VideoPath request={api} added={async videos=>{await refreshLibrary();setPath(videos[0].path);}} notify={notify}/><form onSubmit={async e=>{e.preventDefault();setSaving(true);try{const created=await request('/jobs','POST',{path,title,windows:regions?initial?.windows:scope==='full'?undefined:[[start*60,end*60]],organize,handout_path:handout.mode==='file'?handout.path:undefined,regions,regions_capture_ts:regionTime});if(!created)return;refresh();close();notify('课程已加入处理队列');}catch(e){notify((e as Error).message);}finally{setSaving(false);}}}>
 <label className="field">视频文件<select value={path} onChange={e=>setPath(e.target.value)}>{library.map(v=><option key={v.path} value={v.path}>{v.name} · {time(v.duration)}</option>)}</select></label><label className="field">课程名称<input value={title} placeholder="例如：概率论 · 第一讲" onChange={e=>setTitle(e.target.value)}/></label>
 {!regions&&<><label className="field">处理范围<select value={scope} onChange={e=>setScope(e.target.value)}><option value="full">完整课时</option><option value="range">先处理一个片段</option></select></label>{scope==='range'&&<div className="two"><label className="field">开始（分钟）<input type="number" min="0" step="0.1" value={start} onChange={e=>setStart(+e.target.value)}/></label><label className="field">结束（分钟）<input type="number" min="0" step="0.1" value={end} onChange={e=>setEnd(+e.target.value)}/></label></div>}</>}
 {!regions&&<HandoutInput value={handout} onChange={setHandout}/>}<label className="check"><input type="checkbox" checked={organize} onChange={e=>setOrganize(e.target.checked)}/>提取完成后自动整理为学习笔记（按额度调用接口）</label><div className="notice"><HardDrive size={17}/>{handout.mode==='file'?'课件使用原文档页面，视频仅用于字幕与播放。':'自动保留课件、板书及整屏切换。区域不确定的画面会标记，供你核对。'}</div><button className="primary full" disabled={saving||!path||(handout.mode==='file'&&!handout.path.trim())}>{saving?'正在创建…':'开始本地处理'}<ArrowUpRight size={17}/></button></form></DetailPage>;
}

function Gallery({items,jobId,select}:{items:Visual[];jobId:string;select:(v:Visual)=>void}){
 const box=useRef<HTMLDivElement>(null);const [top,setTop]=useState(0);const [size,setSize]=useState({width:900,height:600});
 useLayoutEffect(()=>{if(!box.current)return;const observer=new ResizeObserver(([e])=>setSize({width:e.contentRect.width,height:e.contentRect.height}));observer.observe(box.current);box.current.scrollTop=0;setTop(0);return()=>observer.disconnect();},[items.length]);
 const cols=size.width>950?3:size.width>540?2:1;const row=352;const first=Math.max(0,Math.floor(top/row)-2);const last=Math.min(Math.ceil(items.length/cols),Math.ceil((top+size.height)/row)+2);
 return <div className="gallery-scroll" ref={box} onScroll={e=>setTop(e.currentTarget.scrollTop)}><div style={{height:Math.ceil(items.length/cols)*row,position:'relative'}}>{Array.from({length:Math.max(0,last-first)},(_,i)=>first+i).map(r=><div key={r} className="gallery-row" style={{top:r*row,gridTemplateColumns:`repeat(${cols},minmax(0,1fr))`}}>{items.slice(r*cols,r*cols+cols).map(v=><button className="visual-card" key={v.id} onClick={()=>select(v)}><div className="visual-image"><img loading="lazy" src={art(jobId,v.image)} alt={v.document_page?`原课件第 ${v.document_page} 页`:`${kind[v.kind]} ${time(v.capture_ts)}`}/><span className="image-time">{v.document_page?`第 ${v.document_page} 页`:time(v.capture_ts)}</span></div><div className="visual-meta"><span><i className={`dot ${v.kind}`}/>{kind[v.kind]}</span><span>{v.document_page?'原始文档':`${(v.end-v.start).toFixed(1)} 秒`}</span></div><div className="visual-caption">{v.ocr?.split('\n')[0]||'保留来源原图 · 可对照视频检查'}</div>{v.flags?.includes('region_proposal_needs_check')&&<span className="small-warning">区域待核对</span>}</button>)}</div>)}</div>{!items.length&&<div className="empty"><ScanLine size={36}/><h3>还没有符合条件的画面</h3><p>提取完成后，课件与板书会显示在这里。</p></div>}</div>;
}

function VisualDetail({visual,job,close,jump,refresh,notify,calibrate,view,open}:{visual:Visual;job:Any;close:()=>void;jump:(s:number)=>void;refresh:()=>void;notify:(s:string)=>void;calibrate:()=>void;view:string;open:(s:string)=>void}){
 const [edits,setEdits]=useState<Any>({});const [saving,setSaving]=useState(false);const [sources,setSources]=useState<Any[]>([]);useEffect(()=>{if(view==='appearances')api(`/jobs/${job.id}/sources?page=${visual.content_id}`).then(setSources).catch(e=>notify(e.message));},[view,visual.id]);const names:Any={text:'识别文字',formulas:'公式核对',appearances:'同组来源记录'};
 return <DetailPage wide title={`${names[view]||kind[visual.kind]} · ${visual.document_page?`第 ${visual.document_page} 页`:time(visual.capture_ts)}`} close={()=>view?open(''):close()}>
 {!view?<><img className="source-image" src={art(job.id,visual.image)} alt="来源画面"/><p className="muted">{visual.document_page?`原课件第 ${visual.document_page} 页 · 无视频时间戳`:`出现于 ${time(visual.start)}—${time(visual.end)}，截图于 ${time(visual.capture_ts)}。`}</p><div className="feature-grid compact">{[['text','识别文字',ScanLine],['formulas',`公式核对 · ${visual.formulas?.length||0}个`,Braces],['appearances','同组来源记录',Layers3]].map(([id,title,Icon])=><button className="feature-card" key={id as string} onClick={()=>open(id as string)}><Icon size={22}/><h2>{title as string}</h2><ArrowUpRight size={16}/></button>)}</div><div className="detail-actions">{!visual.untimed&&<button onClick={()=>jump(visual.capture_ts)}><Play size={15}/>回看这一刻</button>}{visual.quad&&<button onClick={calibrate}><SlidersHorizontal size={15}/>校准提取区域</button>}</div></>:view==='text'?<div className="text-detail"><img src={art(job.id,visual.image)} alt="文字来源"/><pre className="ocr-text">{visual.ocr||(visual.document_page?'本页没有可直接读取的文字层，原页已保留。':'本图未识别出文字，原图已保留。')}</pre></div>:view==='appearances'?<><p className="muted">{visual.document_page?'原文档页面按原序保留，不代表视频中的出现时刻。':'保留每次出现时间，重复位图按需从本地视频恢复。查看原图时才解码，不会重复调用识别模型。'}</p><div className="source-list">{sources.map(r=><div key={r.id}><span><b>{r.document_page?`原课件第 ${r.document_page} 页`:`${time(r.start)}—${time(r.end)}`}</b><small>{r.document_page?'文档来源 · 无视频时间戳':`截图 ${time(r.capture_ts)}`} · {r.id}</small></span>{!r.document_page&&<button onClick={()=>jump(r.capture_ts)}><Play size={13}/>回看</button>}<a href={`/api/source-frame/${job.id}/${r.id}`} target="_blank" rel="noreferrer">恢复原图<ArrowUpRight size={14}/></a></div>)}</div>{!sources.length&&<p className="muted">本任务暂无精简后的来源索引。</p>}</>:<div className="formula-review"><div className="formula-source"><img className="detail-image" src={art(job.id,visual.image)} alt="公式所在课件"/><p className="muted">识别结果是候选。对照原图检查上下标、符号和分式。</p></div><div className="formula-list">{visual.formulas?.map(f=><div className="formula" key={f.id}>{f.image&&<img src={art(job.id,f.image)} alt="公式来源"/>}<MathView latex={edits[f.id]??f.corrected_latex??f.latex}/><label className="field">LaTeX<textarea value={edits[f.id]??f.corrected_latex??f.latex} onChange={e=>setEdits({...edits,[f.id]:e.target.value})}/></label><button disabled={saving} onClick={async()=>{setSaving(true);try{await api(`/jobs/${job.id}/formula`,'PUT',{id:f.id,latex:edits[f.id]??f.corrected_latex??f.latex});refresh();notify('公式修订已保存');}catch(e){notify((e as Error).message);}finally{setSaving(false);}}}><Check size={14}/>保存修订</button>{f.status==='corrected'&&<span className="success">已保存修订</span>}</div>)}{!visual.formulas?.length&&<div><p className="muted">{visual.document_page?'原页中的文字与公式在整理笔记时由 API 读取，可随时对照原图。':'公式随学习笔记整理，原图始终可查看；旧任务可按需执行本地识别。'}</p>{!visual.document_page&&job.spec?.slide_mode!=='vision_api'&&<button disabled={!['materials_ready','ready'].includes(job.status)||saving} onClick={async()=>{setSaving(true);try{await api(`/jobs/${job.id}/visual/${visual.id}/formulas`,'POST',{});refresh();notify('已加入本地图像公式识别队列');}catch(e){notify((e as Error).message);}finally{setSaving(false);}}}><Braces size={15}/>识别这一幅的公式</button>}</div>}</div></div>}
 </DetailPage>;
}

function Calibrate({visual,job,close,submit}:{visual:Visual;job:Any;close:()=>void;submit:(r:Any[])=>void}){
 const [points,setPoints]=useState(visual.quad||[[0,0],[1,0],[1,1],[0,1]]);const [drag,setDrag]=useState<number|null>(null);const svg=useRef<SVGSVGElement>(null);
 return <DetailPage wide title="校准画面区域" close={close}><p className="muted">拖动四个角，使边框覆盖完整课件或板书。校准后创建新任务，原有结果仍保留；其他镜头继续自动识别。</p><svg ref={svg} className="calibration" viewBox="0 0 1280 720" onPointerMove={e=>{if(drag===null||!svg.current)return;const p=svg.current.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const v=p.matrixTransform(svg.current.getScreenCTM()!.inverse());setPoints(points.map((q,i)=>i===drag?[Math.max(0,Math.min(1,v.x/1280)),Math.max(0,Math.min(1,v.y/720))]:q));}} onPointerUp={()=>setDrag(null)} onPointerCancel={()=>setDrag(null)}><image href={`/api/snapshot?path=${encodeURIComponent(job.spec.path)}&second=${visual.capture_ts}`} width="1280" height="720"/><polygon points={points.map(p=>`${p[0]*1280},${p[1]*720}`).join(' ')} fill="#0071e322" stroke="#0071e3" strokeWidth="4"/>{points.map((p,i)=><circle key={i} cx={p[0]*1280} cy={p[1]*720} r="13" fill="#ffffff" stroke="#0071e3" strokeWidth="3" onPointerDown={e=>{setDrag(i);e.currentTarget.setPointerCapture(e.pointerId);}}/>)}</svg><button className="primary" onClick={()=>{const profile=(job.profiles[Number(visual.layout.split('_').pop())]||job.profiles.find((p:Any)=>p.regions.some((r:Any)=>r.kind===visual.kind)))?.regions||[];const regions=profile.filter((r:Any)=>r.kind!==visual.kind);regions.push({kind:visual.kind,quad:points,automatic:false});submit(regions);}}>使用这个区域创建新任务<ChevronRight size={17}/></button></DetailPage>;
}


function App(){
 const [route,setRoute]=useState(()=>location.hash.slice(1)||'/home');
 const [courses,setCourses]=useState<Any[]>([]),[catalogLoaded,setCatalogLoaded]=useState(false),[catalogError,setCatalogError]=useState('');
 const [libraryLoaded,setLibraryLoaded]=useState(false),[libraryError,setLibraryError]=useState('');
 const [reduceMotion,setReduceMotion]=useState(()=>localStorage.getItem('course-reduce-motion')==='true');
 const [library,setLibrary]=useState<Any[]>([]),[jobs,setJobs]=useState<Any[]>([]),[detail,setDetail]=useState<Any>({}),[detailError,setDetailError]=useState('');
 const [search,setSearch]=useState(''),[filter,setFilter]=useState('all'),[uniqueOnly,setUniqueOnly]=useState(true);
 const [toast,setToast]=useState(''),[error,setError]=useState('');
 const [confirmation,setConfirmation]=useState<Confirmation>();
 const deleteFailures=useRef(new Set<string>());
 const reads=useRef({catalog:0,library:0,jobs:0,detail:0});
 const confirmRequest:typeof api=async(url,method='GET',body)=>{try{return await api(url,method,body);}catch(error){const conflict=(error as Any).detail;if(conflict?.code!=='confirmation_required')throw error;const accepted=await new Promise<boolean>(resolve=>setConfirmation({title:'已有处理结果',message:conflict.message,resolve}));if(!accepted)return;return api(url,method,{...(body as Any||{}),confirm_reprocess:true});}};
 const [pendingTask,setPendingTask]=useState<Any>({}),[newReturn,setNewReturn]=useState('/home');
 const [pendingTime,setPendingTime]=useState<number>();
 const [playbackRate,setPlaybackRate]=useState(()=>{const n=Number(localStorage.getItem('course-playback-rate'));return [.5,.75,1,1.25,1.5,1.75,2,2.5,3].includes(n)?n:1;});
 const video=useRef<HTMLVideoElement>(null),root=useRef<HTMLDivElement>(null);
 const parts=route.split('/').filter(Boolean),page=parts[0]||'home',selected=page==='course'?parts[1]||'':'';
 const sub=parts[2]||'notes',tab=sub;
 const selectedRef=useRef(selected);selectedRef.current=selected;
 const job=jobs.find(j=>j.id===selected),status=job?.status||'';
 const detailReady=detail.id===selected;
 const visuals:Visual[]=detailReady?detail.visuals||[]:[];
 const visual=visuals.find(v=>v.id===parts[3]);
 const notify=(text:string)=>setToast(text);
 const go=(path:string)=>{location.hash=path;};
 const course=(view='notes')=>`/course/${selected}/${view}`;
 const openNew=(spec?:Any,regions?:Any[],regionTime?:number)=>{setPendingTask({spec,regions,regionTime});setNewReturn(route);go('/new');};
 const refreshCatalog=async()=>{const ticket=++reads.current.catalog;setCatalogLoaded(false);setCatalogError('');try{const data=await api('/courses');if(ticket===reads.current.catalog)setCourses(data);}catch(e){if(ticket===reads.current.catalog){setCatalogError((e as Error).message);throw e;}}finally{if(ticket===reads.current.catalog)setCatalogLoaded(true);}};
 const refreshLibrary=async()=>{const ticket=++reads.current.library;setLibraryLoaded(false);setLibraryError('');try{const data=await api('/library');if(ticket===reads.current.library)setLibrary(data);}catch(e){if(ticket===reads.current.library){setLibraryError((e as Error).message);throw e;}}finally{if(ticket===reads.current.library)setLibraryLoaded(true);}};
 const refresh=async()=>{const ticket=++reads.current.jobs;try{const data=await api('/jobs');if(ticket===reads.current.jobs){setJobs(current=>JSON.stringify(current)===JSON.stringify(data)?current:data);setError('');}}catch(e){if(ticket===reads.current.jobs)setError((e as Error).message);}};
 const loadDetail=async()=>{if(selected&&selectedRef.current===selected){const ticket=++reads.current.detail;setDetailError('');try{const data=await api(`/jobs/${selected}`);if(selectedRef.current===selected&&ticket===reads.current.detail)setDetail(current=>JSON.stringify(current)===JSON.stringify(data)?current:data);}catch(e){if(selectedRef.current===selected&&ticket===reads.current.detail)setDetailError((e as Error).message);}}};
 useEffect(()=>{const entry=location.hash;api('/preparation').then(v=>{if(v.portable&&!v.ready&&(!entry||entry==='#/home')&&location.hash===entry)location.hash='/prepare';}).catch(()=>{});},[]);
 useEffect(()=>{const changed=()=>{setRoute(location.hash.slice(1)||'/home');setSearch('');};addEventListener('hashchange',changed);return()=>removeEventListener('hashchange',changed);},[]);
 useLayoutEffect(()=>{window.scrollTo(0,0);},[route]);
 useEffect(()=>{refreshLibrary().catch(()=>{});refreshCatalog().catch(()=>{});refresh();},[]);
 useVisiblePolling(refresh,jobs.some(j=>busy(j.status))?2500:15000);
 useEffect(()=>{setDetail({});setDetailError('');loadDetail();},[selected]);
 useVisiblePolling(loadDetail,!detailReady||busy(status)?10000:60000,!!selected);
 useEffect(()=>{if(job&&!busy(job.status)&&detailReady&&(detail.status!==job.status||detail.updated<job.updated))loadDetail();},[selected,job?.status,detailReady]);
 useEffect(()=>{const failed=jobs.filter(j=>j.status==='delete_failed');if(failed.some(j=>!deleteFailures.current.has(j.id)))notify('清理未完成：任务记录已保留，可在处理记录中点击垃圾箱重试。');deleteFailures.current=new Set(failed.map(j=>j.id));},[jobs]);
 useEffect(()=>{if(toast){const timer=setTimeout(()=>setToast(''),6000);return()=>clearTimeout(timer);}},[toast]);
 useEffect(()=>{localStorage.setItem('course-playback-rate',String(playbackRate));if(video.current)video.current.playbackRate=playbackRate;},[playbackRate,route]);
 const contentReady=page==='course'?!!job:['home','collection'].includes(page)?catalogLoaded:page==='library'?library.length>0:true;
 useEffect(()=>{localStorage.setItem('course-reduce-motion',String(reduceMotion));},[reduceMotion]);
 useEffect(()=>{
  if(reduceMotion||!matchMedia('(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)').matches)return;
  const surface=root.current;if(!surface)return;
  const setters=new WeakMap<HTMLElement,{x:ReturnType<typeof gsap.quickSetter>;y:ReturnType<typeof gsap.quickSetter>}>();
  const highlight=(event:PointerEvent)=>{
   const target=(event.target as Element).closest<HTMLElement>('.reader-toolbar');
   if(!target||!surface.contains(target))return;
   let setter=setters.get(target);
   if(!setter){setter={x:gsap.quickSetter(target,'--glass-x','px'),y:gsap.quickSetter(target,'--glass-y','px')};setters.set(target,setter);}
   const bounds=target.getBoundingClientRect();setter.x(event.clientX-bounds.left);setter.y(event.clientY-bounds.top);
  };
  surface.addEventListener('pointermove',highlight,{passive:true});
  return()=>surface.removeEventListener('pointermove',highlight);
 },[reduceMotion]);
 useGSAP(()=>{
  if(reduceMotion)return;
  const media=gsap.matchMedia();
  media.add('(prefers-reduced-motion: no-preference)',()=>{
   const panels=root.current?.querySelectorAll('.animate-in');
   const cards=root.current?.querySelectorAll('.motion-card,.feature-card,.export-list>a');
   if(panels?.length)gsap.from(panels,{y:14,opacity:0,duration:.45,stagger:.055,ease:'power2.out',clearProps:'transform,opacity'});
   if(cards?.length)gsap.from(Array.from(cards).slice(0,16),{y:18,opacity:0,duration:.5,stagger:.045,delay:.08,ease:'power3.out',clearProps:'transform,opacity'});
  });
  return()=>media.revert();
 },{scope:root,dependencies:[route,contentReady,reduceMotion],revertOnUpdate:true});
 const jump=(second:number)=>{setPendingTime(second);go(course('video'));if(video.current){video.current.currentTime=second;video.current.play().catch(()=>{});setPendingTime(undefined);}};
 const setVisual=(v:Visual)=>go(course(`visual/${v.id}`));
 const action=async(name:string)=>{try{const result=await confirmRequest(`/jobs/${selected}/${name}`,'POST',{});if(!result)return;refresh();notify(['organize','review'].includes(name)?'已加入笔记队列，调用前会核对剩余额度':'任务状态已更新');}catch(e){notify((e as Error).message);}};
 const removeItem=async(kind:'jobs'|'courses',id:string)=>{
  try{
   await api(`/${kind}/${id}`,'DELETE');
   const removedCourse=kind==='courses'?courses.find(c=>c.id===id):undefined;
   const currentRemoved=kind==='jobs'?selected===id:!!job&&removedCourse?.lessons.some((l:Any)=>l.path.replaceAll('\\','/').toLowerCase()===job.spec.path.replaceAll('\\','/').toLowerCase());
   if(currentRemoved){if(video.current){video.current.pause();video.current.removeAttribute('src');video.current.load();}setDetail({});setSearch('');go(kind==='jobs'&&relatedCollection?`/collection/${relatedCollection.id}`:'/home');}
   else if(kind==='courses'&&page==='collection'&&parts[1]===id)go('/home');
   await Promise.all([refresh(),refreshCatalog()]);
   notify(kind==='courses'?'课程已移除，正在清理生成资料；原视频保留':'正在停止并删除本节笔记及缓存；原视频保留');
  }catch(e){notify((e as Error).message);}
 };
 const filtered=useMemo(()=>{const matched=visuals.filter(v=>(filter==='all'||v.kind===filter||filter==='check'&&v.flags.length>0)&&(v.ocr||'').toLowerCase().includes(search.toLowerCase()));if(!uniqueOnly)return matched;const matches=new Set(matched.map(v=>v.content_id));const groups=new Map<string,Visual>();for(const v of visuals.filter(v=>matches.has(v.content_id))){const prior=groups.get(v.content_id);if(!prior||(v.is_representative&&!prior.is_representative)||(v.is_representative===prior.is_representative&&((v as Any).quality_score||0)>((prior as Any).quality_score||0)))groups.set(v.content_id,v);}return [...groups.values()].sort((a,b)=>a.capture_ts-b.capture_ts);},[visuals,filter,search,uniqueOnly]);
 const uniqueCount=new Set(visuals.map(v=>v.content_id)).size;
 const names:Any={overview:'课程概览',quality:'结果核验与课件整理',visuals:'课件与板书',transcript:'课堂字幕',notes:'学习笔记',video:'视频回看',exports:'导出资料',visual:'画面详情',calibrate:'区域校准'};
 const globalName:Any={home:'学习工作台',library:'本地课程',jobs:'处理记录',settings:'设置',new:'新建提取任务',collection:'课程目录','course-new':'新建课程'};
 const fileName=(path:string)=>path.split(/[\\/]/).pop();
 const relatedCollection=courses.find(c=>c.lessons.some((l:Any)=>fileName(l.path)===fileName(job?.spec.path||'')));
 const relatedLesson=relatedCollection?.lessons.find((l:Any)=>fileName(l.path)===fileName(job?.spec.path||''));
 const lessonHeading=relatedLesson?`${relatedCollection?.title} · ${relatedLesson.title}`:job?.spec.title;
 const activeCollection=courses.find(c=>c.id===parts[1]);
 const trail:{text:string;path?:string}[]=[{text:'我的课程',path:'/home'}];
 if(page==='course'){
  if(relatedCollection)trail.push({text:relatedCollection.title,path:`/collection/${relatedCollection.id}`});
  trail.push({text:relatedLesson?.title||job?.spec.title||'正在读取',path:course()});
  if(['visual','calibrate'].includes(sub)){
   trail.push({text:'课件与板书',path:course('visuals')});
   if(parts[4]||sub==='calibrate')trail.push({text:'画面详情',path:course(`visual/${parts[3]}`)});
   trail.push({text:sub==='calibrate'?'区域校准':({text:'识别文字',formulas:'公式核对',appearances:'同组来源'} as Any)[parts[4]]||'画面详情'});
  }else if(sub==='quality'&&parts[3]){trail.push({text:names.quality,path:course('quality')});trail.push({text:({subtitles:'字幕核验',formulas:'公式核验',visuals:'课件完整性'} as Any)[parts[3]]});}else if(sub!=='overview')trail.push({text:names[sub]});
 }else if(page==='collection'){
  trail.push({text:activeCollection?.title||'课程目录',path:`/collection/${parts[1]}`});
  if(parts[2])trail.push({text:({organize:'课程设置',rename:'修改课程名称',add:'添加课时',history:'本节处理记录'} as Any)[parts[2]]});
 }else if(page==='settings'){
  trail.push({text:'设置',path:'/settings'});
  if(parts[1]==='models')trail.push({text:'本地识别',path:'/settings/local'});
  if(parts[1])trail.push({text:({local:'本地识别',models:'模型配置',api:'文字整理接口',budget:'费用与用量',appearance:'界面与动效',storage:'存储与清理',resources:'资源与并发'} as Any)[parts[1]]||'设置'});
 }else if(page!=='home')trail.push({text:globalName[page]});
 const exportNames:Any={'quality.json':'识别质量核验报告','note_repairs.json':'整理时的识别修订记录','note_review.json':'笔记复核与修订记录','notes.html':'离线图文讲义 · HTML','visuals.html':'全部画面与分组核对 · HTML','visual_audit.json':'画面覆盖与遮挡核对报告','pages.json':'分组和出现时间','notes.md':'可编辑讲义 · Markdown','transcript.srt':'视频字幕 · SRT','transcript.vtt':'网页字幕 · VTT','transcript.txt':'时间字幕 · TXT','report.json':'完整性报告','ocr.txt':'全部课件文字 · TXT'};
 return <div className={`app ${page==='course'&&sub==='video'?'study-mode':page==='course'&&sub==='notes'?'reading-mode':''} ${page==='home'?'home-mode':''} ${page==='collection'&&!parts[2]?'catalog-mode':''}`} data-motion={reduceMotion?'reduced':'full'} ref={root}>
 <header className="site-nav"><a className="brand" href="#/home" aria-label="notes 首页"><img src="/notes.svg" width="38" height="38" alt=""/><span>notes</span></a><nav aria-label="主导航"><button aria-current={['home','collection','course','course-new'].includes(page)?'page':undefined} onClick={()=>go('/home')}>我的课程</button><details className="site-menu" key={route}><summary>资料库<ChevronDown size={16}/></summary><div><button onClick={()=>go('/library')}><Film size={19}/>本地视频</button><button onClick={()=>go('/jobs')}><Clock3 size={19}/>处理记录</button></div></details><button aria-label="设置" onClick={()=>go('/settings')}><Settings2 size={20}/><span>设置</span></button></nav></header>
 <div className="workspace"><header className="topbar"><div>{trail.map((item,index)=><React.Fragment key={index}>{index>0&&<ChevronRight size={16}/ >}{item.path?<button className="crumb" onClick={()=>go(item.path!)}>{item.text}</button>:<span>{item.text}</span>}</React.Fragment>)}</div></header><main className="hierarchy-main" id="main-content" tabIndex={-1}>
 {error&&<div className="error"><AlertCircle size={16}/>{error}</div>}
 {['home','collection','course-new'].includes(page)&&<CourseCatalog key={route+String(catalogLoaded)} libraryLoaded={libraryLoaded} loadError={catalogError} libraryError={libraryError} parts={parts} courses={courses} library={library} jobs={jobs} loaded={catalogLoaded} go={go} openNew={openNew} request={api} refresh={refreshCatalog} refreshLibrary={refreshLibrary} notify={notify} removeCourse={id=>removeItem('courses',id)} removeJob={id=>removeItem('jobs',id)}/>}
 {page==='library'&&<><div className="page-heading animate-in"><div><h1>本地视频</h1><p>原视频文件与处理记录。课程归属和章节顺序在课程目录中整理。</p></div><button className="primary" onClick={()=>openNew()}><Plus size={17}/>新建提取任务</button></div><VideoPath request={api} added={async()=>{await refreshLibrary();}} notify={notify}/><div className="library-grid animate-in">{library.map((v,i)=>{const related=jobs.filter(j=>j.spec.path.replaceAll('\\','/').toLowerCase()===v.path.replaceAll('\\','/').toLowerCase());return <article className="course-card" key={v.path}><div className="course-cover"><img loading="lazy" src={`/api/snapshot?path=${encodeURIComponent(v.path)}&second=60`} alt={`${v.name}课程预览`}/><span>本地视频</span><b>{time(v.duration)}</b></div><div className="course-info"><h2>{v.name}</h2><p>{related.length?`${related.length} 次处理记录`:'尚未生成笔记'}</p><button onClick={()=>openNew({path:v.path})}>创建提取任务<ArrowUpRight size={17}/></button></div></article>;})}</div>{libraryError?<div className="library-load-error settings-load-error" role="alert"><p>暂时无法读取本地视频</p><p className="muted">{libraryError}</p><button onClick={()=>void refreshLibrary().catch(()=>{})}>重新读取</button></div>:!library.length&&<div className="empty" role={libraryLoaded?undefined:"status"}><Film size={36}/>{libraryLoaded?<><h3>还没有导入本地视频</h3><p>在上方填写本机文件路径，可一次添加多节视频。</p></>:<p>正在查找本地课程视频…</p>}</div>}</>}
 {page==='jobs'&&<DetailPage title="处理记录" close={()=>go('/home')}><p className="muted">每次提取独立保存，进入后查看进度与成果。</p><JobList jobs={jobs} labels={label} open={id=>go(`/course/${id}/overview`)} remove={id=>removeItem('jobs',id)}/></DetailPage>}
 {page==='prepare'&&<ModelPreparation request={api} close={()=>go('/home')} notify={notify}/>}
 {page==='settings'&&<Settings key={parts[1]||'root'} reduceMotion={reduceMotion} changeMotion={setReduceMotion} step={parts[1]||''} go={step=>go('/settings'+(step?'/'+step:''))} close={()=>go('/home')} notify={notify}/>}
 {page==='new'&&<NewTask refreshLibrary={refreshLibrary} request={confirmRequest} library={library} initial={pendingTask.spec} regions={pendingTask.regions} regionTime={pendingTask.regionTime} close={()=>go(newReturn)} refresh={refresh} notify={notify}/>}
 {page==='course'&&(!job?<p className="muted">正在读取课程…</p>:<>
 {detailError&&<div className="detail-load-error settings-load-error" role="alert"><p>暂时无法读取本节资料</p><p className="muted">{detailError}</p><button onClick={()=>void loadDetail()}>重新读取</button></div>}
 {sub==='overview'&&<><div className="page-heading animate-in"><div><h1>{relatedLesson?.title||job.spec.title}</h1><p>{relatedCollection?.title||fileName(job.spec.path)} · {label[status]}</p></div><div className="course-controls"><DeleteButton label="删除本节笔记" disabled={status==='delete_requested'} remove={()=>removeItem('jobs',selected)}/>{busy(status)?<button onClick={()=>action('pause')} disabled={['pause_requested','delete_requested'].includes(status)}><Pause size={16}/>暂停处理</button>:<button onClick={()=>action('resume')}><RotateCcw size={16}/>{['paused','needs_attention','cancelled'].includes(status)?'继续处理':'再次处理'}</button>}</div></div>
 <div className="overview-primary-actions animate-in"><button className="primary" onClick={()=>go(course('notes'))}><BookOpen size={21}/>阅读笔记</button><button className="quiet-button" onClick={()=>go(course('video'))}><Play size={21}/>听课</button></div><details className="course-panel overview-details animate-in"><summary>处理进度与来源<ChevronDown size={20}/></summary><div className={`pipeline overview-progress ${['running','starting'].includes(status)?'is-running':''}`}><div className="pipeline-copy"><span>{job.stage}</span><span>{busy(status)?job.progress>0?`已完成 ${Math.round(job.progress*100)}%`:'正在准备':label[status]}</span></div><div className="progress" role="progressbar" aria-label="本阶段处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress*100)}><div style={{width:`${Math.max(0,job.progress*100)}%`}}/></div><p>{job.message}</p></div>{job.error&&<details className="error-detail"><summary>查看需要处理的问题</summary><pre>{job.error}</pre></details>}<div className="stats" aria-busy={!detailReady}><div><Layers3 size={18}/><strong>{detailReady?uniqueCount:'—'}</strong><span>组 · 保留 {detailReady?visuals.length:'…'} 幅</span></div><div><Subtitles size={18}/><strong>{detailReady?detail.segments?.length||0:'—'}</strong><span>字幕片段</span></div><div><Braces size={18}/><strong>{detailReady?job.spec?.slide_mode==='vision_api'?visuals.filter(v=>v.api_display?.status==='judged').length:visuals.filter(v=>v.is_representative!==false).reduce((s,v)=>s+(v.formulas?.length||0),0):'—'}</strong><span>{job.spec?.slide_mode==='vision_api'?'API 已判断画面':'公式候选'}</span></div><div><ShieldCheck size={18}/><strong>{detailReady?`¥${(detail.usage?.spent||0).toFixed(3)}`:'—'}</strong><span>接口已用 / 预留</span></div></div><TimingPanel value={detail.timings}/></details>
 <div className="feature-grid animate-in">{[['visuals','课件与板书','课件原图与公式',Layers3],['transcript','课堂字幕','时间对齐的原始字幕',Subtitles],['exports','导出资料','学习笔记与资料包',Download],['quality','结果核验与课件整理','检查疑点与重复课件',ShieldCheck]].map(([id,title,desc,Icon])=><button className="feature-card" key={id as string} onClick={()=>go(course(id as string))}><Icon size={25}/><h2>{title as string}</h2><p>{desc as string}</p><ArrowUpRight size={18}/></button>)}</div></>}
 {sub==='quality'&&<QualityReview key={selected} job={job} data={detailReady?detail:{}} view={parts[3]||''} go={view=>go(course(view))} jump={jump} request={confirmRequest} refresh={loadDetail} notify={notify}/>}
 {sub==='notes'&&<NoteReader job={job} data={detailReady?detail:{}} title={lessonHeading||job.spec.title} ready={detailReady} loadError={detailError} back={()=>go(relatedCollection?`/collection/${relatedCollection.id}`:'/home')} go={view=>go(course(view))} jump={jump} organize={()=>action('organize')} review={()=>action('review')} search={search} setSearch={setSearch} remove={()=>removeItem('jobs',selected)}/>}
 {['visuals','transcript'].includes(sub)&&<DetailPage wide title={names[sub]} close={()=>go(course())}><section className="content-panel focus-panel">
 <div className="content-toolbar"><div className="search"><Search size={16}/><input aria-label="搜索课程内容" placeholder={tab==='visuals'?'搜索课件识别文字…':'搜索原始字幕…'} value={search} onChange={e=>setSearch(e.target.value)}/></div>{tab==='visuals'&&<select aria-label="画面类型" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部画面</option><option value="slides">课件</option><option value="board">板书</option><option value="screen">整屏画面</option><option value="check">有核对标记</option></select>}</div>
 {tab==='visuals'?<><div className="content-count"><label><input type="checkbox" checked={uniqueOnly} onChange={e=>setUniqueOnly(e.target.checked)}/>只看代表页（取消可看补充状态）</label><span>{filtered.length} 幅 · {detail.compaction?.original_count||visuals.length} 次来源</span></div><Gallery items={filtered} jobId={selected} select={setVisual}/></>:<div className="reading transcript">{detail?.segments?.filter((s:Any)=>s.text.includes(search)).map((s:Any)=><button key={s.id} className="speech" onClick={()=>jump(s.start)}><time>{time(s.start)}</time><span>{s.text}{s.flags?.length>0&&<small className="small-warning">识别待核对</small>}</span><Play size={13}/></button>)}{!detail?.segments?.length&&<div className="empty"><Subtitles size={36}/><h3>字幕正在准备</h3><p>本地转写完成后，可按时间回看。</p></div>}</div>}
 </section></DetailPage>}
 {sub==='video'&&<StudyPlayer key={selected} job={job} detail={detailReady?detail:{}} title={lessonHeading||job.spec.title} videoRef={video} pendingTime={pendingTime} clearPending={()=>setPendingTime(undefined)} rate={playbackRate} setRate={setPlaybackRate} close={()=>go(course())} control={action} notify={notify}/>}
 {sub==='overview'&&detailReady&&<RecoveryPanel job={detail} request={confirmRequest} refresh={()=>{refresh();loadDetail();}} notify={notify}/>}
 {sub==='exports'&&<DetailPage title="导出学习资料" close={()=>go(course())}><p className="muted">完整资料包含代表页、必要补充和全部来源时间记录，解压后可离线阅读。</p><div className="export-list">{detail.compaction?.version&&!busy(status)&&<a className="bundle-download" href={`/api/download-pages/${selected}`}><Layers3 size={20}/><span>精简课件包 · 仅代表页</span><ArrowUpRight size={17}/></a>}{detail.exports?.includes('notes.html')&&!busy(status)&&<a className="bundle-download" href={`/api/download/${selected}`}><Download size={20}/><span>完整学习资料包 · ZIP</span><ArrowUpRight size={17}/></a>}{detail.exports?.map((path:string)=><a key={path} href={art(selected,path)} download={path}><Download size={17}/><span>{exportNames[path]||path}</span><ArrowUpRight size={15}/></a>)}{!detail.exports?.length&&<p className="muted">提取完成后，资料会显示在这里。</p>}</div></DetailPage>}
 {sub==='visual'&&visual&&<VisualDetail key={visual.id} visual={visual} job={detail} close={()=>go(course('visuals'))} jump={jump} refresh={loadDetail} notify={notify} calibrate={()=>go(course(`calibrate/${visual.id}`))} view={parts[4]||''} open={view=>go(course(`visual/${visual.id}`+(view?'/'+view:'')))}/>}
 {sub==='calibrate'&&visual&&<Calibrate visual={visual} job={detail} close={()=>go(course(`visual/${visual.id}`))} submit={regions=>openNew(job.spec,regions,visual.capture_ts)}/>}
 </>)}
 <footer><span>notes · 让学习有迹可循</span><button className="footer-motion" onClick={()=>go('/settings/appearance')}><Waves size={13}/>{reduceMotion?'已减少动态效果':'界面与动效'}</button><span>本地处理 / 来源保留 / 费用可控</span></footer></main></div>
 {confirmation&&<ConfirmDialog value={confirmation} close={accepted=>{confirmation.resolve(accepted);setConfirmation(undefined);}}/>}
 {toast&&<div className="toast" role="status"><Check size={17}/>{toast}<button aria-label="关闭提示" onClick={()=>setToast('')}><X size={15}/></button></div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);

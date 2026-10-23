import {useEffect,useMemo,useRef,useState,RefObject} from 'react';
import {ArrowLeft,ArrowRight,BookOpen,ChevronLeft,ChevronRight,Maximize,PanelRightClose,PanelRightOpen,Pause,Play} from 'lucide-react';
import NoteMarkdown from './NoteMarkdown';
import RecognitionRepairs from './RecognitionRepairs';

type Any=Record<string,any>;
type Props={job:Any;detail:Any;title:string;videoRef:RefObject<HTMLVideoElement|null>;pendingTime?:number;clearPending:()=>void;rate:number;setRate:(n:number)=>void;close:()=>void;control:(name:string)=>void;notify:(s:string)=>void};
const stamp=(s:number)=>`${Math.floor(s/3600)?Math.floor(s/3600)+':':''}${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(Math.floor(s)%60).padStart(2,'0')}`;
const activeStatus=(s:string)=>['running','starting','queued','pause_requested'].includes(s);

export default function StudyPlayer({job,detail,title,videoRef,pendingTime,clearPending,rate,setRate,close,control,notify}:Props){
 const [showNotes,setShowNotes]=useState(()=>localStorage.getItem('study-show-notes')!=='false');
 const [follow,setFollow]=useState(true),[manualIndex,setManualIndex]=useState(0),[second,setSecond]=useState(pendingTime||0);
 const activeLine=useRef<HTMLParagraphElement>(null);
 const noteScroll=useRef<HTMLDivElement>(null);
 const segments:Any[]=detail.segments||[];
 const bySegment=useMemo(()=>new Map(segments.map(s=>[s.id,s])),[segments]);
 const notes:Any[]=useMemo(()=>{
  if(detail.notes?.length)return detail.notes;
  const groups=new Map<number,Any>();
  for(const s of segments){
   const start=Math.floor(s.start/300)*300;
   if(!groups.has(start))groups.set(start,{id:'preview-'+start,start,end:start+300,title:`${stamp(start)}—${stamp(start+300)}`,body:'',speech:[],display_visual_ids:[]});
   groups.get(start)!.speech.push({id:s.id,time:stamp(s.start),text:s.text});
  }
  return [...groups.values()].sort((a,b)=>a.start-b.start);
 },[detail.notes,segments]);
 const playingIndex=notes.findIndex(n=>n.start<=second&&second<n.end);
 const index=follow?playingIndex:Math.min(manualIndex,notes.length-1);
 const note=notes[index];
 const speech:Any[]=note?.speech||[];
 const currentSpeech=speech.find(s=>{const item=bySegment.get(s.id);return item&&item.start<=second&&second<item.end;})?.id;
 const images:Any[]=useMemo(()=>{
  const ids=new Set(note?.display_visual_ids||note?.visual_ids||[]);
  return (detail.visuals||[]).filter((v:Any)=>ids.has(v.id)&&v.is_representative!==false).sort((a:Any,b:Any)=>a.capture_ts-b.capture_ts);
 },[detail.visuals,note]);
 useEffect(()=>{localStorage.setItem('study-show-notes',String(showNotes));},[showNotes]);
 useEffect(()=>{noteScroll.current?.scrollTo({top:0});},[note?.id]);
 useEffect(()=>{
  if(follow&&showNotes&&currentSpeech)activeLine.current?.scrollIntoView({block:'nearest',behavior:'auto'});
 },[currentSpeech,follow,showNotes]);
 useEffect(()=>{
  if(pendingTime!==undefined&&videoRef.current&&videoRef.current.readyState>=1){
   videoRef.current.currentTime=pendingTime;videoRef.current.play().catch(()=>{});clearPending();
  }
 },[pendingTime]);
 const seek=(time:number)=>{if(videoRef.current){videoRef.current.currentTime=time;videoRef.current.play().catch(()=>{});setSecond(Math.floor(time));}};
 const browse=(next:number)=>{setManualIndex(Math.max(0,Math.min(notes.length-1,next)));setFollow(false);};
 const toggleFull=async()=>{try{await videoRef.current?.requestFullscreen();}catch{notify('请使用播放器自带的全屏按钮。');}};
 const previewImages=(follow?images.filter(v=>v.capture_ts<=second).sort((a,b)=>b.capture_ts-a.capture_ts):images).slice(0,1);
 const otherImages=images.filter(v=>!previewImages.some(p=>p.id===v.id));
 const imageCard=(v:Any)=><button className="study-note-image" key={v.id} onClick={()=>seek(v.capture_ts)}><img loading="lazy" src={`/api/artifacts/${job.id}/${v.image}`} alt={`课件 ${stamp(v.capture_ts)}`}/><span>课件 · {stamp(v.capture_ts)}</span></button>;
 const running=activeStatus(job.status);
 return <section className={`study-page ${showNotes?'with-notes':'video-only'}`}>
  <header className="study-heading"><div><button className="back-link" onClick={close}><ArrowLeft size={15}/>返回课程</button><h1>{title}</h1></div><button className="study-task" onClick={()=>control(running?'pause':'resume')} disabled={job.status==='pause_requested'||['ready','materials_ready'].includes(job.status)}>{running?<Pause size={14}/>:<Play size={14}/>}<span>{running?'后台生成中 · 暂停':['ready','materials_ready'].includes(job.status)?'资料已就绪':'继续生成笔记'}</span></button></header>
  <div className="study-layout">
   <div className="study-screen">
    <video ref={videoRef} controls preload="metadata" src={`/api/video?path=${encodeURIComponent(job.spec.path)}`} onTimeUpdate={e=>setSecond(Math.floor(e.currentTarget.currentTime))} onLoadedMetadata={e=>{e.currentTarget.playbackRate=rate;if(pendingTime!==undefined){e.currentTarget.currentTime=pendingTime;e.currentTarget.play().catch(()=>{});clearPending();}}}/>
    <div className="study-controls"><label className="study-speed">播放速度<select aria-label="播放速度" value={rate} onChange={e=>setRate(Number(e.target.value))}>{[.5,.75,1,1.25,1.5,1.75,2,2.5,3].map(r=><option key={r} value={r}>{r}×{r===1?' · 正常':''}</option>)}</select></label><div><button aria-pressed={showNotes} onClick={()=>setShowNotes(!showNotes)}>{showNotes?<PanelRightClose size={16}/>:<PanelRightOpen size={16}/>}<span>{showNotes?'隐藏笔记':'显示笔记'}</span></button><button onClick={toggleFull}><Maximize size={16}/><span>视频全屏</span></button></div></div>
    <p className="study-processing" role="status"><i className={running?'working':''}/>{running?`${job.stage} · ${job.message}`:'已生成内容保存在本机，播放不会重复识别。'}</p>
   </div>
   {showNotes&&<aside className="study-notes" aria-label="随堂笔记"><div className="study-note-head"><div><BookOpen size={17}/><h2>随堂笔记</h2></div><button aria-label="关闭笔记栏" onClick={()=>setShowNotes(false)}><PanelRightClose size={16}/></button></div>
    <div className="study-note-nav"><label><input type="checkbox" checked={follow} onChange={e=>{setFollow(e.target.checked);if(!e.target.checked)setManualIndex(playingIndex>=0?playingIndex:Math.max(0,notes.length-1));}}/>跟随播放</label><div><button aria-label="上一段笔记" disabled={!notes.length||index===0} onClick={()=>browse(index<0?notes.length-1:index-1)}><ChevronLeft size={15}/></button><span>{index>=0?index+1:'—'} / {notes.length}</span><button aria-label="下一段笔记" disabled={index<0||index>=notes.length-1} onClick={()=>browse(index+1)}><ChevronRight size={15}/></button></div></div>
    <div className="study-note-scroll" ref={noteScroll}>
     {note?<><button className="study-chapter" onClick={()=>seek(note.start)}><time>{note.title}</time><ArrowRight size={13}/></button><div className="study-note-kind">{note.organized?'已整理笔记':'本地字幕讲义 · 尚未整理'}</div>{note.omitted?<p className="muted">这一时段没有可整理的学习内容。</p>:note.body?<div className="study-organized"><NoteMarkdown>{note.body}</NoteMarkdown></div>:speech.map(s=><p key={s.id} ref={s.id===currentSpeech?activeLine:undefined} className={`study-message ${s.id===currentSpeech?'is-current':''}`}><button onClick={()=>seek(bySegment.get(s.id)?.start??note.start)}>{s.time}</button><span>{s.text}</span></p>)}<RecognitionRepairs items={note.repairs} pending={note.deferred_formula_ids} editorial={note.editorial_notes}/>{previewImages.map(imageCard)}{otherImages.length>0&&<details className="study-more" key={note.id}><summary>本段另有 {otherImages.length} 幅课件，点击展开</summary>{otherImages.map(imageCard)}</details>}</>:<div className="study-note-empty"><BookOpen size={28}/><h3>{notes.length?'笔记尚未到这里':'笔记正在准备'}</h3><p>{notes.length?'该时段还没有就绪内容，可用左箭头查看已有段落。':'已完成的字幕和讲义会自动出现在这里。生成按阶段推进，无需保持页面打开。'}</p></div>}
    </div><div className="study-note-footer">内容与原视频时间对应 · 可随时隐藏</div>
   </aside>}
  </div>
 </section>;
}

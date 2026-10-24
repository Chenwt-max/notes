import {useEffect,useState,type SyntheticEvent} from 'react';
import {ArrowLeft,ArrowUpRight,BookOpen,Check,ChevronDown,Download,FileText,Layers3,LoaderCircle,MoreHorizontal,Play,Search,Settings2,Sparkles,PanelRightOpen,X} from 'lucide-react';
import NoteMarkdown from './NoteMarkdown';
import RecognitionRepairs from './RecognitionRepairs';
import DeleteButton from './DeleteButton';
import {SlidePanel,SlideViewer,chapterSlides} from './SlidePanel';
import NoteAssistant,{type AskSelection} from './NoteAssistant';
import ReaderSplit from './ReaderSplit';
import './reader-tools.css';

type Any=Record<string,any>;
const time=(s:number)=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
const chapterTitle=(note:Any,index:number)=>note.body?.match(/^#{1,3}\s+(.+)$/m)?.[1]?.replace(/\*\*/g,'')||`第 ${index+1} 章`;

export default function NoteReader({job,data,title,ready,loadError='',back,go,jump,organize,review,search,setSearch,remove}:{job:Any;data:Any;title:string;ready:boolean;loadError?:string;back:()=>void;go:(view:string)=>void;jump:(second:number)=>void;organize:()=>void;review:()=>void;search:string;setSearch:(value:string)=>void;remove:()=>Promise<void>}){
 const notes:Any[]=data.notes||[],visuals:Any[]=data.visuals||[];
 const complete=notes.filter(n=>n.organized&&(n.body?.trim()||n.omitted)),running=['running','starting','queued','pause_requested'].includes(job.status);
 const reviewWarnings=notes.filter(n=>n.review_warning);
 const [active,setActive]=useState(''),[searchOpen,setSearchOpen]=useState(false);
 const [slideNote,setSlideNote]=useState<string>(),[viewer,setViewer]=useState<{items:Any[];index:number}>(),[selectedText,setSelectedText]=useState<{text:string;noteId:string;x:number;y:number}>(),[ask,setAsk]=useState<AskSelection>();
 const visible=notes.filter(n=>!n.omitted&&(!search||(n.body||'').toLowerCase().includes(search.toLowerCase())));
 useEffect(()=>{
  const observer=new IntersectionObserver(entries=>{const current=entries.find(e=>e.isIntersecting);if(current)setActive(current.target.id);},{rootMargin:'-100px 0px -65% 0px'});
  document.querySelectorAll('.note-chapter').forEach(node=>observer.observe(node));return()=>observer.disconnect();
 },[notes.length,complete.length,search]);
 const scroll=(id:string)=>document.getElementById(id)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches||localStorage.getItem('course-reduce-motion')==='true'?'auto':'smooth',block:'start'});
 const showSlides=(note:Any)=>setSlideNote(note.id);
 const selectText=(event:SyntheticEvent<HTMLElement>)=>{
  const selection=window.getSelection();if(!selection||selection.isCollapsed){setSelectedText(undefined);return;}
  const range=selection.getRangeAt(0);if(!event.currentTarget.contains(range.commonAncestorContainer)){setSelectedText(undefined);return;}
  const node=selection.anchorNode?.parentElement,chapter=node?.closest('.note-chapter');
  if(!node?.closest('.note-prose')||!chapter){setSelectedText(undefined);return;}
  const text=selection.toString().trim();if(!text||text.length>2000){setSelectedText(undefined);return;}
  const rect=range.getBoundingClientRect();setSelectedText({text,noteId:chapter.id.replace('chapter-',''),x:Math.max(12,Math.min(rect.left,innerWidth-130)),y:Math.max(12,rect.top-48)});
 };
 const outline=<>{visible.map((n,i)=><button className={active===`chapter-${n.id}`?'is-active':''} key={n.id} onClick={e=>{scroll(`chapter-${n.id}`);e.currentTarget.closest('details')?.removeAttribute('open');}}>{chapterTitle(n,i)}</button>)}</>;
 return <div className={`note-reader ${slideNote?'with-slides':''}`}>
  <nav className="reader-toolbar" aria-label="课时工具"><button className="reader-back" onClick={back}><ArrowLeft size={20}/>课程目录</button><div className="reader-tools"><details className="reader-mobile-outline"><summary>目录<ChevronDown size={17}/></summary><div>{outline}</div></details><button aria-label="展开对应PPT侧栏" disabled={!notes.length} aria-expanded={!!slideNote} onClick={()=>slideNote?setSlideNote(undefined):setSlideNote((notes.find(n=>`chapter-${n.id}`===active)||notes[0])?.id)}><PanelRightOpen size={20}/><span>PPT</span></button><button className="reader-listen" onClick={()=>go('video')}><Play size={18}/>听课</button><DeleteButton label="删除本节笔记" disabled={job.status==='delete_requested'} remove={remove}/><button aria-label={searchOpen?'关闭搜索':'搜索笔记'} aria-expanded={searchOpen} className="icon-button" onClick={()=>{setSearchOpen(!searchOpen);if(searchOpen)setSearch('');}}>{searchOpen?<X size={21}/>:<Search size={21}/>}</button><details className="reader-menu"><summary aria-label="来源与更多"><MoreHorizontal size={24}/></summary><div><button disabled={running||!complete.length} onClick={review}><Sparkles size={19}/>复核笔记</button><button onClick={()=>go('visuals')}><Layers3 size={19}/>原始课件</button><button onClick={()=>go('transcript')}><FileText size={19}/>原始字幕</button><button onClick={()=>go('quality')}><Check size={19}/>识别核验</button><button onClick={()=>go('exports')}><Download size={19}/>导出笔记</button><button onClick={()=>go('overview')}><Settings2 size={19}/>处理详情</button></div></details></div></nav>
  <header className="reader-heading animate-in"><p>{title}</p><h1>学习笔记</h1></header>
  {!ready?loadError?null:<div className="reader-loading" role="status"><LoaderCircle size={24}/>正在打开这节课的笔记…</div>:<>
   {reviewWarnings.length>0&&<details className="reader-review-warnings"><summary>{reviewWarnings.length} 章有待核对内容<ChevronDown size={18}/></summary>{reviewWarnings.map((n,i)=><button key={n.id} onClick={()=>scroll(`chapter-${n.id}`)}><b>{chapterTitle(n,i)}</b><span>{n.review_warning}</span></button>)}</details>}
   {(running||complete.length<notes.length||(!notes.length&&job.status==='materials_ready'))&&<div className="reader-progress"><div><Sparkles size={20}/><span><b>{running?job.stage:complete.length?'还有章节等待整理':'先把这节课整理成笔记'}</b><small>{running?job.message:job.status==='paused'?'提取已暂停，继续处理后会生成笔记。':job.error||data.report?.warnings?.find((w:string)=>/token|接口|额度|输出|分章|成稿|预算/.test(w))||'将字幕和课件组织成可阅读的知识，不再逐句堆叠。'}</small></span></div>{!running&&['materials_ready','ready'].includes(job.status)&&<button className="primary" onClick={organize}><Sparkles size={16}/>{complete.length?'继续整理笔记':'整理为学习笔记'}</button>}{running&&<span className="reader-working"><i/>处理中</span>}</div>}
   {searchOpen&&<div className="reader-search"><Search size={21}/><input autoFocus aria-label="搜索学习笔记" placeholder="搜索概念、公式或关键词" value={search} onChange={e=>setSearch(e.target.value)}/></div>}
   {notes.length>0&&<ReaderSplit enabled={!!slideNote}><div className="reader-paper" role="region" aria-label="整理后的学习笔记" onPointerUp={selectText} onKeyUp={selectText}>
    {visible.map((note,index)=>{const sources=chapterSlides(note,visuals);const heading=chapterTitle(note,index),body=(note.body||'').replace(/^#{1,3}\s+.+\n?/,'');return <article className="note-chapter" id={`chapter-${note.id}`} key={note.id}>
     <h2>{heading}</h2>{sources.length>0&&<button className="chapter-slides-button" onClick={()=>showSlides(note)}><PanelRightOpen size={18}/>展开对应PPT<span>{sources.length}</span></button>}
     {note.organized&&note.body?<div className="note-prose"><NoteMarkdown>{body}</NoteMarkdown></div>:<p className="chapter-pending">{running?'这一章整理完成后，会在这里呈现。':note.warning||'这一章尚未完成整理。原始资料保存在来源页。'}</p>}
     <details className="chapter-sources"><summary>课堂来源<ChevronDown size={17}/></summary><button className="source-text-link" onClick={()=>jump(note.start)}><Play size={17}/>回到 {time(note.start)} 听课</button><button className="source-text-link" onClick={()=>go('transcript')}><FileText size={17}/>原始字幕</button>{sources.length>0&&<button className="source-text-link" onClick={()=>showSlides(note)}>本章全部课件<ArrowUpRight size={17}/></button>}<p className="source-review-state">{note.review_warning|| (note.reviewed?'已完成一次 AI 复核，仍可对照来源检查。':'当前版本尚未完成独立笔记复核。')}</p><RecognitionRepairs items={[...(note.repairs||[]),...(note.review_repairs||[])]} pending={note.deferred_formula_ids} editorial={note.editorial_notes}/></details>
    </article>;})}

    {notes.length>0&&!visible.length&&<p className="reader-empty">{search?'没有找到相关笔记，试试其他关键词。':'这一时段没有可整理的学习内容，原始资料保存在来源页。'}</p>}
   </div><>{slideNote?<SlidePanel jobId={job.id} notes={notes.filter(n=>!n.omitted)} visuals={visuals} noteId={slideNote} choose={setSlideNote} close={()=>setSlideNote(undefined)} view={(items,index)=>setViewer({items,index})}/>:<aside className="reader-outline" aria-label="笔记章节目录"><h2>目录</h2>{outline}</aside>}</></ReaderSplit>}
    {!notes.length&&!running&&job.status!=='materials_ready'&&<div className="reader-empty"><BookOpen size={34}/><h2>本节笔记尚未生成</h2><p>{running?'本地提取完成后会自动整理，无需保持页面打开。':'请先完成本节课的素材提取。'}</p><button onClick={()=>go('overview')}>查看处理进度<ArrowUpRight size={16}/></button></div>}
  </>}
  {viewer&&<SlideViewer jobId={job.id} items={viewer.items} index={viewer.index} choose={index=>setViewer({...viewer,index})} close={()=>setViewer(undefined)} jump={jump}/>}
  {selectedText&&<button className="selection-ask" style={{left:selectedText.x,top:selectedText.y}} onPointerDown={e=>e.preventDefault()} onClick={()=>{setAsk({text:selectedText.text,noteId:selectedText.noteId,nonce:Date.now()});setSelectedText(undefined);}}>问 AI<Sparkles size={17}/></button>}
  <NoteAssistant key={job.id} jobId={job.id} notes={notes} currentNote={active.replace('chapter-','')} selection={ask}/>
 </div>;
}

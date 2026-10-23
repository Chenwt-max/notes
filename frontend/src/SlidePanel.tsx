import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,Download,Expand,Play,X,ZoomIn,ZoomOut} from 'lucide-react';

type Any=Record<string,any>;
const stamp=(s:number)=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
export function chapterSlides(note:Any|undefined,visuals:Any[]):Any[]{
 const ids=[...(note?.visual_ids||[]),...(note?.display_visual_ids||[])];
 const byId=new Map(visuals.map(v=>[v.id,v]));
 const groups=new Map<string,Any[]>(),end=note?.end??Infinity;
 for(const id of new Set<string>(ids)){
  const v=byId.get(id);if(!v||v.api_display?.keep===false||(!v.document_page&&v.capture_ts>=end))continue;
  const group=v.content_id||v.poster_id||v.id;
  const candidates=groups.get(group)||[];candidates.push(v);groups.set(group,candidates);
 }
 return [...groups.values()].map((items):Any=>{
  const poster=byId.get(items[0].poster_id);
  if(poster&&poster.api_display?.keep!==false&&(poster.document_page||poster.capture_ts<end)&&!items.some(v=>v.id===poster.id))items.push(poster);
  const rank=(v:Any)=>(v.api_display?.decisions?.some((d:Any)=>d.final_state==='final'&&d.keep)?1e10:0)+(v.is_representative?1e9:0)+(v.ocr?.length||0)*100+(v.formulas?.length||0)*1000+(v.quality_score||0);
  const best=items.reduce((a,b)=>rank(a)>=rank(b)?a:b);
  return {...best,variants:items.filter(v=>v.id!==best.id)};
 }).sort((a,b)=>a.capture_ts-b.capture_ts);
}

export function SlidePanel({jobId,notes,visuals,noteId,choose,close,view}:{jobId:string;notes:Any[];visuals:Any[];noteId:string;choose:(id:string)=>void;close:()=>void;view:(items:Any[],index:number)=>void}){
 const document=visuals.some(v=>v.document_page);
 const [all,setAll]=useState(document),[supplements,setSupplements]=useState(false),[originals,setOriginals]=useState(false);
 useEffect(()=>{if(document)setAll(true);},[document]);
 const note=notes.find(n=>n.id===noteId)||notes[0];
 const grouped=all?chapterSlides({visual_ids:document?visuals.map(v=>v.id):notes.flatMap(n=>[...(n.visual_ids||[]),...(n.display_visual_ids||[])])},visuals):chapterSlides(note,visuals);
 const slides=originals?[...visuals].sort((a,b)=>(a.document_page??a.capture_ts)-(b.document_page??b.capture_ts)):supplements?grouped.flatMap(v=>[v,...v.variants]):grouped;
 return <aside className="slide-panel" aria-label="对应PPT侧栏"><header><div><h2>{originals?'全部来源':'精选课件'}</h2><span>{originals?slides.length:grouped.length} 页{document?' · 文档原序':''}</span></div><button className="icon-button" aria-label="收起PPT侧栏" onClick={close}><X size={21}/></button></header>{!document&&<div className="slide-scope"><button aria-pressed={!all} onClick={()=>setAll(false)}>本章</button><button aria-pressed={all} onClick={()=>setAll(true)}>全部</button></div>}{!all&&!document&&<select aria-label="选择课件对应章节" value={note?.id||''} onChange={e=>choose(e.target.value)}>{notes.map((n,i)=><option key={n.id} value={n.id}>{n.body?.match(/^#{1,3}\s+(.+)$/m)?.[1]?.replace(/\*\*/g,'')||`第 ${i+1} 章`}</option>)}</select>}{grouped.some(v=>v.variants.length>0)&&<button className="slide-supplements" aria-pressed={supplements} onClick={()=>setSupplements(!supplements)}>{supplements?'收起补充画面':'查看补充画面'}</button>}<button className="slide-supplements" aria-pressed={originals} onClick={()=>setOriginals(!originals)}>{originals?'返回精选课件':'查看全部来源'}</button><div className="slide-panel-pages">{slides.map((v,i)=><button className="slide-preview" key={v.id} onClick={()=>view(slides,i)}><img loading="lazy" decoding="async" src={`/api/artifacts/${jobId}/${v.hd_image||v.image}`} alt={v.document_page?`原课件第 ${v.document_page} 页`:`课件 ${i+1} · ${stamp(v.capture_ts)}`}/><span><b>{String(i+1).padStart(2,'0')}</b>{v.document_page?`第 ${v.document_page} 页`:stamp(v.capture_ts)}<Expand size={18}/></span></button>)}{!slides.length&&<p className="muted">本章暂无对应课件。</p>}</div></aside>;
}

export function SlideViewer({jobId,items,index,choose,close,jump}:{jobId:string;items:Any[];index:number;choose:(index:number)=>void;close:()=>void;jump:(second:number)=>void}){
 const dialog=useRef<HTMLDialogElement>(null),v=items[index];
 const [fit,setFit]=useState(true),[zoom,setZoom]=useState(1),[full,setFull]=useState(false),[fallback,setFallback]=useState(false),[broken,setBroken]=useState(false),[size,setSize]=useState({width:0,height:0});
 useEffect(()=>{dialog.current?.showModal();},[]);
 useEffect(()=>{setFit(true);setZoom(1);setFallback(false);setBroken(false);setSize({width:0,height:0});},[index,full]);
 const url=v.document_page?`/api/artifacts/${jobId}/${v.hd_image||v.image}`:fallback?`/api/artifacts/${jobId}/${v.hd_image||v.image}`:`/api/source-frame/${jobId}/${v.id}${full?'?full=true':''}`;
 return <dialog className="slide-viewer" ref={dialog} onCancel={e=>{e.preventDefault();close();}} onKeyDown={e=>{if(e.key==='ArrowLeft'&&index>0)choose(index-1);if(e.key==='ArrowRight'&&index<items.length-1)choose(index+1);}} aria-label="原始课件大图"><header><div><b>课件 {index+1} / {items.length}</b><span>{v.document_page?`原课件第 ${v.document_page} 页`:fallback?'已保存图片':'原视频画面'}{size.width?` · ${size.width} × ${size.height}`:' · 正在读取'}</span></div><button className="icon-button" aria-label="关闭课件大图" onClick={close}><X size={23}/></button></header><div className="slide-viewer-tools"><button disabled={!index} aria-label="上一张课件" onClick={()=>choose(index-1)}><ArrowLeft size={20}/></button><button disabled={index===items.length-1} aria-label="下一张课件" onClick={()=>choose(index+1)}><ArrowRight size={20}/></button><button onClick={()=>setFit(true)} aria-pressed={fit}>适应窗口</button><button onClick={()=>{setFit(false);setZoom(1);}} aria-pressed={!fit&&zoom===1}>1:1</button><button aria-label="缩小课件" onClick={()=>{setFit(false);setZoom(z=>Math.max(.5,z-.25));}}><ZoomOut size={20}/></button><button aria-label="放大课件" onClick={()=>{setFit(false);setZoom(z=>Math.min(4,z+.25));}}><ZoomIn size={20}/></button>{!v.document_page&&<button onClick={()=>setFull(!full)} aria-pressed={full}>{full?'仅看课件':'课堂全景'}</button>}<a href={url} download={`课件-${v.id}.png`}><Download size={18}/>原图</a></div><div className={`slide-viewport ${fit?'fit':''}`}>{broken?<p>图片暂时无法读取，请检查本机视频是否仍在。</p>:<img key={url} src={url} alt={`课件原始画面 ${stamp(v.capture_ts)}`} draggable={false} style={fit?{}:{width:size.width?size.width*zoom:undefined,maxWidth:'none',maxHeight:'none'}} onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} onError={()=>v.document_page||fallback?setBroken(true):setFallback(true)}/>}</div><footer><span>{v.document_page?'原文档页面 · 未设置视频时间戳':fallback?'原视频不可用，当前显示保留图':'清晰度以原视频为限'}{!fit?` · ${Math.round(zoom*100)}%`:''}</span>{!v.document_page&&<button onClick={()=>{close();jump(v.capture_ts);}}><Play size={18}/>回到 {stamp(v.capture_ts)} 听课</button>}</footer></dialog>;
}

import {useEffect,useRef,useState,type PointerEvent as ReactPointerEvent} from 'react';
import gsap from 'gsap';
import {ArrowUp,GripHorizontal,Maximize2,MessageCircle,Minus,Minimize2,MoveDiagonal,Quote,X} from 'lucide-react';
import NoteMarkdown from './NoteMarkdown';
import AssistantCharacter,{type CharacterPose} from './AssistantCharacter';
import PetWheel,{petRoles,petExpressions} from './PetWheel';
import './pet.css';
type Any=Record<string,any>;
export type AskSelection={text:string;noteId:string;nonce:number};
type Message={role:'user'|'assistant';content:string;cost?:number;costUnknown?:boolean;estimated?:boolean};
type Box={x:number;y:number;width:number;height:number};
const avatarSize=(size:number)=>({width:size,height:size*1.5+28});
const availableViewport=()=>({w:document.documentElement.clientWidth||innerWidth,h:innerHeight});
const nextPose=(pose:CharacterPose)=>petExpressions[(petExpressions.indexOf(pose)+1)%petExpressions.length];
const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(n,Math.max(min,max)));
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches||localStorage.getItem('course-reduce-motion')==='true';
const fitBox=(b:Box,w:number,h:number)=>{const width=clamp(b.width,Math.min(330,w-24),w-24),height=clamp(b.height,Math.min(360,h-24),h-24);return {width,height,x:clamp(b.x,12,w-width-12),y:clamp(b.y,12,h-height-12)};};
async function request(url:string,method='GET',body?:unknown,signal?:AbortSignal){
 const response=await fetch('/api'+url,{method,signal,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'请求失败');return value;
}
export default function NoteAssistant({jobId,notes,currentNote,selection}:{jobId:string;notes:Any[];currentNote:string;selection?:AskSelection}){
 const [ready,setReady]=useState(false),[open,setOpen]=useState(false),[menu,setMenu]=useState(false),[persona,setPersona]=useState('deepseek');
 const [position,setPosition]=useState({x:0,y:0}),[viewport,setViewport]=useState({w:1280,h:800}),[box,setBox]=useState<Box>({x:0,y:0,width:420,height:580}),[expanded,setExpanded]=useState(false),[size,setSize]=useState(180),[expression,setExpression]=useState<CharacterPose>('idle');
 const [quote,setQuote]=useState<AskSelection>(),[question,setQuestion]=useState(''),[messages,setMessages]=useState<Message[]>([]),[pending,setPending]=useState(false),[error,setError]=useState(''),[config,setConfig]=useState<Any>();
 const [automatic,setAutomatic]=useState(true),[dragging,setDragging]=useState(false);
 const drag=useRef<{kind:'avatar'|'window'|'resize';x:number;y:number;px:number;py:number;width:number;height:number}|null>(null),moved=useRef(false),placed=useRef(false),sending=useRef(false),controller=useRef<AbortController|undefined>(undefined),thread=useRef<HTMLDivElement>(null),composer=useRef<HTMLTextAreaElement>(null),panel=useRef<HTMLElement>(null);
 const dimensions=avatarSize(size);
 useEffect(()=>{
  const read=(key:string)=>{try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}};
  const saved=read('note-assistant-position'),savedBox=read('note-assistant-window'),viewportSize=availableViewport();setViewport(viewportSize);
  const savedSize=Number(localStorage.getItem('note-assistant-size')),initialSize=Number.isFinite(savedSize)&&savedSize>=120&&savedSize<=260?savedSize:180,initialDimensions=avatarSize(initialSize);setSize(initialSize);
  setPosition({x:clamp(Number.isFinite(saved?.x)?saved.x:viewportSize.w-initialDimensions.width-28,8,viewportSize.w-initialDimensions.width-8),y:clamp(Number.isFinite(saved?.y)?saved.y:viewportSize.h-initialDimensions.height-28,8,viewportSize.h-initialDimensions.height-8)});
  if(savedBox&&['x','y','width','height'].every(k=>Number.isFinite(savedBox[k]))){setBox(fitBox(savedBox,viewportSize.w,viewportSize.h));placed.current=true;}
  const choice=localStorage.getItem('note-assistant-persona');if(petRoles.includes(choice||''))setPersona(choice!);
  setAutomatic(localStorage.getItem('note-assistant-auto-pose')!=='false');
  setReady(true);
  const resize=()=>{const next=availableViewport();setViewport(next);setBox(b=>fitBox(b,next.w,next.h));};
  const observer=new window.ResizeObserver(resize);observer.observe(document.documentElement);
  addEventListener('resize',resize);return()=>{observer.disconnect();removeEventListener('resize',resize);controller.current?.abort();};
 },[]);
 useEffect(()=>{if(ready)setPosition(p=>({x:clamp(p.x,8,viewport.w-dimensions.width-8),y:clamp(p.y,8,viewport.h-dimensions.height-8)}));},[ready,size,viewport.w,viewport.h]);
 useEffect(()=>{
  if(!ready||!automatic||pending||dragging)return;
  let timer:ReturnType<typeof setTimeout>|undefined;
  const schedule=()=>{if(timer!==undefined)clearTimeout(timer);if(!document.hidden)timer=setTimeout(()=>setExpression(nextPose),15000);};
  schedule();document.addEventListener('visibilitychange',schedule);
  return()=>{if(timer!==undefined)clearTimeout(timer);document.removeEventListener('visibilitychange',schedule);};
 },[ready,automatic,pending,dragging,persona,expression]);
 useEffect(()=>{if(question.trim()&&!pending&&!error)setExpression('reading');},[question,pending,error]);
 const cyclePose=()=>setExpression(nextPose);
 const resizePet=(value:number)=>{const next=clamp(value,120,260),nextDimensions=avatarSize(next);setSize(next);const nextPosition={x:clamp(position.x+(dimensions.width-nextDimensions.width)/2,8,viewport.w-nextDimensions.width-8),y:clamp(position.y+dimensions.height-nextDimensions.height,8,viewport.h-nextDimensions.height-8)};setPosition(nextPosition);localStorage.setItem('note-assistant-size',String(next));localStorage.setItem('note-assistant-position',JSON.stringify(nextPosition));};
 const show=()=>{if(panel.current){gsap.killTweensOf(panel.current);gsap.set(panel.current,{clearProps:'transform,opacity'});}if(!placed.current){setBox(fitBox({...box,x:position.x-box.width-14,y:position.y-box.height+dimensions.height},viewport.w,viewport.h));placed.current=true;}setOpen(true);setMenu(false);};
 const close=()=>{if(!panel.current||reduced()){setOpen(false);return;}gsap.to(panel.current,{opacity:0,y:12,scale:.97,duration:.16,ease:'power2.in',overwrite:true,onComplete:()=>setOpen(false)});};
 useEffect(()=>{if(selection){setQuote(selection);show();setQuestion('请解释这段内容，说明直觉和关键推导。');requestAnimationFrame(()=>composer.current?.focus());}},[selection?.nonce]);
 useEffect(()=>{if(open)request('/jobs/'+jobId+'/assistant').then(setConfig).catch(e=>setError(e.message));},[open,jobId]);
 useEffect(()=>{if(!open||!panel.current||reduced())return;const tween=gsap.fromTo(panel.current,{opacity:0,y:18,scale:.96},{opacity:1,y:0,scale:1,duration:.35,ease:'back.out(1.2)',clearProps:'transform,opacity'});return()=>{tween.kill();};},[open]);
 useEffect(()=>{if(!menu)return;const outside=(e:PointerEvent)=>{if(!(e.target as Element).closest('.note-assistant'))setMenu(false);};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[menu]);
 useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight,behavior:reduced()?'auto':'smooth'});},[messages,pending]);
 useEffect(()=>{if(composer.current){composer.current.style.height='auto';composer.current.style.height=Math.min(140,Math.max(56,composer.current.scrollHeight))+'px';}},[question,open]);
 const begin=(kind:'avatar'|'window'|'resize')=>(e:ReactPointerEvent<HTMLElement>)=>{
  if(e.button!==0||kind==='window'&&((e.target as HTMLElement).closest('button')||expanded))return;
  e.stopPropagation();moved.current=false;setDragging(kind==='avatar');drag.current={kind,x:e.clientX,y:e.clientY,px:kind==='avatar'?position.x:box.x,py:kind==='avatar'?position.y:box.y,width:box.width,height:box.height};e.currentTarget.setPointerCapture(e.pointerId);
 };
 const move=(e:ReactPointerEvent<HTMLElement>)=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.hypot(dx,dy)<5&&!moved.current)return;moved.current=true;
  if(d.kind==='avatar')setPosition({x:clamp(d.px+dx,8,viewport.w-dimensions.width-8),y:clamp(d.py+dy,8,viewport.h-dimensions.height-8)});
  else setBox(fitBox(d.kind==='resize'?{x:d.px,y:d.py,width:clamp(d.width+dx,330,viewport.w-d.px-12),height:clamp(d.height+dy,360,viewport.h-d.py-12)}:{x:d.px+dx,y:d.py+dy,width:d.width,height:d.height},viewport.w,viewport.h));
 };
 const end=()=>{drag.current=null;setDragging(false);localStorage.setItem('note-assistant-position',JSON.stringify(position));localStorage.setItem('note-assistant-window',JSON.stringify(box));};
 const send=async()=>{
  if(sending.current||!question.trim())return;
  const noteId=quote?.noteId||currentNote||notes.find(n=>!n.omitted&&n.body?.trim())?.id;if(!noteId){setError('当前还没有可提问的笔记章节。');return;}
  sending.current=true;setPending(true);setError('');setExpression('thinking');const text=question.trim();setQuestion('');
  const previous=messages.slice(-6).map(m=>({role:m.role,content:m.content.slice(0,2800)}));
  setMessages(old=>[...old,{role:'user' as const,content:quote?'“'+quote.text+'”\n\n'+text:text}].slice(-40));
  controller.current=new AbortController();
  try{
   const reply=await request('/jobs/'+jobId+'/assistant','POST',{request_id:crypto.randomUUID(),note_id:noteId,selected_text:quote?.text||'',question:text,persona,history:previous},controller.current.signal);
   setMessages(old=>[...old,{role:'assistant' as const,content:reply.answer+(reply.truncated?'\n\n*回答已达本次长度上限，可以继续追问。*':''),cost:reply.cost_cny??undefined,costUnknown:reply.cost_cny===null,estimated:reply.cost_is_estimate}].slice(-40));setExpression('happy');
   request('/jobs/'+jobId+'/assistant').then(setConfig).catch(()=>{});
  }catch(e){if((e as Error).name!=='AbortError'){setError((e as Error).message);setQuestion(text);setExpression('surprised');}}
  finally{sending.current=false;setPending(false);}
 };
 if(!ready)return null;
 const shown=expanded?{x:12,y:12,width:viewport.w-24,height:viewport.h-24}:fitBox(box,viewport.w,viewport.h);
 const outdated=config&&config.budget_cny!==null;
 const pose=expression;
 return <div className="note-assistant" data-persona={persona} onKeyDown={e=>{if(e.key==='Escape'){setMenu(false);close();}}}>
  {open&&<section ref={panel} className={'assistant-window '+(expanded?'expanded':'')} role="dialog" aria-modal="false" aria-label="笔记AI助手" style={{left:shown.x,top:shown.y,width:shown.width,height:shown.height}}>
   <header onPointerDown={begin('window')} onPointerMove={move} onPointerUp={end} onPointerCancel={end}><GripHorizontal size={18}/><div><b>学习助手</b><span title="角色切换只改变外观，回答使用设置中的API模型">{config?.model||'笔记学习助手'}</span></div><button aria-label={expanded?'恢复助手大小':'展开助手阅读'} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize2 size={18}/>:<Maximize2 size={18}/>}</button><button aria-label="收起助手对话框" onClick={close}><Minus size={20}/></button></header>
   <div className="assistant-thread" ref={thread} aria-live="polite">{!messages.length&&<div className="assistant-welcome"><MessageCircle size={29}/><h3>一起把问题想明白。</h3><p>选中一段笔记，或直接问我。</p></div>}{messages.map((m,i)=><article key={i} className={'assistant-message '+m.role}>{m.role==='assistant'?<NoteMarkdown>{m.content}</NoteMarkdown>:<p>{m.content}</p>}{(m.cost!==undefined||m.costUnknown)&&<span className="assistant-fee">{m.costUnknown?'本次费用未知':<>{m.estimated?'本次估算':'本次'} {m.cost!>0&&m.cost!<.0001?'< ¥0.0001':'¥'+m.cost!.toFixed(4)}</>}</span>}</article>)}{pending&&<div className="assistant-thinking"><span className="thinking-dots" aria-hidden="true"><i/><i/><i/></span>正在想这道题…</div>}</div>
   {quote&&<div className="assistant-quote"><Quote size={17}/><p>{quote.text}</p><button aria-label="移除引用选文" onClick={()=>setQuote(undefined)}><X size={17}/></button></div>}
   {(error||outdated)&&<p className="assistant-error" role="alert">{error||'后台版本较旧，请重启本地服务后刷新，启用独立问答计费。'}</p>}
   {!pending&&<div className="assistant-suggestions">{['直观解释','逐步推导','举个例子'].map((label,i)=><button key={label} onClick={()=>{setQuestion(['请用直观的方式解释，说明为什么。','请逐步推导，解释每个符号和前提。','请给一个具体例子，帮助我理解。'][i]);composer.current?.focus();}}>{label}</button>)}</div>}
   <form className="assistant-composer" onSubmit={e=>{e.preventDefault();send();}}><textarea ref={composer} aria-label="向AI提问" maxLength={2000} rows={2} value={question} placeholder="聊聊哪里没理解…" onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}}}/><div><span>{config?.configured===false?'请先在设置中配置API':config?.price_configured===false?'单价未设置 · 问答无费用上限':'问答单独计费 · 无费用上限'}</span><button type="submit" className="primary" aria-label="发送问题（调用API）" disabled={pending||!question.trim()||config?.configured!==true||config?.budget_cny!==null}><ArrowUp size={20}/></button></div></form>
   {!expanded&&<button className="assistant-resize" aria-label="调整助手窗口大小" onPointerDown={begin('resize')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={e=>{const delta=e.shiftKey?40:10;if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();setBox(b=>fitBox({...b,width:b.width+(e.key==='ArrowRight'?delta:e.key==='ArrowLeft'?-delta:0),height:b.height+(e.key==='ArrowDown'?delta:e.key==='ArrowUp'?-delta:0)},viewport.w,viewport.h));}}}><MoveDiagonal size={15}/></button>}
  </section>}
  {menu&&<PetWheel persona={persona} pose={pose} size={size} automatic={automatic} left={clamp(position.x+dimensions.width-296,12,viewport.w-308)} top={clamp(position.y-386,12,viewport.h-398)} choose={id=>{if(id===persona){cyclePose();return;}setPersona(id);setExpression('idle');localStorage.setItem('note-assistant-persona',id);}} expression={cyclePose} resize={resizePet} autoChange={value=>{setAutomatic(value);localStorage.setItem('note-assistant-auto-pose',String(value));}} close={()=>setMenu(false)}/>}
  <button className="assistant-avatar" data-dragging={dragging} data-status={pending?'thinking':error?'error':pose==='happy'?'happy':'idle'} style={{left:position.x,top:position.y,width:dimensions.width,height:dimensions.height}} aria-label="学习助手，点击开关对话并换姿态，右键选择外观，可拖动" aria-expanded={open} title="点击聊天并换姿态 · 右键选择外观 · 拖动移动" onPointerDown={begin('avatar')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onClick={()=>{if(moved.current){moved.current=false;return;}cyclePose();setMenu(false);if(open)close();else show();}} onContextMenu={e=>{e.preventDefault();setMenu(!menu);}}><AssistantCharacter id={persona} pose={pose}/><span>{pending?'思考中':error?'看看提示':open?'收起':'问 AI'}</span></button>
 </div>;
}


import {useEffect,useRef,useState,type ReactNode,type CSSProperties} from 'react';

const key='notes-reader-split';
const initial=()=>{try{const value=Number(localStorage.getItem(key));return value>=25&&value<=80?value:60;}catch{return 60;}};

export default function ReaderSplit({enabled,children}:{enabled:boolean;children:[ReactNode,ReactNode]}){
 const root=useRef<HTMLDivElement>(null),drag=useRef<number|undefined>(undefined),current=useRef(initial());
 const [ratio,setRatio]=useState(current.current),[resizing,setResizing]=useState(false);
 const update=(value:number,persist=false)=>{
  const width=root.current?.getBoundingClientRect().width||1200;
  const lower=Math.max(25,Math.min(48,420/width*100)),upper=Math.min(80,100-Math.min(48,360/width*100));
  const next=Math.round(Math.max(lower,Math.min(upper,value))*10)/10;
  current.current=next;setRatio(next);if(persist)try{localStorage.setItem(key,String(next));}catch{}
 };
 const finish=()=>{drag.current=undefined;setResizing(false);update(current.current,true);};
 useEffect(()=>{const resize=()=>update(current.current);resize();window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);},[]);
 const style=enabled?{'--reader-split-columns':`minmax(0,${ratio}fr) 20px minmax(0,${100-ratio}fr)`} as CSSProperties:undefined;
 return <div ref={root} className={`reader-layout ${enabled?'reader-resizable':''} ${resizing?'is-resizing':''}`} style={style}>
  {children[0]}{enabled&&<div className="reader-divider" role="separator" tabIndex={0} aria-label="调整笔记与PPT宽度" aria-orientation="vertical" aria-valuemin={25} aria-valuemax={80} aria-valuenow={Math.round(ratio)} title="拖动调整宽度，双击恢复"
   onPointerDown={e=>{if(e.button!==0)return;e.preventDefault();drag.current=e.pointerId;e.currentTarget.setPointerCapture(e.pointerId);setResizing(true);}}
   onPointerMove={e=>{if(drag.current!==e.pointerId||!root.current)return;const bounds=root.current.getBoundingClientRect();update((e.clientX-bounds.left)/bounds.width*100);}}
   onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={()=>{if(drag.current!==undefined)finish();}} onDoubleClick={()=>update(60,true)}
   onKeyDown={e=>{if(['ArrowLeft','ArrowRight','Home'].includes(e.key)){e.preventDefault();update(e.key==='Home'?60:current.current+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?10:2),true);}}}><span/></div>}{children[1]}
 </div>;
}

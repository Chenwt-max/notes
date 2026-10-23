import {useRef,type CSSProperties} from 'react';
import {RotateCcw,Smile,X} from 'lucide-react';
import AssistantCharacter,{type CharacterPose} from './AssistantCharacter';

export const petRoles=['deepseek','gpt','claude','grok','glm','kimi'];
export const petExpressions:CharacterPose[]=['idle','wave','reading','thinking','surprised','happy'];
export default function PetWheel({persona,pose,size,automatic,left,top,choose,expression,resize,autoChange,close}:{persona:string;pose:CharacterPose;size:number;automatic:boolean;left:number;top:number;choose:(id:string)=>void;expression:()=>void;resize:(value:number)=>void;autoChange:(value:boolean)=>void;close:()=>void}){
 const options=useRef<(HTMLButtonElement|null)[]>([]);
 return <section className="pet-wheel" aria-label="角色与大小" style={{left,top}}>
  <div className="pet-wheel-disc" role="menu" aria-label="选择角色" onKeyDown={e=>{
   const index=options.current.indexOf(document.activeElement as HTMLButtonElement);
   if(['ArrowLeft','ArrowUp','ArrowRight','ArrowDown','Home','End'].includes(e.key)){
    e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?petRoles.length-1:(index+(e.key==='ArrowLeft'||e.key==='ArrowUp'?-1:1)+petRoles.length)%petRoles.length;options.current[next]?.focus();
   }
  }}>
   <span className="pet-wheel-orbit" aria-hidden="true"/>
   <button className="pet-wheel-center" aria-label="切换姿态" title="切换姿态" onClick={expression}><AssistantCharacter id={persona} pose={pose}/><Smile size={15}/></button>
   {petRoles.map((id,index)=>{const angle=index*2*Math.PI/petRoles.length-Math.PI/2;return <button ref={node=>{options.current[index]=node;}} key={id} data-pet={id} className="pet-wheel-option" role="menuitemradio" aria-label={`选择第${index+1}个角色`} aria-checked={id===persona} tabIndex={id===persona?0:-1} style={{'--pet-x':`${Math.cos(angle)*99}px`,'--pet-y':`${Math.sin(angle)*99}px`} as CSSProperties} onClick={()=>choose(id)}><AssistantCharacter id={id}/><span className="pet-selected-dot" aria-hidden="true"/></button>;})}
  </div>
  <div className="pet-size-control"><label htmlFor="pet-size">大小</label><input id="pet-size" type="range" aria-label="角色大小" min="120" max="260" step="5" value={size} onChange={e=>resize(Number(e.target.value))}/><output htmlFor="pet-size">{Math.round(size/180*100)}%</output><button aria-label="恢复默认角色大小" title="恢复默认大小" onClick={()=>resize(180)}><RotateCcw size={16}/></button></div>
  <label className="pet-auto-control"><input type="checkbox" aria-label="定时切换姿态" checked={automatic} onChange={e=>autoChange(e.target.checked)}/><span>每15秒切换姿态</span></label>
  <button className="pet-wheel-close" aria-label="关闭角色轮盘" onClick={close}><X size={17}/></button>
 </section>;
}

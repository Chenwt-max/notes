import {useEffect,useState} from 'react';
import {Waves} from 'lucide-react';

export default function AppearanceSettings({reduced,change}:{reduced:boolean;change:(value:boolean)=>void}){
 const [systemReduced,setSystemReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
 useEffect(()=>{
  const media=matchMedia('(prefers-reduced-motion: reduce)'),update=()=>setSystemReduced(media.matches);
  update();media.addEventListener('change',update);return()=>media.removeEventListener('change',update);
 },[]);
 return <section className="settings-form appearance-settings" aria-labelledby="appearance-title">
  <header className="appearance-intro"><div className="form-emblem"><Waves size={25}/></div><div><h2 className="appearance-title" id="appearance-title">让界面适合你的节奏</h2><p className="muted">调整页面过渡与动画，保留清晰的操作反馈。</p></div></header>
  <label className="motion-choice" htmlFor="reduce-motion"><span><b>减少动态效果</b><small id="motion-description">减少位移与循环动画，让阅读更安静。</small></span><span className="motion-control"><span className="motion-state" aria-hidden="true">{reduced?'已开启':'已关闭'}</span><input id="reduce-motion" type="checkbox" role="switch" aria-label="减少动态效果" aria-describedby="motion-description" checked={reduced} onChange={e=>change(e.target.checked)}/></span></label>
  <p className="appearance-hint" role="status">{systemReduced?'系统已开启减少动态效果，当前也会减少动画。':'自动保存在此浏览器，重新打开仍会保留。'}</p>
 </section>;
}

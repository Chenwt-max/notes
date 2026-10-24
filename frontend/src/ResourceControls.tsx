import {Cpu,Gauge,Headphones} from 'lucide-react';

type Config=Record<string,any>;
export default function ResourceControls({value,set}:{value:Config;set:(v:Config)=>void}){
 const cores=value.cpu_count||1;
 const preset=(fast:boolean)=>set({...value,processing_mode:fast?'fast':'listening',cpu_threads:fast?Math.min(4,cores):Math.min(2,cores),gpu_concurrency:1,max_concurrent_jobs:fast?0:1});
 return <>
  <p className="muted">选择听课时的轻负载，或离开时的连续处理。</p>
  <div className="resource-presets"><button type="button" aria-pressed={value.processing_mode==='listening'} onClick={()=>preset(false)}><Headphones size={20}/><span><b>听课优先</b><small>轻负载、单课程，为播放留出余量</small></span></button><button type="button" aria-pressed={value.processing_mode==='fast'} onClick={()=>preset(true)}><Gauge size={20}/><span><b>快速并发</b><small>连续处理，多课程同时推进</small></span></button></div>
  <label className="field">本地推理设备<select value={value.device} onChange={e=>set({...value,device:e.target.value})}><option value="cuda">NVIDIA GPU · 显卡</option><option value="cpu">CPU · 处理器</option></select></label>
  <div className="two">
   <label className="field">每个任务的CPU线程数<input type="number" min="1" max={cores} step="1" value={value.cpu_threads??2} onChange={e=>set({...value,cpu_threads:Number(e.target.value)})}/><small>本机 {cores} 个逻辑处理器</small></label>
   <label className="field">GPU推理并发上限<input type="number" min="0" max="64" step="1" disabled={value.device==='cpu'} value={value.gpu_concurrency??1} onChange={e=>set({...value,gpu_concurrency:Number(e.target.value)})}/><small>8GB显卡自动限制为1；0由显存保护决定</small></label>
  </div>
  <label className="field">同时处理的课程数<input type="number" min="0" max="128" step="1" value={value.max_concurrent_jobs??0} onChange={e=>set({...value,max_concurrent_jobs:Number(e.target.value)})}/><small>0 表示不限，超出设置数量的任务会排队。</small></label>
  <label className="field">处理节奏<select value={value.processing_mode} onChange={e=>set({...value,processing_mode:e.target.value})}><option value="listening">听课优先 · 约50%计算占空</option><option value="balanced">均衡 · 约80%计算占空</option><option value="fast">速度优先 · 连续处理</option></select><small>均衡模式计算约4份、休息1份；快速模式不加固定休眠。占空比例不是温度或整机利用率保证。</small></label>
  <details className="context-help"><summary><Cpu size={17}/>资源使用说明</summary><p>CPU线程按每个任务计算。GPU并发控制同时进入显卡推理的任务数，不是显卡核心线程数。8GB显卡自动保持单个GPU阶段，大模型加载前会等待可用显存。</p><p>设置在任务下次启动或继续时生效，降低上限不会中断现有任务。视频解码与预处理仍可能使用CPU。</p></details>
 </>;
}

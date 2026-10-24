import React,{useEffect,useState} from 'react';
import useVisiblePolling from './useVisiblePolling';

type Request=(url:string,method?:string,body?:unknown)=>Promise<any>;
export default function ModelPreparation({request,close,notify}:{request:Request;close:()=>void;notify:(message:string)=>void}){
 const [value,setValue]=useState<any>(),[working,setWorking]=useState(false),[error,setError]=useState('');
 const load=()=>request('/preparation').then(v=>{setValue(v);setError('');}).catch(e=>setError(e.message));
 useEffect(()=>{load();},[]);
 useVisiblePolling(load,value?.running?1000:15000);
 const control=async(action:string)=>{setWorking(true);try{setValue(await request('/preparation/'+action,'POST',{}));setError('');}catch(e){notify((e as Error).message);}finally{setWorking(false);}};
 const gib=(size:number)=>((size||0)/1024**3).toFixed(2)+' GiB';
 const progress=value?.total_bytes?Math.min(100,(value.completed_bytes||0)/value.total_bytes*100):0;
 return <section className="detail-page"><button className="back-link" onClick={close}>返回资料库</button><div className="page-heading"><div><h1>准备本地模型</h1><p className="muted">首次下载，之后在本机完成识别。</p></div></div><div className="settings-form" aria-live="polite">
 {error&&<p role="alert">{error}</p>}{!value?<p>正在读取准备状态…</p>:<><h2>{value.ready?'已准备就绪':value.running?'正在准备':'开始之前'}</h2><p>{value.message}</p><p className="muted">{gib(value.completed_bytes)} / {gib(value.total_bytes)} · 下载和校验完成后才可开始提取</p><progress aria-label="模型准备进度" value={value.ready?100:progress} max="100" style={{width:'100%'}}/><div className="model-summary">{value.models?.map((name:string)=><React.Fragment key={name}><b>{name}</b><span>本地推理</span></React.Fragment>)}</div>{value.running?<button disabled={working} onClick={()=>control('cancel')}>取消下载并保留断点</button>:!value.ready?<button className="primary" disabled={working} onClick={()=>control('start')}>{['cancelled','interrupted','failed'].includes(value.status)?'继续下载与校验':'下载并校验模型'}</button>:<button className="primary" onClick={close}>进入资料库</button>}<p className="muted">模型约 {gib(value.total_bytes)}，下载与安装过程还需要临时空间。取消后重新开始会续传；SHA-256 不符的文件会重新下载。</p></>}
 </div></section>;
}

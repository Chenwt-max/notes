import React,{useEffect,useRef,useState} from 'react';
import useVisiblePolling from './useVisiblePolling';

type Request=(url:string,method?:string,body?:unknown)=>Promise<any>;
const purpose:Record<string,string>={'Qwen3-ASR-1.7B':'字幕转写','Qwen3-ForcedAligner-0.6B':'字幕时间对齐','PaddleOCR-VL-1.6':'课件筛选','PP-DocLayoutV3':'版面定位','YOLOX-Tiny':'遮挡辅助','Silero VAD':'语音分段','RapidOCR PP-OCRv6 / 分类器':'兼容旧任务','YOLOX-S（设置可选）':'兼容旧任务'};
export default function ModelPreparation({request,close,notify}:{request:Request;close:()=>void;notify:(message:string)=>void}){
 const [value,setValue]=useState<any>(),[working,setWorking]=useState(false),[reading,setReading]=useState(false),[error,setError]=useState('');
 const sequence=useRef(0);
 const load=async()=>{const ticket=++sequence.current;setReading(true);try{const result=await request('/preparation');if(ticket===sequence.current){setValue(result);setError('');}}catch(e){if(ticket===sequence.current)setError((e as Error).message);}finally{if(ticket===sequence.current)setReading(false);}};
 useEffect(()=>{void load();return()=>{sequence.current++;};},[]);
 useVisiblePolling(load,value?.running?1000:15000,!working);
 const control=async(action:string)=>{const ticket=++sequence.current;setWorking(true);setReading(false);try{const result=await request('/preparation/'+action,'POST',{});if(ticket===sequence.current){setValue(result);setError('');}}catch(e){if(ticket===sequence.current){setError((e as Error).message);notify((e as Error).message);}}finally{setWorking(false);}};
 const gib=(size:number)=>((size||0)/1024**3).toFixed(2)+' GiB';
 const progress=value?.total_bytes?Math.min(100,(value.completed_bytes||0)/value.total_bytes*100):0;
 return <section className="detail-page"><button className="back-link" onClick={close}>返回资料库</button><div className="page-heading"><div><h1>准备本地模型</h1><p className="muted">首次下载，之后在本机完成识别。</p></div></div><div className="settings-form" aria-live="polite">
 {error&&<div className="settings-load-error" role="alert"><p>暂时无法确认模型准备状态</p><p className="muted">{error}</p><button disabled={reading||working} onClick={()=>void load()}>重新读取</button></div>}{!value?(!error&&<p role="status">正在读取准备状态…</p>):<><h2>{value.ready?'已准备就绪':value.running?'正在准备':'开始之前'}</h2><p>{value.message}</p><p className="muted">{gib(value.completed_bytes)} / {gib(value.total_bytes)} · 下载和校验完成后才可开始提取</p><progress aria-label="模型准备进度" value={value.ready?100:progress} max="100" style={{width:'100%'}}/><div className="model-summary">{value.models?.map((name:string)=><React.Fragment key={name}><b>{name==='YOLOX-S（设置可选）'?'YOLOX-S':name}</b><span>{purpose[name]||'本地模型'}</span></React.Fragment>)}</div>{value.running?<button disabled={working||!!error} onClick={()=>control('cancel')}>取消下载并保留断点</button>:!value.ready?<button className="primary" disabled={working||!!error} onClick={()=>control('start')}>{['cancelled','interrupted','failed'].includes(value.status)?'继续下载与校验':'下载并校验模型'}</button>:<button className="primary" onClick={close}>进入资料库</button>}<p className="muted">模型约 {gib(value.total_bytes)}，下载与安装过程还需要临时空间。取消后重新开始会续传；SHA-256 不符的文件会重新下载。</p><details className="context-help"><summary>兼容资源说明</summary><p>兼容模型用于读取或继续旧任务，不代表默认新任务会运行额外的识别链。依赖自带的轻量资源会一并校验。</p></details></>}
 </div></section>;
}

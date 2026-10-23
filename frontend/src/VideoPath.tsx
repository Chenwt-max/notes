import {useState} from 'react';
import {Plus,ArrowRight} from 'lucide-react';

type Any=Record<string,any>;
export default function VideoPath({request,added,notify}:{request:(url:string,method?:string,body?:unknown)=>Promise<any>;added:(videos:Any[])=>Promise<void>;notify:(text:string)=>void}){
 const [open,setOpen]=useState(false),[path,setPath]=useState(''),[saving,setSaving]=useState(false),[error,setError]=useState('');
 return <div className="video-path-import">{!open?<button type="button" onClick={()=>setOpen(true)}><Plus size={19}/>添加本机视频</button>:<form onSubmit={async e=>{e.preventDefault();setSaving(true);setError('');try{const result=await request('/library/paths','POST',{paths:path.split(/\r?\n/).map(p=>p.trim()).filter(Boolean)});await added(result.videos);setPath('');setOpen(false);notify(`已添加 ${result.videos.length} 个视频，原文件未复制`);}catch(e){setError((e as Error).message);}finally{setSaving(false);}}}><label className="field">视频完整路径（每行一个）<textarea rows={4} autoFocus placeholder={'例如：D:\\课程\\第4节.mp4'} value={path} onChange={e=>setPath(e.target.value)} required/><small>支持批量粘贴路径，直接使用原文件，不复制。</small></label>{error&&<p role="alert" className="notice">{error}</p>}<div className="heading-actions"><button type="button" disabled={saving} onClick={()=>{setOpen(false);setError('');}}>取消</button><button className="primary" disabled={saving||!path.trim()}>{saving?'正在校验…':'添加视频'}<ArrowRight size={18}/></button></div></form>}</div>;
}

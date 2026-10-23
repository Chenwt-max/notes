import {useState} from 'react';
import {LoaderCircle,Trash2} from 'lucide-react';

export default function DeleteButton({label,remove,disabled=false}:{label:string;remove:()=>Promise<void>;disabled?:boolean}){
 const [working,setWorking]=useState(false);
 return <button type="button" className="trash-button" title={`${label}；停止任务并清理生成资料，保留原视频`} aria-label={label} disabled={disabled||working} aria-busy={working} onClick={async()=>{setWorking(true);try{await remove();}finally{setWorking(false);}}}>{working?<LoaderCircle size={21} className="spinning"/>:<Trash2 size={21}/>}</button>;
}

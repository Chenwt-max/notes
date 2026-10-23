import {useEffect,useRef} from 'react';

export type Confirmation={title:string;message:string;resolve:(accepted:boolean)=>void};
export default function ConfirmDialog({value,close}:{value:Confirmation;close:(accepted:boolean)=>void}){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{dialog.current?.showModal();},[]);
 return <dialog className="confirm-dialog" ref={dialog} onCancel={e=>{e.preventDefault();close(false);}} aria-labelledby="confirm-title"><h2 id="confirm-title">{value.title}</h2><p>{value.message}</p><div><button autoFocus onClick={()=>close(false)}>保留现有结果</button><button className="primary" onClick={()=>close(true)}>确认再次处理</button></div></dialog>;
}

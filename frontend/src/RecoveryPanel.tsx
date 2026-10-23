import React,{useState} from 'react';

export default function RecoveryPanel({job,request,refresh,notify}:{job:any;request:(url:string,method?:string,body?:unknown)=>Promise<any>;refresh:()=>void;notify:(s:string)=>void}){
 const [busy,setBusy]=useState(false);
 const workflow=job.workflow;if(!workflow)return null;
 const names:Record<string,string>={organize:'整理正文',review:'复核修订',chapters:'整课分章'};
 const failed=workflow.phases?.filter((p:any)=>p.failed_ids?.length)||[];
 const budgetBlocked=job.report?.warnings?.some((w:string)=>/预算|额度|token上限/.test(w));
 if(!failed.length&&!workflow.billing_confirmation_required?.length&&!workflow.metadata_warnings?.length&&!budgetBlocked)return null;
 return <div className="settings-form"><h2>整理恢复</h2><p>{workflow.recoverable_reason}</p>{workflow.metadata_warnings?.map((s:string)=><p key={s} className="muted">{s}</p>)}
 {failed.map((phase:any)=><button key={phase.phase} disabled={busy||workflow.billing_confirmation_required?.length>0} onClick={async()=>{setBusy(true);try{const result=await request(`/jobs/${job.id}/retry/${phase.phase}`,'POST',{request_id:crypto.randomUUID()});if(result){refresh();notify('已安排一次失败重试，历史响应与费用保留');}}catch(e){notify((e as Error).message);}finally{setBusy(false);}}}>重试{names[phase.phase]}</button>)}
 {workflow.billing_confirmation_required?.map((id:string)=><BillingConfirmation key={id} job={job} callId={id} request={request} refresh={refresh} notify={notify}/>)}
 {budgetBlocked&&<BudgetRecovery job={job} request={request} refresh={refresh} notify={notify}/>}
 </div>;
}

function BudgetRecovery({job,request,refresh,notify}:any){
 const [amount,setAmount]=useState(String(job.spec?.budget_cny??1)),[saving,setSaving]=useState(false);
 return <form onSubmit={async e=>{e.preventDefault();setSaving(true);try{await request(`/jobs/${job.id}/budget`,'PATCH',{budget_cny:Number(amount)});refresh();notify('本节额度已更新，累计账本保留；点击继续处理即可');}catch(e){notify((e as Error).message);}finally{setSaving(false);}}}><label className="field">本节笔记总额度（元）<input type="number" min="0" step="any" required value={amount} onChange={e=>setAmount(e.target.value)}/></label><button disabled={saving}>保存本节额度</button></form>;
}

function BillingConfirmation({job,callId,request,refresh,notify}:any){
 const [amount,setAmount]=useState(''),[busy,setBusy]=useState(false);
 const call=job.usage?.calls?.find((c:any)=>c.id===callId);
 return <form onSubmit={async e=>{e.preventDefault();setBusy(true);try{await request(`/jobs/${job.id}/billing/${callId}`,'POST',{actual_cny:Number(amount),confirmed:true});refresh();notify('核账已记录，未发起新的付费请求');}catch(e){notify((e as Error).message);}finally{setBusy(false);}}}><p>未确认请求 · 预留 ¥{Number(call?.reserved||0).toFixed(4)}</p><label className="field">供应商账单中确认的实际费用（元）<input required type="number" min="0" step="any" value={amount} onChange={e=>setAmount(e.target.value)}/></label><p className="muted">确认供应商已经结束该请求后填写。没有收费填 0；本操作只核账，随后可明确重试。</p><button disabled={busy||!amount}>确认账单</button></form>;
}

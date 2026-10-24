import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import ModelPreparation from '../../frontend/src/ModelPreparation';

export async function run(){
 const mode=process.argv[3]||'read-failure',host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
 const timers=new Map<number,()=>void>();let sequence=0,gets=0,posts=0,fail=mode==='read-failure',resolveOld:(value:any)=>void=()=>{};
 const status=(running=false)=>({ready:false,running,status:running?'downloading':'required',total_bytes:100,completed_bytes:0,models:['PaddleOCR-VL-1.6','YOLOX-S（设置可选）']});
 globalThis.setTimeout=((run:()=>void)=>{timers.set(++sequence,run);return sequence;}) as any;
 globalThis.clearTimeout=((id:number)=>{timers.delete(id);}) as any;
 const request=async(_url:string,method='GET')=>{
  if(method==='POST'){posts++;if(mode==='post-failure')throw new Error('准备请求暂未确认');return status(true);}
  gets++;if(fail)throw new Error('读取中断');
  if(mode==='read-race'&&gets===2)return new Promise(resolve=>{resolveOld=resolve;});
  return status();
 };
 const button=(name:string)=>[...host.querySelectorAll('button')].find(x=>x.textContent===name);
 const click=async(name:string)=>{assert(button(name),`Missing ${name}`);await act(async()=>button(name)!.click());};
 try{
  await act(async()=>root.render(<ModelPreparation request={request} close={()=>{}} notify={()=>{}}/>));
  if(mode==='read-failure'){
   assert(!host.textContent?.includes('正在读取准备状态'),'A failed read must not pretend to keep loading');
   assert(host.querySelector('[role="alert"]')?.textContent?.includes('读取中断'));
   fail=false;const count=gets;await click('重新读取');assert.equal(gets,count+1);assert.equal(posts,0);
   assert(!host.querySelector('[role="alert"]'));assert(button('下载并校验模型'));
   assert(!host.textContent?.includes('设置可选'),'Compatibility resources must not promise a missing settings choice');
   assert(host.textContent?.includes('课件筛选')&&host.textContent?.includes('兼容旧任务'));
  }else if(mode==='read-race'){
   const timer=timers.entries().next().value!;timers.delete(timer[0]);await act(async()=>{timer[1]();});
   await click('下载并校验模型');assert(button('取消下载并保留断点'));
   await act(async()=>resolveOld(status()));
   assert(button('取消下载并保留断点'),'An old GET cannot undo a successful start response');assert.equal(posts,1);
  }else{
   await click('下载并校验模型');assert(host.querySelector('[role="alert"]')?.textContent?.includes('暂未确认'),'Control failure must remain visible');
   assert(button('下载并校验模型')?.disabled,'Do not resubmit an unconfirmed control request before rereading');
   await click('重新读取');assert(!host.querySelector('[role="alert"]'));assert.equal(posts,1);assert(!button('下载并校验模型')?.disabled);
  }
  await act(async()=>root.unmount());
 }finally{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;host.remove();}
 return {mode,explicit_read_recovery:true,stale_get_protected:true,paid_calls:0};
}

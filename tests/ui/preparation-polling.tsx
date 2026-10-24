import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import ModelPreparation from '../../frontend/src/ModelPreparation';

export async function run(){
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const nativeSet=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
 const hidden=Object.getOwnPropertyDescriptor(document,'hidden');
 const timers=new Map<number,{run:()=>void;delay:number}>();let sequence=0,calls=0,fail=true,running=false;
 globalThis.setTimeout=((run:()=>void,delay:number)=>{timers.set(++sequence,{run,delay});return sequence;}) as any;
 globalThis.clearTimeout=((id:number)=>{timers.delete(id);}) as any;
 const request=async()=>{calls++;if(fail)throw new Error('fixture: 网络中断');return {ready:false,running,total_bytes:10,completed_bytes:0,models:[]};};
 const fire=async()=>{const [id,item]=timers.entries().next().value!;timers.delete(id);await act(async()=>{item.run();});};
 try{
  Object.defineProperty(document,'hidden',{value:false,configurable:true});
  await act(async()=>root.render(<ModelPreparation request={request} close={()=>{}} notify={()=>{}}/>));
  assert(host.querySelector('[role="alert"]')?.textContent?.includes('网络中断'));assert.equal([...timers.values()][0].delay,15000);
  fail=false;running=true;await fire();assert(!host.querySelector('[role="alert"]'),'Successful refresh clears the stale error');assert.equal([...timers.values()][0].delay,1000);
  await act(async()=>{Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});assert.equal(timers.size,0);
  const before=calls;running=false;
  await act(async()=>{Object.defineProperty(document,'hidden',{value:false,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});assert.equal(calls,before+1);assert.equal([...timers.values()][0].delay,15000);
  await act(async()=>root.unmount());assert.equal(timers.size,0);
 }finally{
  globalThis.setTimeout=nativeSet;globalThis.clearTimeout=nativeClear;if(hidden)Object.defineProperty(document,'hidden',hidden);else delete (document as any).hidden;host.remove();
 }
 return {idle_interval_15s:true,active_interval_1s:true,hidden_pauses:true,foreground_refreshes:true,error_clears_on_success:true,cleanup:true};
}

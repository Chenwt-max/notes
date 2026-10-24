import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import useVisiblePolling from '../../frontend/src/useVisiblePolling';

export async function run(){
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const nativeSet=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
 const timers=new Map<number,()=>void>();let sequence=0,calls=0,release:()=>void=()=>{};
 const hidden=Object.getOwnPropertyDescriptor(document,'hidden');
 globalThis.setTimeout=((callback:()=>void)=>{timers.set(++sequence,callback);return sequence;}) as any;
 globalThis.clearTimeout=((id:number)=>{timers.delete(id);}) as any;
 const visibility=async(value:boolean)=>{await act(async()=>{Object.defineProperty(document,'hidden',{value,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});};
 function Probe({run,enabled=true}:{run:()=>Promise<void>;enabled?:boolean}){useVisiblePolling(run,10,enabled);return null;}
 const fire=async()=>{const [id,callback]=timers.entries().next().value!;timers.delete(id);await act(async()=>{void callback();});};
 try{
  Object.defineProperty(document,'hidden',{value:false,configurable:true});
  const blocked=async()=>{calls++;await new Promise<void>(resolve=>release=resolve);};
  await act(async()=>root.render(<Probe run={blocked}/>));assert.equal(timers.size,1);
  await fire();assert.equal(calls,1);assert.equal(timers.size,0,'No timer while a request is pending');
  await visibility(true);await visibility(false);assert.equal(calls,1,'Returning during a pending request must not duplicate it');
  await visibility(true);await act(async()=>release());assert.equal(timers.size,0,'Hidden pages stay paused after an in-flight request finishes');
  const fresh=async()=>{calls+=10;};await act(async()=>root.render(<Probe run={fresh}/>));
  await visibility(false);assert.equal(calls,11,'Visibility restore uses the latest callback immediately');assert.equal(timers.size,1);
  await fire();assert.equal(calls,21);assert.equal(timers.size,1);
  await act(async()=>root.render(<Probe run={fresh} enabled={false}/>));assert.equal(timers.size,0);
  await visibility(true);await visibility(false);assert.equal(calls,21,'Disabled polling remains disabled');
  await act(async()=>root.render(<Probe run={fresh}/>));await fire();assert.equal(calls,31);
  await act(async()=>root.unmount());assert.equal(timers.size,0);
  await visibility(true);await visibility(false);assert.equal(calls,31,'Unmount removes the visibility listener');
 }finally{
  globalThis.setTimeout=nativeSet;globalThis.clearTimeout=nativeClear;
  if(hidden)Object.defineProperty(document,'hidden',hidden);else delete (document as any).hidden;
  host.remove();
 }
 return {passed:true,checks:['serialized requests','hidden pause','in-flight visibility restore','fresh callback','foreground immediate refresh','disabled','unmount cleanup']};
}

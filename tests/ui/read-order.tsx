import React,{act} from 'react';
import assert from 'node:assert/strict';

type Ticket={resolve:(value:any)=>void;reject:(reason:Error)=>void};
export async function run(){
 const mode=process.argv[3]||'detail-latest',queues=new Map<string,Ticket[]>();
 const job=(id:string)=>({id,status:'ready',stage:'已完成',spec:{title:id,path:`C:/fixture/${id}.mp4`,windows:[[0,10]]}});
 const data=(id:string,body:string)=>({...job(id),notes:[{id:'n1',start:0,end:10,organized:true,body}],visuals:[],segments:[]});
 const course={id:'fixture',title:'较新课程',lessons:[]};
 const defer=(path:string)=>new Promise((resolve,reject)=>{const items=queues.get(path)||[];items.push({resolve:value=>resolve({ok:true,json:async()=>value}),reject});queues.set(path,items);});
 Object.defineProperty(globalThis,'location',{value:window.location,configurable:true});
 Object.defineProperty(document,'hidden',{value:false,configurable:true});localStorage.setItem('course-reduce-motion','true');
 window.location.hash=mode==='jobs'?'#/jobs':mode==='library'?'#/collection/fixture/add':mode==='catalog'?'#/course-new':'#/course/a/notes';
 document.body.innerHTML='<div id="root"></div>';
 globalThis.fetch=(async(url:any,options:any={})=>{
  const path=String(url);
  if(path==='/api/courses'&&options.method==='POST')return {ok:true,json:async()=>course};
  assert.equal(options.method,'GET');
  if((mode==='jobs'&&path==='/api/jobs')||(mode==='library'&&path==='/api/library')||(mode==='catalog'&&path==='/api/courses')||path.startsWith('/api/jobs/'))return defer(path);
  return {ok:true,json:async()=>path==='/api/jobs'?[job('a'),job('b')]:path==='/api/courses'&&mode==='library'?[course]:path==='/api/preparation'?{portable:false,ready:true}:[]};
 }) as any;
 const tick=async()=>{await new Promise(resolve=>setTimeout(resolve,30));};
 const settle=async(ticket:Ticket,value:any)=>{await act(async()=>{ticket.resolve(value);await tick();});};
 const click=async(text:string)=>{const e=[...document.querySelectorAll('button')].find(e=>e.textContent?.trim()===text);assert(e,`Missing ${text}`);await act(async()=>{e!.click();await tick();});};
 await act(async()=>{await import('../../frontend/src/main');await tick();});await act(tick);
 if(mode==='jobs'){
  await act(async()=>{document.dispatchEvent(new Event('visibilitychange'));await tick();});const q=queues.get('/api/jobs')!;assert(q.length>=2);
  await settle(q.at(-1)!,[job('new')]);await settle(q[0],[job('old')]);
  assert(document.querySelector('.job-list')?.textContent?.includes('new'),'An old job-list response must not resurrect older records');
 }else if(mode==='library'){
  await click('刷新本地视频');const q=queues.get('/api/library')!;assert(q.length>=2);
  await settle(q.at(-1)!,[{name:'较新视频',path:'C:/fixture/new.mp4',duration:10}]);await settle(q[0],[{name:'过时视频',path:'C:/fixture/old.mp4',duration:10}]);
  assert(document.querySelector('.lesson-picker')?.textContent?.includes('较新视频'),'An earlier library scan must not overwrite a refreshed import list');
 }else if(mode==='catalog'){
  const input=document.querySelector('form input')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')!.set!.call(input,'较新课程');input.dispatchEvent(new Event('input',{bubbles:true}));await tick();});
  await act(async()=>{document.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await tick();});
  const q=queues.get('/api/courses')!;assert(q.length>=2);await settle(q.at(-1)!,[course]);await settle(q[0],[]);
  assert.equal(document.querySelector('main h1')?.textContent,'较新课程','An older catalog cannot erase a newly created course from the UI');
 }else if(mode==='detail-initial'){
  const q=queues.get('/api/jobs/a')!;assert(q.length<=2,'A ready job list should not duplicate the initial detail read (StrictMode may mount twice)');await settle(q.at(-1)!,data('a','初次正文'));assert(document.querySelector('.note-prose')?.textContent?.includes('初次正文'));
 }else if(mode==='detail-terminal'){
  const q=queues.get('/api/jobs/a')!,before=q.length;await settle(q.at(-1)!,{...data('a','完成前的正文'),status:'running',updated:1});assert(q.length>before,'A ready list with an older running detail must read the completed materials');await settle(q.at(-1)!,data('a','完成后的正文'));assert(document.querySelector('.note-prose')?.textContent?.includes('完成后的正文'));
 }else if(mode==='detail-retry'){
  const q=queues.get('/api/jobs/a')!;await act(async()=>{q.at(-1)!.reject(new Error('当前资料读取失败'));await tick();});
  assert(document.querySelector('.detail-load-error')?.textContent?.includes('当前资料读取失败'));assert(!document.querySelector('.reader-loading'),'A failed note read must not pretend to remain loading');
  await click('重新读取');await settle(q.at(-1)!,data('a','恢复的正文'));assert(!document.querySelector('.detail-load-error'));assert(document.querySelector('.note-prose')?.textContent?.includes('恢复的正文'));
  await act(async()=>{document.dispatchEvent(new Event('visibilitychange'));await tick();});await act(async()=>{q.at(-1)!.reject(new Error('刷新暂不可用'));await tick();});
  assert(document.querySelector('.detail-load-error'));assert(document.querySelector('.note-prose')?.textContent?.includes('恢复的正文'),'A refresh error must preserve the already loaded note');
 }else{
  if(mode==='detail-latest')await act(async()=>{document.dispatchEvent(new Event('visibilitychange'));await tick();});
  const q=queues.get('/api/jobs/a')!,first=q[0];
  if(mode==='detail-return'||mode==='detail-error'){
   await act(async()=>{window.location.hash='#/course/b/notes';await tick();});
   if(mode==='detail-error'){
    await settle(queues.get('/api/jobs/b')!.at(-1)!,data('b','当前B正文'));
    await act(async()=>{first.reject(new Error('旧课读取失败'));await tick();});
    assert(!document.querySelector('.toast')?.textContent?.includes('旧课读取失败'),'A previous course error must not appear over the current note');return {mode,passed:true,real_api_calls:0};
   }
   await act(async()=>{window.location.hash='#/course/a/notes';await tick();});
  }
  assert(q.length>=2);await settle(q.at(-1)!,data('a','较新正文'));await settle(first,data('a','过时正文'));
  assert(document.querySelector('.note-prose')?.textContent?.includes('较新正文'),'An outdated response must not overwrite the current note');
 }
 return {mode,passed:true,real_api_calls:0};
}

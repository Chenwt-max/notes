import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import CourseCatalog from '../../frontend/src/CourseCatalog';

const tick=()=>new Promise(resolve=>setTimeout(resolve,25));
export async function run(){
 const mode=process.argv[3]||'notes';
 if(mode==='catalog'){
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  const navigated:string[]=[];let release=()=>{};
  const gate=new Promise<void>(resolve=>release=resolve);
  await act(async()=>{root.render(<CourseCatalog courses={[]} library={[]} jobs={[]} parts={['course-new']} loaded libraryLoaded go={route=>navigated.push(route)} openNew={()=>{}} request={async()=>({id:'new-course'})} refresh={async()=>{await gate;}} refreshLibrary={async()=>{}} notify={()=>{}} removeCourse={async()=>{}} removeJob={async()=>{}}/>);await tick();});
  const input=host.querySelector('input')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')!.set!.call(input,'新课程');input.dispatchEvent(new window.Event('input',{bubbles:true}));await tick();});
  await act(async()=>{host.querySelector('form')!.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await tick();});
  assert.deepEqual(navigated,[],'Do not enter a course before its refreshed catalog is available');
  await act(async()=>{release();await tick();});
  assert.deepEqual(navigated,['/collection/new-course']);
  await act(async()=>root.unmount());
  return {catalog_refresh_before_navigation:true};
 }
 Object.defineProperty(globalThis,'location',{value:window.location,configurable:true});
 const start=mode==='home'?'#/home':'#/course/existing-note/notes';
 window.location.hash=start;
 document.body.innerHTML='<div id="root"></div>';
 const job={id:'existing-note',status:'ready',stage:'ready',spec:{title:'既有笔记',path:'example.webm',windows:[[0,6]]}};
 const note={id:'n1',title:'保存的正文',body:'保存的正文内容',organized:true,start:0,end:6,speech:[],evidence:[],segment_ids:[],visual_ids:[]};
 globalThis.fetch=(async(url:any)=>({ok:true,json:async()=>{
  const path=String(url);
  if(path.endsWith('/preparation'))return {portable:true,ready:false,status:'required',total_bytes:10,models:[]};
  if(path.endsWith('/jobs'))return [job];
  if(path.endsWith('/courses')||path.endsWith('/library'))return [];
  if(path.endsWith('/jobs/existing-note'))return {...job,notes:[note],visuals:[],segments:[]};
  return {};
 }})) as any;
 await act(async()=>{await import('../../frontend/src/main');await tick();});
 await act(async()=>{await tick();});
 assert.equal(window.location.hash,mode==='home'?'#/prepare':start,'Model setup must not replace an existing note deep link');
 if(mode!=='home')assert(document.body.textContent?.includes('保存的正文内容'));
 return {mode,first_home_guidance:mode==='home',existing_note_readable_without_models:mode!=='home'};
}

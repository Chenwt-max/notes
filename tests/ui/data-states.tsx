import React,{act} from 'react';
import assert from 'node:assert/strict';

export async function run(){
 const mode=process.argv[3]||'library-empty',catalog=mode.startsWith('catalog'),deep=mode==='catalog-deep',creating=mode==='catalog-create',models=mode==='settings-model';let fail=mode!=='library-empty'&&!creating&&!models,created=false;
 Object.defineProperty(globalThis,'location',{value:window.location,configurable:true});
 window.location.hash=models?'#/settings/models':catalog?(deep?'#/collection/fixture':'#/home'):'#/library';localStorage.setItem('course-reduce-motion','true');document.body.innerHTML='<div id="root"></div>';
 const calls:string[]=[];
 globalThis.fetch=(async(url:any,options:any={})=>{
  const path=String(url);calls.push(path);if(creating&&options.method==='POST'&&path.endsWith('/courses')){created=true;return {ok:true,json:async()=>({id:'created',title:'新课程',lessons:[]})};}assert.equal(options.method,'GET');
  if(fail&&path.endsWith(catalog?'/courses':'/library'))throw new Error('fixture: 本地读取失败');
  return {ok:true,json:async()=>path.endsWith('/settings')?{formula_model:'PaddleOCR-VL-1.6',person_model:'yolox-s',device:'cpu'}:path.endsWith('/preparation')?{portable:false,ready:true}:created&&path.endsWith('/courses')?[{id:'created',title:'新课程',lessons:[]}]:deep&&path.endsWith('/courses')?[{id:'fixture',title:'恢复后的课程',lessons:[]}]:[]};
 }) as any;
 const tick=async()=>{await new Promise(resolve=>setTimeout(resolve,30));};
 await act(async()=>{await import('../../frontend/src/main');await tick();});await act(tick);
 if(models){
  assert(document.querySelector('.model-summary b')?.textContent?.includes('YOLOX-S · CPU'),'Model summary must match the saved person model');
 }else if(creating){
  await act(async()=>{(document.querySelector('.hero-copy>.primary') as HTMLButtonElement).click();await tick();});
  const input=document.querySelector('form input')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')!.set!.call(input,'新课程');input.dispatchEvent(new Event('input',{bubbles:true}));await tick();});
  await act(async()=>{document.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await tick();});
  assert.equal(window.location.hash,'#/collection/created');assert.equal(document.querySelector('main h1')?.textContent,'新课程','Catalog refresh must finish before navigation, even when it remounts the form');
 }else if(mode==='library-empty'){
  assert(document.body.textContent?.includes('还没有导入本地视频'),'A loaded empty library must not pretend to be searching');
  assert(!document.body.textContent?.includes('正在查找本地课程视频'));
 }else{
  const error=document.querySelector(catalog?'.catalog-load-error':'.library-load-error');assert(error?.textContent?.includes('本地读取失败'),'A dataset read failure needs a persistent, scoped error');
  if(deep)assert(!document.body.textContent?.includes('课程不存在'),'A network/read failure must not be called a missing course');
  fail=false;await act(async()=>{(error!.querySelector('button') as HTMLButtonElement).click();await tick();});
  assert(!document.querySelector(catalog?'.catalog-load-error':'.library-load-error'));
  assert(document.body.textContent?.includes(catalog?(deep?'恢复后的课程':'先为一门课留个位置'):'还没有导入本地视频'));
 }
 return {mode,loading_empty_error_distinct:true,read_retry:mode!=='library-empty'&&!creating,create_navigation:creating,real_api_calls:0};
}

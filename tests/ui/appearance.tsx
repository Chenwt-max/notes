import React,{act} from 'react';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';

export async function run(){
 Object.defineProperty(globalThis,'location',{value:window.location,configurable:true});
 window.location.hash='#/settings/appearance';localStorage.setItem('course-reduce-motion','false');
 document.body.innerHTML='<div id="root"></div>';
 const style=document.createElement('style');style.textContent=['style.css','studio.css','reader-tools.css','pet.css','study.css','glass.css','workspace.css'].map(name=>readFileSync('frontend/src/'+name,'utf8')).join('\n');document.head.append(style);
 const listeners=new Set<(event:any)=>void>(),media={matches:false,media:'(prefers-reduced-motion: reduce)',addEventListener:(_:string,fn:(e:any)=>void)=>listeners.add(fn),removeEventListener:(_:string,fn:(e:any)=>void)=>listeners.delete(fn)};
 const original=globalThis.matchMedia,originalWindow=window.matchMedia;
 globalThis.matchMedia=((query:string)=>query===media.media?media:original(query)) as any;
 const calls:{url:string;method:string}[]=[];let failSettings=false,failMaintenance=false;
 globalThis.fetch=(async(url:any,options:any={})=>{calls.push({url:String(url),method:options.method||'GET'});if(failSettings&&String(url).endsWith('/settings'))throw new Error('fixture: 配置暂不可用');if(failMaintenance&&String(url).endsWith('/maintenance'))throw new Error('fixture: 存储暂不可用');return {ok:true,json:async()=>String(url).endsWith('/preparation')?{portable:false,ready:true}:String(url).endsWith('/maintenance')?{bytes:1024,reclaimable:0}:String(url).endsWith('/settings')?{device:'cuda',cpu_count:24,cpu_threads:2,gpu_concurrency:1,max_concurrent_jobs:0,processing_mode:'balanced'}:[]};}) as any;
 const tick=async()=>{await new Promise(resolve=>setTimeout(resolve,25));};
 try{
  await act(async()=>{await import('../../frontend/src/main');await tick();});await act(tick);
  const toggle=document.querySelector('[role="switch"]') as HTMLInputElement;
  assert(toggle,'Appearance page must have an operable switch');
  const label=document.querySelector('.motion-choice')!,title=label.querySelector('b')!,description=label.querySelector('small')!;
  const sizes={title:parseFloat(getComputedStyle(title).fontSize),description:parseFloat(getComputedStyle(description).fontSize),switch_width:parseFloat(getComputedStyle(toggle).width),switch_height:parseFloat(getComputedStyle(toggle).height)};
  console.log('appearance sizes',sizes);
  assert(sizes.title>sizes.description,'The setting title must be larger than its description');
  assert(sizes.switch_width>=52&&sizes.switch_height>=30,'The switch must remain clearly visible at normal zoom');
  assert.equal(toggle.getAttribute('aria-label'),'减少动态效果');assert(toggle.getAttribute('aria-describedby'));
  assert.equal(toggle.checked,false);
  await act(async()=>{toggle.click();await tick();});
  assert.equal(toggle.checked,true);assert.equal(localStorage.getItem('course-reduce-motion'),'true');assert.equal(document.querySelector('.app')?.getAttribute('data-motion'),'reduced');
  assert(document.querySelector('.motion-control')?.textContent?.includes('已开启'));
  await act(async()=>{window.location.hash='#/settings';await tick();});
  await act(async()=>{window.location.hash='#/settings/appearance';await tick();});
  const restored=document.querySelector('[role="switch"]') as HTMLInputElement;assert.equal(restored.checked,true,'Navigation retains the saved preference');
  await act(async()=>{restored.click();await tick();});assert.equal(localStorage.getItem('course-reduce-motion'),'false');
  await act(async()=>{media.matches=true;listeners.forEach(fn=>fn({matches:true}));await tick();});
  assert(document.querySelector('.appearance-hint')?.textContent?.includes('系统已开启'));
  assert.equal(localStorage.getItem('course-reduce-motion'),'false','System preference must not overwrite the user choice');
  await act(async()=>{media.matches=false;listeners.forEach(fn=>fn({matches:false}));await tick();});
  assert(!document.querySelector('.appearance-hint')?.textContent?.includes('系统已开启'));
  assert.equal(calls.filter(c=>c.url.endsWith('/settings')).length,0,'Local appearance and the settings directory must not read private API configuration');
  failSettings=true;await act(async()=>{window.location.hash='#/settings/resources';await tick();});
  assert(document.querySelector('.settings-load-error[role="alert"]')?.textContent?.includes('配置暂不可用'),'A failed read must not remain in the loading state');
  failSettings=false;await act(async()=>{(document.querySelector('.settings-load-error button') as HTMLButtonElement).click();await tick();});
  assert(!document.querySelector('.settings-load-error'));
  const presets=[...document.querySelectorAll('.resource-presets button')] as HTMLButtonElement[];
  assert.equal(presets.length,2);assert(presets.every(e=>e.getAttribute('aria-pressed')==='false'));
  await act(async()=>{presets[1].click();await tick();});assert.equal(presets[1].getAttribute('aria-pressed'),'true');assert.equal(presets[0].getAttribute('aria-pressed'),'false');
  const numberField=(text:string)=>[...document.querySelectorAll('label.field')].find(e=>e.textContent?.includes(text))!.querySelector('input') as HTMLInputElement;
  assert.equal(numberField('CPU线程数').value,'4');assert.equal(numberField('课程数').value,'0');
  await act(async()=>{presets[0].click();await tick();});assert.equal(presets[0].getAttribute('aria-pressed'),'true');assert.equal(numberField('CPU线程数').value,'2');assert.equal(numberField('课程数').value,'1');
  failMaintenance=true;await act(async()=>{window.location.hash='#/settings/storage';await tick();});
  assert(document.querySelector('.settings-load-error')?.textContent?.includes('存储暂不可用'));
  failMaintenance=false;await act(async()=>{(document.querySelector('.settings-load-error button') as HTMLButtonElement).click();await tick();});assert(!document.querySelector('.settings-load-error'));assert(document.querySelector('.model-summary')?.textContent?.includes('当前任务资料'));
  assert.equal(calls.filter(c=>c.method!=='GET').length,0,'Changing local appearance must never call a paid or settings write API');
  const report={title_hierarchy:true,visible_switch:true,saved_preference:true,system_preference_live:true,system_does_not_overwrite_local:true,no_unneeded_settings_read:true,failed_read_retry:true,storage_read_retry:true,resource_preset_feedback:true,preset_values:true,real_api_calls:0};
  writeFileSync('qa/release/appearance-ui-fixture.json',JSON.stringify(report,null,2));return report;
 }finally{globalThis.matchMedia=original;window.matchMedia=originalWindow;}
}

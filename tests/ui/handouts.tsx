import React,{act,useState} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import HandoutInput from '../../frontend/src/HandoutInput';
import {SlidePanel,SlideViewer} from '../../frontend/src/SlidePanel';

export async function run(){
 const host=document.createElement('div');document.body.append(host);let value:any;
 function Form(){const [source,setSource]=useState<{mode:'video'|'file';path:string}>({mode:'video',path:''});value=source;return <HandoutInput value={source} onChange={setSource}/>;}
 const root=createRoot(host);await act(async()=>root.render(<Form/>));
 const select=host.querySelector('select')!;assert.equal(select.value,'video');assert.equal(host.querySelector('input'),null);
 await act(async()=>{select.value='file';select.dispatchEvent(new window.Event('change',{bubbles:true}));});
 assert(host.querySelector('input')?.required);assert(host.textContent?.includes('跳过视频课件提取'));
 assert.equal(value.mode,'file');
 assert.equal(host.querySelectorAll('select').length,1);
 assert.equal(host.querySelector('input[type="checkbox"]'),null,'No obsolete local formula extraction choice');
 assert(host.textContent?.includes('支持图片的 API'));
 await act(async()=>root.unmount());
 const doc={id:'d1',document_page:1,untimed:true,image:'images/document-0001.png',content_id:'d1',capture_ts:0,is_representative:true};
 const slides=[{...doc,api_display:{keep:false}}, {...doc,id:'d2',document_page:2,content_id:'d2',image:'images/document-0002.png'}];
 const panel=createRoot(host);
 await act(async()=>panel.render(<SlidePanel jobId="fixture" notes={[{id:'n1',visual_ids:['d1'],end:60}]} visuals={slides} noteId="n1" choose={()=>{}} close={()=>{}} view={()=>{}}/>));
 assert.equal(host.querySelectorAll('.slide-preview').length,1,'Explicitly hidden duplicate is absent from default reader');
 const original=Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='查看全部来源')!;
 await act(async()=>original.click());
 assert.equal(host.querySelectorAll('.slide-preview').length,2,'All original pages remain accessible');
 assert(host.textContent?.includes('文档原序'));assert.equal(host.querySelector('.slide-scope'),null);
 await act(async()=>panel.unmount());
 const viewer=createRoot(host);
 await act(async()=>viewer.render(<SlideViewer jobId="fixture" items={slides} index={0} choose={()=>{}} close={()=>{}} jump={()=>{throw Error('Document pages have no video timestamp');}}/>));
 assert.equal(host.querySelector('.slide-viewport img')?.getAttribute('src'),'/api/artifacts/fixture/images/document-0001.png');
 assert(!host.textContent?.includes('课堂全景'));assert(!host.textContent?.includes('听课'));
 assert(host.textContent?.includes('未设置视频时间戳'));
 await act(async()=>viewer.unmount());
 return {handout_source_choice:true,api_image_route_copy:true,filtered_and_original_pages:true,original_document_pages:true,untimed_document_viewer:true};
}

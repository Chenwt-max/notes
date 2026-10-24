import React,{act,Profiler} from 'react';
import {createRoot} from 'react-dom/client';
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import NoteMarkdown from '../../frontend/src/NoteMarkdown';

export async function run(){
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const body=Array.from({length:16},(_,i)=>`### 推导 ${i+1}\n\n最小化平方误差，令 $r=y-Xw$。\n\n$$\nX^T Xw=X^T y,\\quad w=(X^T X)^{-1}X^T y\n$$\n`).join('\n');
 const samples:number[]=[];
 const render=async(tick:number,text=body)=>{await act(async()=>{root.render(<div data-active={tick}><Profiler id="markdown" onRender={(_,phase,duration)=>{if(phase==='update')samples.push(duration);}}><NoteMarkdown>{text}</NoteMarkdown></Profiler></div>);});};
 await render(0);const math=host.querySelectorAll('.katex').length;assert.equal(math,32);
 for(let i=1;i<=12;i++)await render(i);
 const sorted=[...samples].sort((a,b)=>a-b),report={fixture:'self-authored 16 sections, 32 formulas',updates:samples.length,median_update_ms:sorted[Math.floor(sorted.length/2)],total_update_ms:samples.reduce((a,b)=>a+b,0),formula_count:math};
 await render(13,'## 修改后的正文\n\n$z=42$');assert.equal(host.querySelectorAll('.katex').length,1);assert(host.textContent?.includes('修改后的正文'));
 await act(async()=>root.unmount());host.remove();
 writeFileSync('qa/release/reader-performance-latest.json',JSON.stringify(report,null,2));return report;
}

import {memo} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export function mathMarkdown(markdown:string){
 return markdown.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g).map((part,index)=>index%2?part:part
  .replace(/\\\[([\s\S]*?)\\\]/g,(_,latex)=>`\n\n$$\n${latex.trim()}\n$$\n\n`)
  .replace(/\\\(([\s\S]*?)\\\)/g,(_,latex)=>`$${latex.trim()}$`)).join('');
}

export default memo(function NoteMarkdown({children}:{children:string}){
 return <ReactMarkdown remarkPlugins={[remarkGfm,remarkMath]} rehypePlugins={[[rehypeKatex,{strict:false,throwOnError:false}]]}>{mathMarkdown(children)}</ReactMarkdown>;
});

type Repair={source:string;before:string;after:string;reason:string};
export default function RecognitionRepairs({items=[],pending=[],editorial=[]}:{items?:Repair[];pending?:string[];editorial?:string[]}){
 if(!items.length&&!pending.length&&!editorial.length)return null;
 return <details className="recognition-repairs"><summary>识别修订 · {items.length} 处{pending.length>0&&` · ${pending.length} 处待核对`}</summary><p>整理时由 AI 根据上下文或原图修订；原始识别仍保留。</p>{items.map((r,i)=><div key={i}><b>{r.source}</b><p>{r.before} → {r.after}</p><small>{r.reason}</small></div>)}{editorial.length>0&&<details><summary>整理说明</summary>{editorial.map((text,i)=><p key={i}>{text}</p>)}</details>}{pending.length>0&&<p>另有 {pending.length} 处公式疑点未附图修复，可在核验页对照原图。</p>}</details>;
}

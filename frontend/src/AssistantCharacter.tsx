import {useEffect,useState} from 'react';
export type CharacterPose='idle'|'smile'|'wave'|'thinking'|'reading'|'happy'|'surprised'|'serious';
// The reference atlas is ordered: original, wave, reading, thinking, puzzled, happy.
const frames:Record<CharacterPose,number>={idle:0,wave:1,reading:2,thinking:3,surprised:4,happy:5,smile:5,serious:2};
const fallbackFrames:Record<CharacterPose,number>={idle:0,smile:1,wave:2,thinking:3,reading:4,happy:5,surprised:3,serious:4};
export const characterAtlas=(id:string)=>`/assistants/${id}-poses.png?v=reference-poses-20261021`;
export default function AssistantCharacter({id,pose='idle'}:{id:string;pose?:CharacterPose}){
 const [loaded,setLoaded]=useState('');
 const atlas=characterAtlas(id),ready=loaded===atlas;
 useEffect(()=>{let active=true;const image=new window.Image();image.onload=()=>{if(active)setLoaded(atlas);};image.src=atlas;return()=>{active=false;image.onload=null;};},[atlas]);
 const portrait=!ready&&id==='kimi',frame=(ready?frames:fallbackFrames)[pose];
 const source=ready?atlas:portrait?'/assistants/kimi-portrait.png':`/assistants/${id}-actions.png`;
 return <span className="assistant-character" aria-hidden="true" data-pose={pose} data-atlas={atlas} data-image-ready={ready} style={{backgroundImage:`url("${source}")`,backgroundPosition:portrait?'center':`${frame%3*50}% ${Math.floor(frame/3)*100}%`,backgroundSize:portrait?'contain':undefined,backgroundRepeat:'no-repeat'}}/>;
}

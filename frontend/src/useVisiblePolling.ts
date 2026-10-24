import {useEffect,useRef} from 'react';

export default function useVisiblePolling(callback:()=>Promise<void>,delay:number,enabled=true){
 const latest=useRef(callback);latest.current=callback;
 useEffect(()=>{
  if(!enabled)return;
  let stopped=false,pending=false,timer:ReturnType<typeof setTimeout>|undefined;
  const schedule=()=>{clearTimeout(timer);if(!stopped&&!document.hidden)timer=setTimeout(tick,delay);};
  const tick=async()=>{
   if(stopped||document.hidden||pending)return;
   pending=true;
   try{await latest.current();}finally{pending=false;schedule();}
  };
  const visibility=()=>{clearTimeout(timer);if(!document.hidden)void tick();};
  schedule();document.addEventListener('visibilitychange',visibility);
  return()=>{stopped=true;clearTimeout(timer);document.removeEventListener('visibilitychange',visibility);};
 },[delay,enabled]);
}

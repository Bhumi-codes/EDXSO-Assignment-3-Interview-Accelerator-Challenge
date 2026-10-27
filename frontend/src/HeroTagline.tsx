import {useEffect,useState} from 'react';

const lines=['Your next interview.','Personalized by AI.'];
const length=lines.reduce((sum,line)=>sum+line.length,0);

export function HeroTagline(){
 const [visible,setVisible]=useState(0);
 useEffect(()=>{
  const preference=window.matchMedia('(prefers-reduced-motion: reduce)');
  let timer:ReturnType<typeof setTimeout>|undefined;
  function configure(){
   clearTimeout(timer);
   if(preference.matches){setVisible(length);return;}
   let count=0;setVisible(0);
   function erase(){
    count-=1;setVisible(count);
    timer=setTimeout(count>0?erase:type,count>0?55:650);
   }
   function type(){
    count+=1;setVisible(count);
    if(count<length)timer=setTimeout(type,count===lines[0].length?550:95);
    else timer=setTimeout(erase,3200);
   }
   timer=setTimeout(type,400);
  }
  configure();preference.addEventListener('change',configure);
  return()=>{clearTimeout(timer);preference.removeEventListener('change',configure);};
 },[]);
 function line(text:string,offset:number){
  return <span className="tagline-line" aria-hidden="true">{Array.from(text).map((character,index)=>{
   const position=offset+index;
   return <span key={index} className={'tagline-character'+(position<visible?' is-visible':'')+(visible<length&&position===Math.max(0,visible-1)?' is-typing':'')}>{character}</span>;
  })}</span>;
 }
 return <h1 id="hero-title" className="typing-tagline" aria-label={lines.join(' ')}>{line(lines[0],0)}<em>{line(lines[1],lines[0].length)}</em></h1>;
}

export function responseDuration(seconds:number|null|undefined,mode:string|null|undefined,status='answered'):string{
 if(status!=='answered')return 'Not recorded';
 if(mode==='text')return 'Not measured (typed answer)';
 if(seconds==null||!Number.isFinite(seconds)||seconds<=0)return 'Not available';
 const total=Math.max(1,Math.round(seconds)),s=total%60,m=Math.floor(total/60)%60,h=Math.floor(total/3600);
 return h?`${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`:total>=60?`${Math.floor(total/60)}m ${String(s).padStart(2,'0')}s`:`${s}s`;
}

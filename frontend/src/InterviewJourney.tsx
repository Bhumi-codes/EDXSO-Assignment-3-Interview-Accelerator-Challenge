import {useEffect,useRef} from 'react';
const steps=[
 {title:'Create your interview',label:'YOUR STARTING POINT',text:'Give your practice a name and choose the opportunity you want to prepare for.',detail:'One session. One role. A focused starting point.',icon:'M7 5h14v20H7z M11 11h6 M11 16h6 M11 21h4'},
 {title:'Bring your resume and job description',label:'PERSONALISED TO YOU',text:'Upload your documents or paste the text. Review the extracted information before your role and experience are analysed.',detail:'Your background + the role’s requirements',icon:'M5 8h13v18H5z M11 8V4h13v18h-6 M9 13h5 M9 18h5'},
 {title:'Start with Screening',label:'LEVEL 01 · GET COMFORTABLE',text:'Ease into the conversation with questions about your background, motivation, basic understanding and role fit.',detail:'A first-round conversation, built around you.',icon:'M5 7h22v15H14l-6 5v-5H5z M10 12h12 M10 17h7'},
 {title:'Put your competencies into practice',label:'LEVEL 02 · APPLY WHAT YOU KNOW',text:'Explore relevant experience, project decisions, technical understanding and practical problem solving.',detail:'Explain your approach. Make your reasoning clear.',icon:'M5 11h22v15H5z M11 11V6h10v5 M5 17h22 M13 17v4h6v-4'},
 {title:'Go further in Deep Dive',label:'LEVEL 03 · THINK IT THROUGH',text:'Work through deeper follow-ups and realistic scenarios that probe the reasoning behind your answers.',detail:'The why, the how and the trade-offs.',icon:'M20 20l7 7 M23 13a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M10 13h8 M14 9v8'},
 {title:'Understand your performance',label:'YOUR PERSONALISED REPORT',text:'Review competency scores, question-level feedback, demonstrated strengths and the areas that need more practice.',detail:'See the evidence behind your feedback.',icon:'M6 4h20v24H6z M11 21v-5 M16 21V11 M21 21v-8 M11 8h10'},
 {title:'Leave with a preparation plan',label:'YOUR NEXT STEP',text:'Turn feedback into prioritised practice actions and progress checks, then return for another attempt when you are ready.',detail:'Know what to prepare—and what to practise next.',icon:'M6 6h20v22H6z M11 4v4 M21 4v4 M11 14l2 2 4-4 M11 22h10'},
];
export function InterviewJourney(){
 const root=useRef<HTMLElement|null>(null);
 useEffect(()=>{
  const section=root.current;if(!section)return;
  const preference=window.matchMedia('(prefers-reduced-motion: reduce)');
  let frame=0,observer:IntersectionObserver|undefined;
  const cards=Array.from(section.querySelectorAll<HTMLElement>('.journey-step'));
  function update(){frame=0;if(!section)return;const line=section.querySelector<HTMLElement>('.journey-track');if(!line)return;const lineRect=line.getBoundingClientRect();const progress=Math.max(0,Math.min(1,(innerHeight*.58-lineRect.top)/lineRect.height));section.style.setProperty('--journey-progress',String(progress));}
  function schedule(){if(!frame)frame=requestAnimationFrame(update);}
  function configure(){
   observer?.disconnect();window.removeEventListener('scroll',schedule);window.removeEventListener('resize',schedule);
   if(preference.matches){cards.forEach(card=>card.dataset.revealed='true');section?.style.setProperty('--journey-progress','1');return;}
   if('IntersectionObserver' in window){observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){(entry.target as HTMLElement).dataset.revealed='true';observer?.unobserve(entry.target);}},{threshold:.16});cards.forEach(card=>{if(card.dataset.revealed!=='true')card.dataset.revealed='false';observer!.observe(card);});}
   window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule);schedule();
  }
  configure();preference.addEventListener('change',configure);
  return()=>{observer?.disconnect();cancelAnimationFrame(frame);window.removeEventListener('scroll',schedule);window.removeEventListener('resize',schedule);preference.removeEventListener('change',configure);};
 },[]);
 return <section ref={root} id="interview-journey" className="interview-journey" aria-labelledby="journey-title"><div className="journey-section-heading"><p className="eyebrow">HOW ACE-IT WORKS</p><h2 id="journey-title">A conversation that moves you<br/><em>forward.</em></h2><p>From your first session to a focused preparation plan.<br className="desktop-break"/> Here is what your interview journey looks like.</p></div><div className="journey-timeline"><div className="journey-track" aria-hidden="true"><span/></div><ol>{steps.map((step,index)=><li className="journey-step" key={step.title}><div className="journey-node" aria-hidden="true"><span>{String(index+1).padStart(2,'0')}</span></div><article className="journey-card"><div className="journey-card-top"><span className="journey-plaque" aria-hidden="true"><svg viewBox="0 0 32 32"><path d={step.icon}/></svg></span><p className="eyebrow">{step.label}</p></div><h3>{step.title}</h3><p className="journey-description">{step.text}</p><p className="journey-detail">{step.detail}</p></article></li>)}</ol></div><div className="journey-finish"><span className="journey-finish-mark" aria-hidden="true">↗</span><h3>Your next step starts with a little practice.</h3><a className="secondary" href="#start-interview">Start your interview <span aria-hidden="true">↑</span></a></div></section>;
}

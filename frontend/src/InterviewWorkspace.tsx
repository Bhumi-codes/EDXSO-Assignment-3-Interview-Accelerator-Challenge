import {useEffect,useRef,useState} from 'react';
import {api} from './client';
import {InterviewStage,type InterviewActivity} from './InterviewStage';
import type {SpeechCue} from './speechMotion';
import {responseDuration} from './responseDuration';
type Turn={id:string;question_text:string;raw_transcript:string|null;number:number};
type HistoryTurn={id:string;question:string;answer:string|null;raw_transcript:string|null;status:string;filler_count:number|null;mode:string|null;response_duration_seconds:number|null;number:number;level:number};
type View={phase:string;status:string;finalised:boolean;level:number;level_name:string;current_turn:Turn|null;turns_used:number;budget:number;total_turns_used:number;total_budget:number;error:string|null;history:HistoryTurn[];levels:{number:number;name:string;budget:number;status:string;history:HistoryTurn[]}[];coverage:{answered:number;skipped:number;evaluated:number;pending_evaluations:number}};
export function InterviewWorkspace({sessionId,onClose,onViewReport,candidateName}:{sessionId:string;onClose:()=>void;onViewReport:()=>void;candidateName?:string}){
 const [view,setView]=useState<View|null>(null),[text,setText]=useState(''),[mode,setMode]=useState<'voice'|'text'>('voice');
 const [status,setStatus]=useState('Ready'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[recording,setRecording]=useState(false),[speaking,setSpeaking]=useState(false),[muted,setMuted]=useState(false);
 const media=useRef<MediaRecorder|null>(null),stream=useRef<MediaStream|null>(null),chunks=useRef<Blob[]>([]),alive=useRef(true);
 const context=useRef<AudioContext|null>(null),frame=useRef(0),peak=useRef(0),started=useRef(0),submission=useRef<string|null>(null),last=useRef<string|null>(null);
 const speechRun=useRef(0),welcomePlayed=useRef(false),welcomeSkipped=useRef(false);
 const [speechCue,setSpeechCue]=useState<SpeechCue>({text:'',charIndex:0});
 const greeting=`Hello${candidateName?' '+candidateName:''}. I'm Alex, your AI interviewer. Welcome, and all the best for your interview. Take a moment to get comfortable. When you are ready, we will begin with Screening.`;
 const [confirmEnd,setConfirmEnd]=useState(false),[historyLevel,setHistoryLevel]=useState(1);
 useEffect(()=>{if(confirmEnd){const title=document.getElementById('end-title');title?.scrollIntoView({block:'center'});title?.focus();}},[confirmEnd]);
 const route='/sessions/'+sessionId+'/interview';
 function release(){stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;cancelAnimationFrame(frame.current);context.current?.close().catch(()=>{});context.current=null;}
 function accept(v:View){setView(v);setHistoryLevel(v.level);if(v.current_turn?.id!==last.current){last.current=v.current_turn?.id||null;submission.current=null;setText(v.current_turn?.raw_transcript||'');setMode('voice');}setStatus(v.finalised?(v.status==='completed'?'Interview complete':'Interview ended'):v.phase==='level_complete'?'Level complete':'Ready');}
 useEffect(()=>{alive.current=true;api<View>(route).then(v=>{if(alive.current)accept(v);}).catch(e=>{if(alive.current)setError(e.message);});return()=>{alive.current=false;if(media.current?.state==='recording')media.current.stop();chunks.current=[];release();speechRun.current++;window.speechSynthesis?.cancel();};},[sessionId]);
 function speak(words=view?.current_turn?.question_text,quiet=false){
  if(!words||recording)return false;if(!quiet)setError('');
  if(!('speechSynthesis'in window)){if(!quiet)setError('Playback unavailable. Read the displayed text or try Chrome/Edge.');return false;}
  const voice=window.speechSynthesis.getVoices().find(v=>v.localService&&v.lang.toLowerCase().startsWith('en'));
  if(!voice){if(!quiet)setError('No local English voice is ready. Try Replay after a moment, or enable an English system voice.');return false;}
  const run=++speechRun.current;
  window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(words);u.voice=voice;
  let previousIndex=0,previousElapsed=0,pace=72;
  u.onstart=()=>{if(alive.current&&speechRun.current===run){setSpeechCue({text:words,charIndex:0,wordStartedAt:performance.now(),hasBoundary:false,millisecondsPerCharacter:pace});setSpeaking(true);setStatus('Speaking');}};
  u.onboundary=e=>{
   if(!alive.current||speechRun.current!==run||(e.name&&e.name!=='word'))return;
   if(e.charIndex>previousIndex&&e.elapsedTime>previousElapsed){
    const observed=(e.elapsedTime-previousElapsed)*1000/(e.charIndex-previousIndex);
    if(observed>=35&&observed<=150)pace=pace*.65+observed*.35;
   }
   previousIndex=e.charIndex;previousElapsed=e.elapsedTime||0;
   setSpeechCue({text:words,charIndex:e.charIndex,wordStartedAt:performance.now(),hasBoundary:true,millisecondsPerCharacter:pace});
  };
  u.onend=()=>{if(alive.current&&speechRun.current===run){setSpeaking(false);setStatus('Ready');}};
  u.onerror=()=>{if(alive.current&&speechRun.current===run){setSpeaking(false);setStatus('Ready');if(!quiet)setError('Playback stopped. Replay or read the displayed text.');}};
  window.speechSynthesis.speak(u);return true;
 }
 function stopWelcome(){welcomeSkipped.current=true;speechRun.current++;window.speechSynthesis?.cancel();setSpeaking(false);setStatus('Ready');}
 useEffect(()=>{if(!muted&&view?.current_turn)speak();},[view?.current_turn?.id]);
 useEffect(()=>{
  if(view?.phase!=='not_started'||!('speechSynthesis'in window))return;
  const welcome=()=>{if(!welcomePlayed.current&&!welcomeSkipped.current&&speak(greeting,true))welcomePlayed.current=true;};
  welcome();window.speechSynthesis.addEventListener?.('voiceschanged',welcome);
  return()=>window.speechSynthesis.removeEventListener?.('voiceschanged',welcome);
 },[view?.phase,greeting]);
 async function checkMic(){setError('');try{const s=await navigator.mediaDevices.getUserMedia({audio:true});s.getTracks().forEach(t=>t.stop());setStatus('Microphone permission ready');}catch{setError('Microphone unavailable or permission denied. Allow browser access or use text.');}}
 async function record(){
  if(!view?.current_turn||busy||recording||speaking)return;setBusy(true);setError('');setText('');submission.current=null;
  try{
   if(typeof MediaRecorder==='undefined')throw new Error('Recording unsupported. Try Chrome/Edge or use text.');
   const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw new Error('No supported recording format. Try Chrome/Edge or use text.');
   window.speechSynthesis?.cancel();setSpeaking(false);stream.current=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
   context.current=new AudioContext();const input=context.current.createMediaStreamSource(stream.current),analyser=context.current.createAnalyser();analyser.fftSize=2048;input.connect(analyser);peak.current=0;const samples=new Float32Array(2048);
   function measure(){analyser.getFloatTimeDomainData(samples);peak.current=Math.max(peak.current,Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length));frame.current=requestAnimationFrame(measure);}measure();
   const recorder=new MediaRecorder(stream.current,{mimeType:mime,audioBitsPerSecond:64000});media.current=recorder;chunks.current=[];const turnId=view.current_turn.id;
   let recordedBytes=0;
   recorder.ondataavailable=e=>{if(e.data.size){recordedBytes+=e.data.size;chunks.current.push(e.data);if(recordedBytes>=7.5*1024*1024&&recorder.state==='recording')recorder.stop();}};
   recorder.onerror=()=>{release();chunks.current=[];media.current=null;setRecording(false);setStatus('Ready');setError('Recording failed. Check the microphone and retry.');};
   recorder.onstop=async()=>{
    release();media.current=null;const pieces=chunks.current;chunks.current=[];if(!alive.current)return;setRecording(false);
    if(peak.current<.002||Date.now()-started.current<600){pieces.length=0;setStatus('Ready');setError('No clear microphone signal detected. Speak closer and record again.');return;}
    setBusy(true);setStatus('Transcribing');
    try{const ext=mime.includes('mp4')?'mp4':mime.includes('ogg')?'ogg':'webm';const file=new File(pieces,'answer.'+ext,{type:mime});if(file.size>8*1024*1024)throw new Error('Recording exceeds the 8 MB audio upload capacity. Use text or record again.');
     const result=await api<{text:string}>(route+'/turns/'+turnId+'/transcribe?format='+ext,'POST',file);
     if(alive.current){setText(result.text);setMode('voice');setView(v=>v?.current_turn?.id===turnId?{...v,current_turn:{...v.current_turn,raw_transcript:result.text}}:v);setStatus('Review transcript');}
    }catch(e){if(alive.current){setError((e as Error).message);setStatus('Ready');}}finally{pieces.length=0;if(alive.current)setBusy(false);}
   };
   started.current=Date.now();recorder.start(1000);setRecording(true);setMode('voice');setStatus('Recording');setBusy(false);
  }catch(e){release();setBusy(false);setRecording(false);setStatus('Ready');setError((e as Error).name==='NotAllowedError'?'Microphone permission denied. Allow access or use text.':(e as Error).message);}
 }
 async function action(kind:'start'|'advance'|'answer'|'end',skip=false){
  setBusy(true);setError('');setConfirmEnd(false);setStatus(kind==='end'?'Ending interview':kind==='answer'?'Evaluating, then preparing next question':'Preparing next question');window.speechSynthesis?.cancel();setSpeaking(false);
  try{
   let next:View;if(kind==='answer'){if(!view?.current_turn)throw new Error('Refresh this question.');submission.current??=crypto.randomUUID();next=await api<View>(route+'/answer','POST',{turn_id:view.current_turn.id,submission_id:submission.current,text:skip?'[skipped]':text,mode,skip});}else next=await api<View>(route+'/'+kind,'POST');accept(next);if(next.finalised)onViewReport();
  }catch(e){setError((e as Error).message);setStatus('Error / retry');try{accept(await api<View>(route));}catch{}setStatus('Error / retry');}finally{setBusy(false);}
 }
 const activity:InterviewActivity=recording?'listening':speaking?'speaking':busy?(status==='Transcribing'?'transcribing':'processing'):'ready';
 return <section className="analysis-workspace interview-workspace">
  <div className="session-heading interview-heading"><div><p className="eyebrow">PERSONALISED INTERVIEW PRACTICE</p><h2>{view?.phase==='not_started'?'Welcome':view?.level_name||'Interview'}</h2></div><div className="interview-header-actions">{view&&!view.finalised&&view.phase!=='not_started'&&<button id="end-interview" className="secondary" disabled={busy||recording} onClick={()=>{window.speechSynthesis?.cancel();setSpeaking(false);setConfirmEnd(true);}}>End interview</button>}<button className="quiet" disabled={busy||recording} onClick={onClose}>Back to session</button></div></div>
  {confirmEnd&&<div className="notice" role="region" aria-labelledby="end-title"><h3 id="end-title" tabIndex={-1}>End this interview permanently?</h3><p>Only submitted answers are kept as accepted answers. Your current draft is not submitted. This attempt cannot resume; a new attempt is separate.</p><div className="actions"><button className="primary" disabled={busy} onClick={()=>action('end')}>End permanently</button><button className="secondary" disabled={busy} onClick={()=>setConfirmEnd(false)}>Keep interviewing</button></div></div>}
  <p className="notice">Screening → Competency → Deep Dive. Questions build on your answers across levels. Submitted answers are saved. Your report and preparation guidance become available when this attempt ends.</p>
  {error&&<p className="error" role="alert">{error}</p>}<div className="interview-status"><span role="status" className="badge">{status}</span><span>{view?.phase==='not_started'?'Before Screening':`Level ${view?.level||1} / 3 · Question ${view?.current_turn?.number||view?.turns_used||0} / ${view?.budget||4} · ${view?.total_turns_used||0} / 15 overall`}</span></div>
  {view&&<InterviewStage activity={activity} finished={view.finalised} speechCue={speaking?speechCue:undefined} greeting={view.phase==='not_started'}/>}
  {!view?<p>Loading…</p>:view.phase==='not_started'?<><section className="interview-welcome" aria-labelledby="welcome-heading"><p className="eyebrow">BEFORE WE BEGIN</p><h3 id="welcome-heading">Welcome{candidateName?', '+candidateName:''}.</h3><p>{greeting}</p><div className="actions"><button className="quiet" disabled={speaking} onClick={()=>{welcomePlayed.current=true;speak(greeting);}}>Replay welcome</button>{speaking&&<button className="quiet" onClick={stopWelcome}>Skip welcome</button>}</div></section><p>Questions use your saved role and resume. Correct transcription errors before submitting. Accepted answers cannot be replaced.</p><div className="actions"><button className="secondary" onClick={checkMic}>Check microphone</button><button className="primary" disabled={busy||speaking} onClick={()=>action('start')}>Start Screening</button></div></>:view.finalised?<div className="notice"><h3>{view.status==='completed'?'Interview complete':'Interview ended early'}</h3><p>This attempt is read-only. {view.coverage.answered} submitted answers, {view.coverage.skipped} skipped questions and {view.coverage.evaluated} completed evaluations are saved.</p>{view.coverage.pending_evaluations>0&&<p>{view.coverage.pending_evaluations} accepted answers remain without a completed evaluation; they are not scored as failures.</p>}<p>Review the three level histories below. Return to the saved session to create a separate new attempt. Your report explains scores, coverage and preparation priorities.</p><button className="primary" onClick={onViewReport}>View report and preparation</button></div>:view.phase==='level_complete'?<div className="notice"><p>Screening is complete. Continue with Competency using the same saved context.</p><button className="primary" disabled={busy} onClick={()=>action('advance')}>Continue to Competency</button></div>:view.current_turn?<>
   <div className={'interviewer-panel '+(speaking?'is-speaking':'')}><p className="eyebrow">CURRENT QUESTION</p><h3>{view.current_turn.question_text}</h3></div>
   <div className="actions"><button className="secondary" disabled={recording||busy||muted} onClick={()=>speak()}>Replay question</button><button className="quiet" onClick={()=>{setMuted(!muted);window.speechSynthesis?.cancel();setSpeaking(false);setStatus('Ready');}}>{muted?'Unmute questions':'Mute questions'}</button></div>
   <div className="actions">{recording?<button className="primary" onClick={()=>media.current?.stop()}>Stop and transcribe</button>:<button className="primary" disabled={busy||speaking} onClick={record}>Record answer</button>}<button className="secondary" disabled={busy||recording} onClick={()=>{window.speechSynthesis?.cancel();setSpeaking(false);setMode('text');setText('');setStatus('Typed fallback');}}>Use text instead</button></div>
   <p className="small">No answer word or time limit. Recording stops near the 8 MB audio upload capacity. Audio goes to Groq for transcription, then this app discards it. Provider retention follows the settings and policies of the configured account.</p>
   <label htmlFor="answer">{mode==='voice'?'Review transcript — correct transcription errors only':'Typed answer'}</label><textarea id="answer" value={text} disabled={busy||recording} readOnly={mode==='voice'&&!view.current_turn.raw_transcript&&status!=='Review transcript'} onChange={e=>setText(e.target.value)}/>
   <div className="actions"><button className="primary" disabled={busy||recording||!text.trim()} onClick={()=>action('answer')}>Submit answer</button><button className="secondary" disabled={busy||recording} onClick={()=>action('answer',true)}>Skip question</button></div>
  </>:<div className="notice"><p>{view.error||'Accepted work is saved. Retry processing to prepare the next question.'}</p><button className="primary" disabled={busy} onClick={()=>action('advance')}>Retry processing</button></div>}
  {view&&<section className="history"><h3>Saved level histories</h3><nav className="tabs" aria-label="Interview level histories">{view.levels.map(l=><button key={l.number} aria-current={historyLevel===l.number?'page':undefined} onClick={()=>setHistoryLevel(l.number)}>{l.name} · {l.history.length}/{l.budget}</button>)}</nav>{view.levels.filter(l=>l.number===historyLevel).map(l=><div key={l.number}><p className="small">{l.status.replaceAll('_',' ')}</p>{!l.history.length?<p className="small">No accepted answers in this level yet.</p>:l.history.map(t=><article className="match" key={t.id}><h4>{t.number}. {t.question}</h4><p>{t.status==='skipped'?'Skipped':t.status==='unanswered_at_finalisation'?'Not answered before this attempt ended':t.answer}</p><p className="small">Response duration: {responseDuration(t.response_duration_seconds,t.mode,t.status)}</p>{t.raw_transcript&&<details><summary>Raw transcript</summary><p>{t.raw_transcript}</p></details>}{t.filler_count!==null&&<p className="small">Detected transcript fillers: {t.filler_count}. Speech recognition may omit fillers.</p>}</article>)}</div>)}</section>}
 </section>;
}
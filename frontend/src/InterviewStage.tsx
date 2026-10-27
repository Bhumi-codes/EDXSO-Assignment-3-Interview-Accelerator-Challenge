import {lazy,Suspense,useEffect,useRef,useState} from 'react';
import type {SpeechCue} from './InterviewerAvatar';
const InterviewerAvatar=lazy(()=>import('./InterviewerAvatar'));

export type InterviewActivity='ready'|'speaking'|'listening'|'transcribing'|'processing';
const labels:Record<InterviewActivity,string>={ready:'Ready',speaking:'Speaking',listening:'Listening',transcribing:'Transcribing',processing:'Preparing'};
const descriptions:Record<InterviewActivity,string>={ready:'Take your time. Start recording when you are ready.',speaking:'Listen to the question. You can replay it before recording.',listening:'Your microphone is recording your answer.',transcribing:'Preparing your transcript for review.',processing:'Preparing the next step of your interview.'};

export function InterviewStage({activity,finished=false,speechCue,greeting=false}:{activity:InterviewActivity;finished?:boolean;speechCue?:SpeechCue;greeting?:boolean}){
 const video=useRef<HTMLVideoElement|null>(null),camera=useRef<MediaStream|null>(null),mounted=useRef(false),request=useRef(0);
 const [enabled,setEnabled]=useState(false),[pending,setPending]=useState(false),[error,setError]=useState('');
 function release(){
  request.current+=1;
  camera.current?.getTracks().forEach(track=>{track.onended=null;track.stop();});camera.current=null;
  if(video.current)video.current.srcObject=null;
 }
 function stop(){release();if(mounted.current){setEnabled(false);setPending(false);}}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;release();};},[]);
 useEffect(()=>{if(finished)stop();},[finished]);
 async function start(){
  setError('');
  if(!navigator.mediaDevices?.getUserMedia){setError('Camera preview requires HTTPS or localhost and a supported browser. You can continue without it.');return;}
  const token=++request.current;setPending(true);
  try{
   // This video-only stream is used solely by this local preview. It is never
   // passed to MediaRecorder, an audio stream, a network request or storage.
   const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:'user',width:{ideal:1280},height:{ideal:720}}});
   if(!mounted.current||request.current!==token){stream.getTracks().forEach(track=>track.stop());return;}
   camera.current=stream;
   stream.getVideoTracks().forEach(track=>{track.onended=()=>{stop();if(mounted.current)setError('Camera disconnected. You can turn it on again or continue without it.');};});
   if(video.current){video.current.srcObject=stream;await video.current.play();}
   if(mounted.current&&request.current===token){setEnabled(true);setPending(false);}
  }catch(reason){
   if(!mounted.current||request.current!==token)return;
   release();setEnabled(false);setPending(false);
   const name=(reason as DOMException).name;
   setError(name==='NotAllowedError'?'Camera access was not allowed. You can continue with voice or text.':name==='NotFoundError'?'No camera was found. You can continue with voice or text.':'Camera preview is unavailable. Close other camera apps and try again, or continue without it.');
  }
 }
 if(finished)return null;
 return <section className="interview-stage" aria-label="Interview room">
  <div className={'interviewer-seat activity-'+activity}>
   <div className="seat-heading"><span className="seat-label">AI interviewer</span><span className="activity-label" role="status"><span aria-hidden="true"/>{labels[activity]}</span></div>
   <Suspense fallback={<div className="avatar-office"><span className="avatar-loading">Preparing your interviewer…</span></div>}><InterviewerAvatar activity={activity} speechCue={speechCue} greeting={greeting}/></Suspense>
   <p className="seat-description">{greeting?(activity==='speaking'?'A brief welcome before we begin.':'Start Screening when you are ready.'):descriptions[activity]}</p>
  </div>
  <div className="candidate-seat">
   <div className="seat-heading"><span className="seat-label">Your camera</span><button type="button" className="camera-toggle" aria-pressed={enabled||pending} onClick={enabled||pending?stop:start}>{pending?'Cancel':enabled?'Turn camera off':'Turn camera on'}</button></div>
   <div className={'camera-preview '+(enabled?'camera-enabled':'')}>
    <video ref={video} autoPlay muted playsInline disablePictureInPicture aria-label="Your local camera preview"/>
    {!enabled&&<div className="camera-placeholder"><svg width="36" height="36" viewBox="0 0 32 32" fill="none" aria-hidden="true"><rect x="4" y="9" width="17" height="15" rx="4" stroke="currentColor" strokeWidth="1.5"/><path d="m21 14 7-4v13l-7-4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg><strong>{pending?'Waiting for camera access':'Camera is off'}</strong>{pending&&<span>Allow access in your browser to preview your video.</span>}</div>}
    {enabled&&<span className="camera-caption">You · Local preview</span>}
   </div>
   {error&&<p className="camera-message" role="status">{error}</p>}
  </div>
 </section>;
}

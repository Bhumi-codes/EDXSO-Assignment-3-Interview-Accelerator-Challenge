// Browser word boundaries guide this modest animation; they are not phoneme audio alignment.
export type SpeechCue = {
 text:string;
 charIndex:number;
 wordStartedAt?:number;
 hasBoundary?:boolean;
 millisecondsPerCharacter?:number;
};
const visemes=['viseme_aa','viseme_E','viseme_I','viseme_O','viseme_U','viseme_PP','viseme_FF','viseme_TH','viseme_DD','viseme_kk','viseme_CH','viseme_SS','viseme_nn','viseme_RR'];
export function speechMouthPose(cue:SpeechCue|undefined,now:number,talking:boolean){
 const pose:Record<string,number>=Object.fromEntries(visemes.map(v=>[v,0]));pose.jawOpen=0;
 if(!talking||!cue?.text||cue.wordStartedAt===undefined)return pose;
 const pace=Math.max(45,Math.min(110,cue.millisecondsPerCharacter||72));
 const elapsed=Math.max(0,now-cue.wordStartedAt);
 let index=cue.charIndex,wordElapsed=elapsed;
 // A fallback for voices without word events. Punctuation reserves a closed-mouth pause.
 if(!cue.hasBoundary){
  for(const match of cue.text.matchAll(/\S+/g)){
   const duration=Math.max(180,Math.min(900,match[0].length*pace));
   const pause=/[.!?]$/.test(match[0])?300:/[,;:]$/.test(match[0])?160:70;
   if(wordElapsed<duration+pause){index=match.index!;break;}
   wordElapsed-=duration+pause;index=cue.text.length;
  }
 }
 const word=cue.text.slice(index).match(/^\S+/)?.[0]||'';
 const letters=word.replace(/[^a-z]/gi,'').toLowerCase();
 const duration=Math.max(180,Math.min(900,word.length*pace));
 if(!letters||wordElapsed>=duration)return pose;
 const progress=wordElapsed/duration;
 const envelope=Math.min(1,wordElapsed/65,(duration-wordElapsed)/95);
 const letter=letters[Math.min(letters.length-1,Math.floor(progress*letters.length))];
 const shape=/[pbm]/.test(letter)?'PP':/[fv]/.test(letter)?'FF':/[ou]/.test(letter)?'O':/[ei]/.test(letter)?'E':/[sz]/.test(letter)?'SS':/[tdn]/.test(letter)?'DD':/[kg]/.test(letter)?'kk':/[r]/.test(letter)?'RR':'aa';
 // One viseme at a time; stacking vowel shapes was causing exaggerated, rapid motion.
 const amplitude=.17*Math.max(0,envelope)*(.78+.22*Math.sin(Math.PI*progress));
 pose['viseme_'+shape]=amplitude;
 pose.jawOpen=shape==='PP'?0:amplitude*.12;
 return pose;
}

import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import type {InterviewActivity} from './InterviewStage';
import {speechMouthPose,type SpeechCue} from './speechMotion';
export type {SpeechCue} from './speechMotion';

export default function InterviewerAvatar({activity,speechCue,greeting=false}:{activity:InterviewActivity;speechCue?:SpeechCue;greeting?:boolean}){
 const host=useRef<HTMLDivElement|null>(null),live=useRef({activity,speechCue,greeting});
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false);
 useEffect(()=>{live.current={activity,speechCue,greeting};},[activity,speechCue,greeting]);
 useEffect(()=>{
  const container=host.current;if(!container)return;
  let disposed=false,frame=0,last=0,started=0;
  let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});}catch{setFailed(true);return;}
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;container.appendChild(renderer.domElement);
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(31,1,.01,20);
  scene.add(new THREE.HemisphereLight(0xfff9f0,0x9da5a1,2.4));
  const key=new THREE.DirectionalLight(0xfff6e9,1.7);key.position.set(-1,2,3);scene.add(key);
  const fill=new THREE.DirectionalLight(0xe4edf3,.75);fill.position.set(2,1,2);scene.add(fill);
  const meshes:THREE.Mesh[]=[],materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>();
  let model:THREE.Group|undefined,head:THREE.Object3D|undefined,headWorld=new THREE.Quaternion(),parentInverse=new THREE.Quaternion(),restY=0;
  const headDelta=new THREE.Quaternion(),rotation=new THREE.Euler();
  function bounds(object:THREE.Object3D){object.updateMatrixWorld(true);object.traverse(o=>{if(o instanceof THREE.SkinnedMesh)o.computeBoundingBox();});return new THREE.Box3().setFromObject(object);}
  function disposeModel(object:THREE.Object3D){object.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>{for(const v of Object.values(m))if(v instanceof THREE.Texture)v.dispose();m.dispose();});}});}
  new GLTFLoader().load('/assets/interviewer/professional-interviewer.glb',gltf=>{
   if(disposed){disposeModel(gltf.scene);return;}
   model=gltf.scene;
   // One complete, consistently authored male model. Preserve its original eyes,
   // skin, hair and clothing instead of mixing unrelated parts or fake pupils.
   model.traverse(o=>{if(o instanceof THREE.Mesh){meshes.push(o);const ms=Array.isArray(o.material)?o.material:[o.material];for(const m of ms){materials.add(m);for(const v of Object.values(m))if(v instanceof THREE.Texture)textures.add(v);if(m instanceof THREE.MeshStandardMaterial){m.metalness=0;m.roughness=Math.max(.65,m.roughness);}}}});
   scene.add(model);let box=bounds(model);const height=box.max.y-box.min.y;
   if(height>0)model.scale.multiplyScalar(1.8/height);
   box=bounds(model);model.position.y-=box.min.y;model.updateMatrixWorld(true);
   const face=meshes.find(m=>(Array.isArray(m.material)?m.material:[m.material]).some(mat=>/head/i.test(mat.name)));
   if(face){
    const positions=face.geometry.getAttribute('position');let max=-Infinity,index=0;
    for(let i=0;i<positions.count;i++)if(positions.getZ(i)>max){max=positions.getZ(i);index=i;}
    const nose=new THREE.Vector3().fromBufferAttribute(positions,index);
    if(face instanceof THREE.SkinnedMesh)face.applyBoneTransform(index,nose);face.localToWorld(nose);
    const centre=new THREE.Box3().setFromObject(face).getCenter(new THREE.Vector3());
    const direction=nose.sub(centre);direction.y=0;
    if(direction.length()>.0001)model.rotation.y-=Math.atan2(direction.x,direction.z);
   }
   model.updateMatrixWorld(true);head=model.getObjectByName('Head');
   const faceBox=face?bounds(face):bounds(model);const centre=faceBox.getCenter(new THREE.Vector3());
   const faceHeight=faceBox.max.y-faceBox.min.y;const target=new THREE.Vector3(centre.x,centre.y+faceHeight*.035,centre.z);
   const distance=Math.max(.7,faceHeight*2.7);
   camera.position.set(target.x,target.y+.015,target.z+distance);camera.lookAt(target);
   if(head){headWorld=head.getWorldQuaternion(new THREE.Quaternion());parentInverse=head.parent?.getWorldQuaternion(new THREE.Quaternion()).invert()||new THREE.Quaternion();}
   restY=model.position.y;setReady(true);
  },undefined,()=>{if(!disposed)setFailed(true);});
  const resize=new ResizeObserver(()=>{const w=container.clientWidth,h=container.clientHeight;if(w&&h){camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);}});resize.observe(container);
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  function animate(now:number){
   frame=requestAnimationFrame(animate);if(document.hidden||now-last<32)return;const dt=Math.min(100,now-last);last=now;if(!started)started=now;
   const t=(now-started)/1000,state=live.current;
   const talking=state.activity==='speaking',reduce=reduced.matches;
   if(container)container.dataset.motion=reduce?'reduced':'full';
   const blink=reduce?0:Math.max(0,1-Math.abs((t%4.7)-4.45)/.12);
   if(head){rotation.set(reduce?0:Math.sin(t*.82)*.012+(state.activity==='listening'?Math.sin(t*1.4)*.012:0),reduce?0:Math.sin(t*.58)*.025+(talking?Math.sin(t*1.5)*.018:0),reduce?0:Math.sin(t*.37)*.008);headDelta.setFromEuler(rotation);head.quaternion.copy(parentInverse).multiply(headDelta).multiply(headWorld);}
   if(model)model.position.y=restY+(reduce?0:Math.sin(t*1.6)*.001);
   const targets:Record<string,number>={...speechMouthPose(state.speechCue,now,talking),eyeBlinkLeft:blink,eyeBlinkRight:blink,mouthSmileLeft:talking?.015:state.greeting?.08:.035,mouthSmileRight:talking?.015:state.greeting?.08:.035};
   for(const mesh of meshes)if(mesh.morphTargetDictionary&&mesh.morphTargetInfluences){for(const [name,value] of Object.entries(targets)){const index=mesh.morphTargetDictionary[name];if(index!==undefined)mesh.morphTargetInfluences[index]=THREE.MathUtils.lerp(mesh.morphTargetInfluences[index],value,name.startsWith('eyeBlink')?.85:1-Math.exp(-dt/85));}}
   renderer.render(scene,camera);
  }
  frame=requestAnimationFrame(animate);
  return()=>{disposed=true;cancelAnimationFrame(frame);resize.disconnect();meshes.forEach(m=>m.geometry.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();};
 },[]);
 return <div ref={host} className="avatar-office" data-avatar-ready={ready} data-avatar-state={activity} role="img" aria-label={'Alex, animated 3D AI interviewer, '+activity}>
  {!ready&&!failed&&<span className="avatar-loading">Preparing your interviewer…</span>}
  {failed&&<span className="avatar-loading">3D view is unavailable. You can continue using voice or text.</span>}
  <span className="avatar-nameplate">Alex · AI interviewer</span>
 </div>;
}


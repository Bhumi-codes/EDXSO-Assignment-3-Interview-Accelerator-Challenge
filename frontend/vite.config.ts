import {defineConfig,loadEnv} from 'vite';
import process from 'node:process';

export default defineConfig(({command,mode})=>{
 if(command==='build'){
  const values={...loadEnv(mode,process.cwd(),''),...process.env};
  let project:URL;
  try{project=new URL(values.VITE_SUPABASE_URL||'');}
  catch{throw new Error('Set VITE_SUPABASE_URL before building the frontend.');}
  if(project.protocol!=='https:'||project.pathname!=='/'||project.search||project.hash)throw new Error('VITE_SUPABASE_URL must be an HTTPS project origin.');
  const key=values.VITE_SUPABASE_PUBLISHABLE_KEY||'';
  let role:string|undefined;
  try{role=JSON.parse(Buffer.from(key.split('.')[1]||'','base64url').toString()).role;}catch{/* New publishable keys are not JWTs. */}
  if(!key.startsWith('sb_publishable_')&&role!=='anon')throw new Error('Use a Supabase public publishable/anon key for VITE_SUPABASE_PUBLISHABLE_KEY, never a private provider or service-role key.');
 }
 return {server:{proxy:{'/api':'http://127.0.0.1:8000'}}};
});

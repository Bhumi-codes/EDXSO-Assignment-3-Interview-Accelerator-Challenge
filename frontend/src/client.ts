import { createClient } from '@supabase/supabase-js';
const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
export const supabase = url && key ? createClient(url, key, {
  auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true }
}) : null;

async function apiResponse(path: string, method = 'GET', body?: unknown): Promise<Response> {
  const { data } = await supabase!.auth.getSession();
  if (!data.session) throw new Error('Please sign in again.');
  const response = await fetch('/api' + path, {
    method, headers: { Authorization: 'Bearer ' + data.session.access_token, 'Content-Type': body instanceof File ? 'application/octet-stream' : 'application/json' },
    ...(body ? { body: body instanceof File ? body : JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Unable to complete this request. Please retry.');
  }
  return response;
}
export async function api<T>(path:string,method='GET',body?:unknown):Promise<T>{
  return (await apiResponse(path,method,body)).json();
}

export async function downloadReport(path:string):Promise<void>{
  const response=await apiResponse(path);
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);
  const anchor=document.createElement('a');
  anchor.href=url;
  anchor.download=response.headers.get('Content-Disposition')?.match(/filename="([^"\r\n]+)"/)?.[1]||'interview-report.pdf';
  document.body.appendChild(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(url),30000);
}

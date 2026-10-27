import { useEffect, useRef, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import type { Session } from '@supabase/supabase-js';
import { api, supabase } from './client';
import './styles.css';
import {InterviewJourney} from './InterviewJourney';
import {HeroTagline} from './HeroTagline';
import { SessionWorkspace, type Detail } from './SessionWorkspace';

type Attempt = { id: string; title: string; status: string; created_at: string };
type Route = { sessionId: string | null; panel: string };
function currentRoute(): Route {
  const params = new URLSearchParams(window.location.search);
  return { sessionId: params.get('session'), panel: params.get('panel') || '' };
}
export function App() {
  const [auth, setAuth] = useState<Session | null>(null);
  const [loading, setLoading] = useState(Boolean(supabase));
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [route, setRoute] = useState<Route>(currentRoute);
  const authUserId = useRef<string | null>(null);
  const sessionsPage = new URLSearchParams(window.location.search).get('view') === 'sessions';
  function navigateSession(sessionId: string | null, panel = '', replace = false) {
    const url = new URL(window.location.href);
    if (sessionId) url.searchParams.set('session', sessionId);
    else url.searchParams.delete('session');
    if (sessionId && panel) url.searchParams.set('panel', panel);
    else url.searchParams.delete('panel');
    window.history[replace ? 'replaceState' : 'pushState'](null, '', url);
    setRoute({ sessionId, panel });
  }
  useEffect(() => {
    function onPopState() { setSelected(null); setRoute(currentRoute()); }
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  useEffect(() => {
    if (!auth || !route.sessionId || selected?.id === route.sessionId) return;
    let active = true;
    api<Detail>('/sessions/' + route.sessionId).then(item => {
      if (active) { setSelected(item); setError(''); }
    }).catch(e => {
      if (active) { setError((e as Error).message); setSelected(null); navigateSession(null, '', true); }
    });
    return () => { active = false; };
  }, [auth?.user.id, route.sessionId, selected?.id]);
  const [menuOpen,setMenuOpen]=useState(false);
  const accountDialog=useRef<HTMLDialogElement|null>(null);
  const fullName=typeof auth?.user.user_metadata.full_name==='string'?auth.user.user_metadata.full_name.trim():'';
  const firstName=fullName.split(/\s+/)[0]||'candidate';
  useEffect(()=>{const dialog=accountDialog.current;if(!dialog)return;if(menuOpen&&!dialog.open)dialog.showModal();else if(!menuOpen&&dialog.open)dialog.close();},[menuOpen]);
  async function logout(){const {error}=await supabase!.auth.signOut();if(error)setError(error.message);else setMenuOpen(false);}
  async function openAttempt(id:string){try{setSelected(await api<Detail>('/sessions/'+id));navigateSession(id);setError('');window.scrollTo({top:0,behavior:'instant'});}catch(e){setError((e as Error).message);}}

  useEffect(() => {
    if (!supabase) return;
    function updateAuth(session: Session | null) {
      const nextUserId = session?.user.id ?? null;
      if (authUserId.current !== nextUserId) {
        setAttempts([]); setSelected(null); setError('');
      }
      authUserId.current = nextUserId;
      setAuth(session); setLoading(false);
    }
    supabase.auth.getSession().then(({ data, error }) => {
      updateAuth(data.session); if (error) setError(error.message);
    }).catch(() => { setLoading(false); setError('Unable to restore your sign-in. Please retry.'); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      updateAuth(session);
    });
    return () => subscription.unsubscribe();
  }, []);
  useEffect(() => {
    if (!auth) return;
    let active = true;
    api<Attempt[]>('/sessions').then(items => { if (active) setAttempts(items); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [auth]);
  async function login() {
    setBusy(true); setError('');
    try {
      const { error } = await supabase!.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } });
      if (error) throw error;
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const item = await api<Detail>('/sessions', 'POST', { title });
      setAttempts(items => [item, ...items]); setSelected(item); navigateSession(item.id); setTitle('');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="shell app-shell">
    {!selected&&!(sessionsPage&&auth)&&<div className="home-atmosphere" aria-hidden="true"><span className="atmosphere-glow glow-sage"/><span className="atmosphere-glow glow-sand"/><span className="atmosphere-grid"/><span className="atmosphere-orbit"/></div>}
    <header className="site-header"><a className="brand ace-brand" href="/" aria-label="Ace-it home"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M6 25 16 6l10 19M10 19h12" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/><path d="m21 7 2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></span><span>Ace-it<span className="brand-caption">Your interview. Your next step.</span></span></a>
      <nav className="header-nav" aria-label="Main navigation"><a href="/" aria-current={!sessionsPage&&!selected?'page':undefined}>Home</a>{auth&&<a href="/?view=sessions" target="_blank" rel="noopener noreferrer">Previous sessions <span aria-hidden="true">↗</span></a>}</nav>
      <button className="menu-toggle" aria-label="Open account menu" aria-expanded={menuOpen} aria-controls="account-menu" onClick={()=>setMenuOpen(true)}><svg viewBox="0 0 24 24" width="23" height="23" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg></button>
    </header>
    <dialog id="account-menu" ref={accountDialog} className="account-drawer" onClose={()=>setMenuOpen(false)} onClick={e=>{if(e.target===e.currentTarget)setMenuOpen(false);}} aria-labelledby="account-title"><div className="drawer-content"><div className="drawer-heading"><p className="eyebrow">YOUR SPACE</p><button className="menu-toggle" aria-label="Close account menu" onClick={()=>setMenuOpen(false)}>×</button></div><h2 id="account-title">Your account</h2>{auth?<><div className="account-avatar" aria-hidden="true">{(fullName||auth.user.email||'A').slice(0,1).toUpperCase()}</div><h3>{fullName||'Your account'}</h3><p className="account-email">{auth.user.email}</p><span className="badge">Signed in with Google</span><nav className="drawer-links" aria-label="Account navigation"><a href="/">Home</a><a href="/?view=sessions" target="_blank" rel="noopener noreferrer">Previous sessions ↗</a></nav><button className="secondary" onClick={logout}>Sign out</button></>:<><p>Sign in to save your interview practice and reports.</p><button className="primary" disabled={!supabase||busy} onClick={login}>Continue with Google</button></>}<p className="small drawer-note">Your sessions and reports stay in your account.</p></div></dialog>
    <main className={selected||route.sessionId&&auth?'expanded app-main':sessionsPage&&auth?'sessions-main app-main':'home-main app-main'}>
      {route.sessionId&&auth&&!selected?<section role="status" className="analysis-workspace">Restoring your interview…</section>:selected&&auth?<SessionWorkspace candidateName={firstName} key={selected.id} initial={selected} initialPanel={route.panel} onPanelChange={panel=>navigateSession(selected.id,panel,true)} onClose={()=>{setSelected(null);navigateSession(null);}} onNewAttempt={value=>{setAttempts(items=>[value,...items.filter(item=>item.id!==value.id)]);setSelected(value);navigateSession(value.id);}} onUpdate={value=>setAttempts(items=>items.map(item=>item.id===value.id?value:item))}/> : sessionsPage&&auth?<section className="sessions-page" aria-labelledby="sessions-title"><div className="session-heading"><div><p className="eyebrow">YOUR INTERVIEW LIBRARY</p><h1 id="sessions-title">Pick up where you left off.</h1><p>Open a saved interview, continue your practice or revisit your report.</p></div><a className="secondary" href="/">New interview <span aria-hidden="true">+</span></a></div><div className="session-list">{attempts.length===0?<div className="empty-sessions"><h3>A fresh start.</h3><p>Your interviews will appear here once you create a session.</p><a className="secondary" href="/">Create your first interview</a></div>:attempts.map(item=><button className="attempt session-row" key={item.id} onClick={()=>openAttempt(item.id)}><span className="session-row-icon" aria-hidden="true">↗</span><span className="session-row-title"><strong>{item.title}</strong><small>{new Date(item.created_at).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'})}</small></span><span className="badge">{({ended_early:'Ended early',in_progress:'In progress',ready:'Ready',completed:'Completed',analysing:'Analysing',draft:'Draft'} as Record<string,string>)[item.status]||item.status.replaceAll('_',' ')}</span><span aria-hidden="true">→</span></button>)}</div>{error&&<p className="error" role="alert">{error}</p>}</section>:<>
      <section className="intro home-hero" aria-labelledby="hero-title"><div className="hero-orbit" aria-hidden="true"/><p className="eyebrow"><span className="live-dot"/> AI-PERSONALISED INTERVIEW PRACTICE</p><HeroTagline/><p className="lede">Practise with an AI interviewer that adapts to your resume, your target role and your answers. Get focused feedback and a clear plan for what to prepare next.</p><div className="hero-features"><span>Built around your resume &amp; JD</span><span>Voice-first practice</span><span>Actionable feedback</span></div><a className="explore-journey" href="#interview-journey">Explore your interview journey <span aria-hidden="true">↓</span></a></section>
      <section id="start-interview" className="workspace start-card" aria-label={auth?'Start a new interview':'Sign in'}>
        {loading?<p role="status">Restoring your sign-in…</p>:!auth?<><span className="symbol" aria-hidden="true">↗</span><p className="eyebrow">MAKE YOUR NEXT INTERVIEW COUNT</p><h2>A little practice.<br/>A clearer next step.</h2><p>Sign in to start personalised interview practice and keep your progress in one place.</p><button className="primary" disabled={!supabase||busy} onClick={login}>{busy?'Opening Google…':'Continue with Google'}<span aria-hidden="true">→</span></button>{!supabase&&<p className="notice">Sign-in is not available yet. Please try again once setup is complete.</p>}<p className="small">Preparation guidance, not a hiring prediction.</p></>:<><p className="eyebrow">YOUR NEXT PRACTICE STARTS HERE</p><h2>Welcome, {firstName}.</h2><p>Name your interview, then add your resume and the role you want to prepare for.</p><form onSubmit={create}><label htmlFor="title">Interview name</label><input id="title" value={title} onChange={e=>setTitle(e.target.value)} maxLength={160} placeholder="e.g. AI Engineer Intern · Acme" required/><button className="primary" disabled={busy||!title.trim()}>{busy?'Creating…':'Create interview'}<span aria-hidden="true">+</span></button></form><a className="previous-sessions-link" href="/?view=sessions" target="_blank" rel="noopener noreferrer">View previous sessions <span aria-hidden="true">↗</span></a><p className="small">Your saved interviews and reports open in a separate tab.</p></>}{error&&<p className="error" role="alert">{error}</p>}
      </section><InterviewJourney/></>}
    </main>
    <footer className="site-footer"><a href="/" className="footer-brand">Ace-it</a><span>AI-personalised interview practice.</span><span>Prepare with purpose. Progress with clarity.</span></footer>
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);

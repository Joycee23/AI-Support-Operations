import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDownUp, ChevronRight, CircleAlert, LoaderCircle, Search } from 'lucide-react';
import { ApiError, api } from './api';
import type { AISuggestion, Bootstrap, Page, TicketDetail } from './types';
import { billingDate, subscriptionLabel } from './components/BillingSection';
import { Sidebar } from './components/Sidebar';
import { Button } from './components/ui';
import { DashboardPage } from './pages/DashboardPage';
import { InboxPage } from './pages/InboxPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { TeamsPage } from './pages/TeamsPage';
import { ReportsPage } from './pages/ReportsPage';
import { AuditPage } from './pages/AuditPage';
import { AuthPage } from './pages/AuthPage';
import { SettingsPage } from './pages/SettingsPage';
import { AccountLinkPage } from './pages/AccountLinkPage';

const pages: Record<Page, string> = { overview: 'Tổng quan', inbox: 'Hộp thư', knowledge: 'Kho kiến thức', teams: 'Nhóm & thành viên', reports: 'Chất lượng AI', audit: 'Nhật ký hoạt động', settings: 'Cấu hình' };

export function App() {
  const [accountLink] = useState(() => { const hash = new URLSearchParams(window.location.hash.slice(1)); return hash.has('verify') ? { purpose: 'verify' as const, token: hash.get('verify')! } : hash.has('reset') ? { purpose: 'reset' as const, token: hash.get('reset')! } : null; });
  const [userId, setUserId] = useState('');
  const [needsAuth, setNeedsAuth] = useState(false);
  const invitationToken = new URLSearchParams(window.location.hash.slice(1)).get('invite');
  const [data, setData] = useState<Bootstrap | null>(null);
  const [page, setPage] = useState<Page>('overview');
  useEffect(() => { window.scrollTo({ top: 0, left: 0, behavior: 'instant' }); }, [page]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [suggestion, setSuggestion] = useState<AISuggestion | null>(null);
  const [draft, setDraft] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState('');
  const requestVersion = useRef(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [ticketSearch, setTicketSearch] = useState('');

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(current => current === message ? '' : current), 4200);
  }, []);

  const refresh = useCallback(async () => {
    const next = await api.bootstrap(userId);
    setData(next);
    setSelectedId(current => current && next.tickets.some(ticket => ticket.id === current) ? current : next.tickets[0]?.id || null);
    setError('');
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.bootstrap(userId).then(next => {
      if (cancelled) return;
      setData(next); setUserId(next.user.id); setNeedsAuth(false);
      setSelectedId(current => current && next.tickets.some(ticket => ticket.id === current) ? current : next.tickets[0]?.id || null);
      setError('');
    }).catch((reason: ApiError) => {
      if (cancelled) return;
      if (reason.status === 401) { setNeedsAuth(true); setData(null); } else setError(reason.message);
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [userId]);

  useEffect(() => {
    if (!userId) return;
    const update = () => { void refresh().catch(reason => notify(reason.message)); };
    const timer = window.setInterval(update, 60000);
    window.addEventListener('subscription-expired', update);
    return () => { window.clearInterval(timer); window.removeEventListener('subscription-expired', update); };
  }, [userId, refresh, notify]);

  useEffect(() => {
    const expire = () => { requestVersion.current += 1; setData(null); setNeedsAuth(true); setSelectedId(null); };
    window.addEventListener('session-expired', expire);
    return () => window.removeEventListener('session-expired', expire);
  }, []);

  useEffect(() => {
    requestVersion.current += 1;
    setAiBusy(false); setAiError(''); setDetail(null);
    if (page !== 'inbox' || !selectedId) return;
    let cancelled = false;
    api.ticket(selectedId, userId).then(value => { if (!cancelled) setDetail(value); }).catch(reason => notify(reason.message));
    setSuggestion(null); setDraft('');
    return () => { cancelled = true; requestVersion.current += 1; };
  }, [selectedId, page, userId, notify]);

  const updateTicket = async (body: Record<string, unknown>) => {
    if (!selectedId) return;
    const ticketId = selectedId;
    const version = requestVersion.current;
    setBusy(true);
    try {
      await api.updateTicket(ticketId, userId, body);
      await refresh();
      const updated = await api.ticket(ticketId, userId);
      if (version === requestVersion.current) {
        setDetail(updated);
        if (typeof body.reply === 'string') setDraft('');
      }
      notify('Đã lưu thay đổi.');
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : 'Không thể lưu thay đổi.');
      throw reason;
    } finally { setBusy(false); }
  };

  const createSuggestion = async () => {
    if (!selectedId) return;
    const version = ++requestVersion.current;
    setAiBusy(true); setAiError(''); setSuggestion(null);
    try {
      const result = await api.suggest(selectedId, userId);
      if (requestVersion.current === version) { setSuggestion(result); setDraft(result.draft || ''); }
    } catch (reason) {
      if (requestVersion.current === version) setAiError(reason instanceof Error ? reason.message : 'Không thể tạo gợi ý lúc này.');
    } finally { if (requestVersion.current === version) setAiBusy(false); }
  };

  const decideSuggestion = async (decision: 'accepted' | 'edited' | 'rejected') => {
    if (!suggestion) return;
    const current = suggestion;
    const version = requestVersion.current;
    const finalDecision = decision === 'accepted' && draft !== current.draft ? 'edited' : decision;
    setBusy(true);
    try {
      await api.feedback(current.id, userId, finalDecision, draft);
      await refresh();
      const updated = await api.ticket(current.ticketId, userId);
      if (version === requestVersion.current) {
        setDetail(updated); setSuggestion(null); setDraft('');
      }
      notify(decision === 'rejected' ? 'Đã ghi nhận bỏ gợi ý AI.' : 'Đã lưu phân loại, ưu tiên và phản hồi vào lịch sử ticket.');
    } catch (reason) { notify(reason instanceof Error ? reason.message : 'Không thể lưu quyết định AI.'); }
    finally { setBusy(false); }
  };

  if (accountLink) return <AccountLinkPage purpose={accountLink.purpose} token={accountLink.token}/>;
  if (needsAuth || invitationToken && data) return <AuthPage invitationToken={invitationToken} signedIn={data?.user}/>;
  if (loading && !data) return <div className="boot-screen"><span className="brand-mark">A</span><LoaderCircle size={18} className="spin"/> Đang kết nối workspace…</div>;
  if (error && !data) return <div className="setup-screen"><div className="setup-brand"><span className="brand-mark">A</span><b>Support Ops</b></div><section className="setup-card"><span className="setup-alert"><CircleAlert size={20}/></span><h1>Backend chưa sẵn sàng</h1><p>{error}</p><div className="setup-steps"><b>Kiểm tra cấu hình</b><code>cp .env.example .env</code><code>docker compose up --build</code><small>GEMINI_API_KEY và PostgreSQL + pgvector là bắt buộc.</small></div><Button variant="primary" onClick={() => { setLoading(true); api.bootstrap(userId).then(setData).then(() => setError('')).catch(reason => setError(reason.message)).finally(() => setLoading(false)); }}><ArrowDownUp size={14}/> Thử kết nối lại</Button></section></div>;
  if (!data) return null;

  return <div className="app-shell"><Sidebar data={data} page={page} setPage={setPage} notify={notify}/>
    <main className="main"><header className="topbar"><div className="breadcrumbs"><span>{data.workspace}</span><ChevronRight size={13}/><b>{pages[page]}</b></div><div className="top-actions"><label className="global-search"><Search size={14}/><input aria-label="Tìm kiếm ticket" placeholder="Tìm ticket…" value={ticketSearch} onFocus={() => setPage('inbox')} onChange={event => { setTicketSearch(event.target.value); setPage('inbox'); }}/></label><span className="top-avatar">{data.user.name.split(' ').slice(-2).map(part => part[0]).join('')}</span></div></header>
      {data.subscription.status !== 'active' && <div className={`subscription-banner ${data.subscription.status}`} role="status"><span>{data.subscription.status === 'trialing' ? `Dùng thử miễn phí đến ${billingDate(data.subscription.trialEndsAt)}.` : 'Workspace đã hết hạn. Bạn vẫn có thể xem dữ liệu.'}</span><Button onClick={() => setPage('settings')}>Xem gói & thanh toán</Button></div>}
      {page === 'overview'  && <DashboardPage data={data} openTicket={id => { setSelectedId(id); setPage('inbox'); }} setPage={setPage}/>}
      {page === 'inbox' && <InboxPage data={data} selectedId={selectedId} onSelect={setSelectedId} detail={detail} suggestion={suggestion} loading={busy || aiBusy} aiLoading={aiBusy} aiError={aiError} draft={draft} setDraft={setDraft} onSuggest={createSuggestion} onFeedback={decideSuggestion} onUpdate={updateTicket} user={data.user} notify={notify} search={ticketSearch} setSearch={setTicketSearch} refresh={refresh}/>}
      {page === 'knowledge' && <KnowledgePage data={data} user={data.user} refresh={refresh} notify={notify}/>}
      {page === 'teams' && <TeamsPage key={data.user.id} data={data} user={data.user} refresh={refresh} notify={notify}/>}
      {page === 'reports' && <ReportsPage user={data.user} notify={notify}/>}
      {page === 'audit' && <AuditPage events={data.events}/>}
      {page === 'settings' && <SettingsPage key={data.workspaceId} data={data} refresh={refresh}/>}
      <footer className="app-footer"><span><i className="live-dot"/> {data.workspace} · {subscriptionLabel(data.subscription.status)}</span><span>AI gợi ý · Nhân viên quyết định</span></footer>
    </main>
    {busy && <div className="busy-indicator" aria-live="polite"><LoaderCircle className="spin" size={14}/> Đang xử lý…</div>}
    {toast && <div className="toast" role="status"><span>{toast}</span><button onClick={() => setToast('')} aria-label="Đóng thông báo">×</button></div>}
  </div>;
}

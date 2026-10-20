import { useEffect, useMemo, useState } from 'react';
import { Plus, ArrowDownUp, ArrowRight, FileCheck2, ListFilter, LoaderCircle, CheckCircle2, Search, Send, ShieldAlert, Sparkles, Tag, WandSparkles } from 'lucide-react';
import type { AISuggestion, Bootstrap, Ticket, TicketDetail, User } from '../types';
import { CreateTicketForm } from '../components/CreateTicketForm';
import { Button, EmptyState, Priority, Status } from '../components/ui';

type Props = {
  data: Bootstrap; selectedId: string | null; onSelect: (id: string) => void; detail: TicketDetail | null;
  suggestion: AISuggestion | null; loading: boolean; aiLoading: boolean; aiError: string; draft: string; setDraft: (value: string) => void;
  onSuggest: () => void; onFeedback: (decision: 'accepted' | 'edited' | 'rejected') => void;
  onUpdate: (body: Record<string, unknown>) => Promise<void>; user: User; notify: (message: string) => void;
  refresh: () => Promise<void>; search: string; setSearch: (query: string) => void;
};

const statuses = ['Mới', 'Đang xử lý', 'Chờ khách', 'Chờ xử lý', 'Đã giải quyết'];
const priorities = ['Khẩn cấp', 'Cao', 'Bình thường', 'Thấp'];

export function InboxPage({ data, selectedId, onSelect, detail, suggestion, loading, aiLoading, aiError, draft, setDraft, onSuggest, onFeedback, onUpdate, user, notify, search, setSearch, refresh }: Props) {
  const [creating, setCreating] = useState(false);
  const [scope, setScope] = useState('all');
  const [status, setStatus] = useState('');
  const [team, setTeam] = useState('');
  const [priority, setPriority] = useState('');
  const [topic, setTopic] = useState('');
  const [assignee, setAssignee] = useState('');
  const [period, setPeriod] = useState('all');
  const [note, setNote] = useState('');
  useEffect(() => { setNote(''); }, [selectedId]);
  const active = detail?.ticket || data.tickets.find(ticket => ticket.id === selectedId) || null;

  const tickets = useMemo(() => {
    const cutoff = period === '7d' ? Date.now() - 7 * 86400000 : period === '30d' ? Date.now() - 30 * 86400000 : 0;
    return data.tickets.filter(ticket => {
      const searchMatch = `${ticket.code} ${ticket.subject} ${ticket.customer} ${ticket.topic}`.toLocaleLowerCase().includes(search.toLocaleLowerCase());
      return searchMatch && (!status || ticket.status === status) && (!team || ticket.teamId === team) &&
        (!priority || ticket.priority === priority) && (!topic || ticket.topic === topic) &&
        (!assignee || ticket.assigneeId === assignee) && (!cutoff || new Date(ticket.updatedAt).getTime() >= cutoff) &&
        (scope === 'all' || scope === 'mine' && ticket.assigneeId === user.id || scope === 'team' && ticket.teamId === user.teamId);
    });
  }, [data.tickets, search, status, team, priority, topic, assignee, period, scope, user.id, user.teamId]);

  return <section className="inbox-page">
    <div className="page-heading inbox-heading"><div><h1>Hộp thư</h1><p>Ticket chỉ hiển thị trong phạm vi bạn được phép xem.</p></div><div className="inbox-heading-meta"><Button variant="primary" disabled={!data.teams.length} onClick={() => setCreating(true)}><Plus size={15}/> Tạo ticket</Button></div></div>
    {creating && <CreateTicketForm data={data} onClose={() => setCreating(false)} onCreated={async ticket => { await refresh(); onSelect(ticket.id); notify('Đã tạo ticket.'); }}/>}
    <div className="inbox-workspace">
      <section className="ticket-column" aria-label="Danh sách ticket">
        <div className="inbox-tabs"><button className={scope === 'all' ? 'selected' : ''} onClick={() => setScope('all')}>Được phép xem</button><button className={scope === 'team' ? 'selected' : ''} onClick={() => setScope('team')}>Nhóm của tôi</button><button className={scope === 'mine' ? 'selected' : ''} onClick={() => setScope('mine')}>Tôi phụ trách</button></div>
        <label className="list-search"><Search size={14}/><input aria-label="Tìm ticket" placeholder="Tìm ticket, khách hàng…" value={search} onChange={event => setSearch(event.target.value)}/></label>
        <div className="ticket-filters">
          <select aria-label="Lọc trạng thái" value={status} onChange={event => setStatus(event.target.value)}><option value="">Mọi trạng thái</option>{statuses.map(value => <option key={value}>{value}</option>)}</select>
          <select aria-label="Lọc nhóm" value={team} onChange={event => setTeam(event.target.value)}><option value="">Mọi nhóm</option>{data.teams.map(value => <option value={value.id} key={value.id}>{value.name}</option>)}</select>
          <select aria-label="Lọc ưu tiên" value={priority} onChange={event => setPriority(event.target.value)}><option value="">Mọi ưu tiên</option>{priorities.map(value => <option key={value}>{value}</option>)}</select>
          <select aria-label="Lọc chủ đề" value={topic} onChange={event => setTopic(event.target.value)}><option value="">Mọi chủ đề</option>{[...new Set(data.tickets.map(ticket => ticket.topic))].map(value => <option key={value}>{value}</option>)}</select>
          <select aria-label="Lọc người phụ trách" value={assignee} onChange={event => setAssignee(event.target.value)}><option value="">Mọi người phụ trách</option>{data.users.map(value => <option value={value.id} key={value.id}>{value.name}</option>)}</select>
          <select aria-label="Lọc thời gian" value={period} onChange={event => setPeriod(event.target.value)}><option value="all">Mọi thời gian</option><option value="7d">7 ngày gần nhất</option><option value="30d">30 ngày gần nhất</option></select>
        </div>
        <div className="list-toolbar"><span>{tickets.length} ticket</span><span><ArrowDownUp size={13}/> Mới cập nhật</span></div>
        <div className="ticket-list">{tickets.map(ticket => <TicketRow key={ticket.id} ticket={ticket} selected={selectedId === ticket.id} onClick={() => onSelect(ticket.id)}/>)}{tickets.length === 0 && <EmptyState title="Không có ticket phù hợp" detail="Đổi từ khóa hoặc xóa bớt bộ lọc." action={<button className="text-link" onClick={() => { setSearch(''); setStatus(''); setTeam(''); setPriority(''); setTopic(''); setAssignee(''); setPeriod('all'); setScope('all'); }}>Xóa bộ lọc</button>}/>}</div>
      </section>

      {active ? <>
        <section className="ticket-detail" aria-label="Chi tiết ticket">
          <div className="detail-toolbar"><div><b>{active.code}</b><span>·</span><span>{active.channel}</span></div><Button disabled={loading || active.status === 'Đã giải quyết'} onClick={() => void onUpdate({ status: 'Đã giải quyết' }).catch(() => {})}><CheckCircle2 size={15}/> Giải quyết</Button></div>
          <div className="detail-scroll">
            <header className="detail-title"><div className="detail-tags"><Status value={active.status}/><Priority value={active.priority}/></div><h2>{active.subject}</h2>
              <div className="customer-line"><span className="customer-avatar">{initials(active.customer)}</span><span><b>{active.customer}</b><small>{active.customerEmail} · nhận qua {active.channel}</small></span><time>{new Date(active.createdAt).toLocaleDateString('vi-VN', { day: '2-digit', month: 'short' })}</time></div>
            </header>
            <div className="conversation"><div className="conversation-date">TRAO ĐỔI VỚI KHÁCH HÀNG</div><MessageCard author={active.customer} body={active.body} time={active.createdAt}/>
              {detail?.messages.filter(message => message.internal || message.author !== active.customer).map((message, index) => <MessageCard key={`${message.createdAt}-${index}`} author={message.internal ? 'Ghi chú nội bộ' : message.author} body={message.body} time={message.createdAt} internal={message.internal}/>)}
            </div>
            <section className="ai-panel"><div className="ai-heading"><span className="ai-icon"><Sparkles size={15}/></span><span><b>Gợi ý từ AI</b><small>Kiểm tra căn cứ trước khi dùng</small></span><Button variant="subtle" loading={loading} onClick={onSuggest}><WandSparkles size={14}/>{suggestion ? 'Phân tích lại' : 'Phân tích'}</Button></div>
              {!suggestion && !aiLoading && !aiError && <div className="ai-empty"><p>AI sẽ phân loại ticket, tìm kiến thức đã duyệt và đề xuất câu trả lời có nguồn.</p><button className="text-link" onClick={onSuggest}>Bắt đầu <ArrowRight size={13}/></button></div>}
              {aiError && <div className="ai-error" role="alert"><ShieldAlert size={18}/><div><b>Chưa thể tạo gợi ý</b><p>{aiError}</p><Button onClick={onSuggest} disabled={loading}>Thử lại</Button></div></div>}
              {aiLoading && <div className="ai-loading"><LoaderCircle className="spin" size={16}/> Đang tìm căn cứ và phân tích ticket…</div>}
              {suggestion && <div className="ai-result">
                {!suggestion.grounded ? <div className="handoff-box"><div><ShieldAlert size={16}/><b>Chuyển người phụ trách</b></div><p>{suggestion.handoffReason || 'Chưa tìm thấy đủ căn cứ trong kiến thức được duyệt.'}</p><small>AI không tạo bản nháp khi chưa có nguồn phù hợp.</small><button className="text-button" disabled={loading} onClick={() => onFeedback('rejected')}>Bỏ gợi ý</button></div> : <>
                  <div className="ai-classification"><span><small>CHỦ ĐỀ</small><b>{suggestion.topic}</b></span><span><small>ƯU TIÊN</small><Priority value={suggestion.priority}/></span><span><small>NHÓM ĐỀ XUẤT</small><b>{data.teams.find(value => value.id === suggestion.suggestedTeamId)?.name || 'Chưa xác định'}</b></span></div>
                  <p className="ai-reason">{suggestion.reason}</p><label className="reply-label">Bản nháp trả lời <span>Chưa gửi</span></label><textarea maxLength={8000} value={draft} onChange={event => setDraft(event.target.value)} rows={4} aria-label="Chỉnh sửa bản nháp trả lời"/>
                  <div className="citations"><strong><FileCheck2 size={14}/> Căn cứ đã duyệt</strong>{suggestion.citations.map(citation => <button key={`${citation.id}-${citation.chunkId}`} onClick={() => notify(`${citation.title}: ${citation.excerpt}`)}>{citation.title} <ArrowRight size={12}/></button>)}</div>
                  <div className="ai-actions"><button className="text-button" disabled={loading} onClick={() => onFeedback('rejected')}>Bỏ gợi ý</button><Button variant="quiet" disabled={loading || !draft.trim()} onClick={() => onFeedback('edited')}>Sửa & lưu phản hồi</Button><Button variant="primary" disabled={loading || !draft.trim()} onClick={() => onFeedback('accepted')}><Send size={13}/> Chấp nhận & lưu</Button></div>
                </>}
              </div>}
            </section>
          </div>
          <div className="reply-composer"><div className="composer-tabs"><b>Trả lời khách</b><span>Chỉ lưu sau xác nhận của bạn</span></div><textarea maxLength={8000} aria-label="Phản hồi khách hàng" value={draft} onChange={event => setDraft(event.target.value)} placeholder="Viết phản hồi…" rows={2}/><div className="composer-foot"><button className="text-button" onClick={() => document.getElementById('internal-note')?.focus()}>Thêm ghi chú nội bộ</button><Button variant="primary" disabled={loading || !draft.trim()} onClick={() => void onUpdate({ reply: draft }).catch(() => {})}><Send size={13}/> Lưu phản hồi</Button></div><div className="note-row"><input aria-label="Ghi chú nội bộ" id="internal-note" maxLength={4000} value={note} onChange={event => setNote(event.target.value)} placeholder="Ghi chú chỉ dành cho nhóm…"/><button disabled={loading || !note.trim()} onClick={async () => { try { await onUpdate({ note }); setNote(''); } catch { /* Keep the note for retry. */ } }}>Lưu ghi chú</button></div></div>
        </section>
        <aside className="ticket-sidebar"><section className="property-section"><h3>Thông tin ticket</h3><Property label="Trạng thái"><select aria-label="Trạng thái ticket" disabled={loading} value={active.status} onChange={event => void onUpdate({ status: event.target.value }).catch(() => {})}>{statuses.map(value => <option key={value}>{value}</option>)}</select></Property><Property label="Mức ưu tiên"><select aria-label="Mức ưu tiên ticket" disabled={loading} value={active.priority} onChange={event => void onUpdate({ priority: event.target.value }).catch(() => {})}>{priorities.map(value => <option key={value}>{value}</option>)}</select></Property><Property label="Chủ đề"><span className="property-value"><Tag size={13}/>{active.topic}</span></Property>
          <Property label="Nhóm hỗ trợ"><select aria-label="Nhóm hỗ trợ ticket" value={active.teamId} disabled={loading || user.role === 'agent'} onChange={event => void onUpdate({ team_id: event.target.value, assignee_id: null }).catch(() => {})}>{data.teams.filter(value => user.role === 'admin' || value.id === user.teamId).map(value => <option value={value.id} key={value.id}>{value.name}</option>)}</select></Property>
          <Property label="Người phụ trách"><select aria-label="Người phụ trách ticket" value={active.assigneeId || ''} disabled={loading || user.role === 'agent'} onChange={event => void onUpdate({ assignee_id: event.target.value || null }).catch(() => {})}><option value="">Chưa phân công</option>{data.users.filter(value => value.teamId === active.teamId).map(value => <option value={value.id} key={value.id}>{value.name}</option>)}</select></Property>
        </section><section className="property-section"><h3>Khách hàng</h3><div className="customer-card"><span className="customer-avatar">{initials(active.customer)}</span><span><b>{active.customer}</b><small>{active.customerEmail}</small></span></div><p className="demo-field-note">Thông tin được ghi nhận từ yêu cầu hỗ trợ của khách hàng.</p></section><section className="property-section"><h3>Thông tin khác</h3><Property label="Kênh"><span className="property-value">{active.channel}</span></Property><Property label="Mã ticket"><code>{active.code}</code></Property><Property label="Cập nhật"><span className="property-value">{new Date(active.updatedAt).toLocaleString('vi-VN')}</span></Property></section></aside>
      </> : <div className="ticket-detail detail-empty"><EmptyState title="Chọn một ticket" detail="Chọn ticket trong danh sách để xem lịch sử và xử lý."/></div>}
    </div>
  </section>;
}

function TicketRow({ ticket, selected, onClick }: { ticket: Ticket; selected: boolean; onClick: () => void }) {
  return <button className={`ticket-item ${selected ? 'selected' : ''}`} onClick={onClick}>
    <span className="ticket-item-top"><span className={`priority-dot ${ticket.priority === 'Khẩn cấp' ? 'urgent' : ticket.priority === 'Cao' ? 'high' : ''}`}/><b>{ticket.customer}</b><time>{new Date(ticket.updatedAt).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</time></span>
    <strong>{ticket.subject}</strong><p>{ticket.body}</p><span className="ticket-item-meta"><Status value={ticket.status}/><small className={`topic-label ${ticket.teamColor}`}>{ticket.topic}</small><small>{ticket.code}</small></span>
  </button>;
}

function MessageCard({ author, body, time, internal = false }: { author: string; body: string; time: string; internal?: boolean }) {
  return <article className={`message ${internal ? 'internal-message' : 'customer-message'}`}><header><b>{author}</b><time>{new Date(time).toLocaleString('vi-VN')}</time></header><p>{body}</p></article>;
}

function Property({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="property"><span>{label}</span>{children}</div>;
}

function initials(name: string) { return name.split(' ').slice(-2).map(part => part[0]).join('').toUpperCase(); }

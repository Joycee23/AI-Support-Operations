import { ArrowRight, ArrowUpRight, BookOpen, Clock3, Inbox, ShieldCheck, Users } from 'lucide-react';
import type { Bootstrap, Page } from '../types';
import { Metric, Priority, Status } from '../components/ui';

export function DashboardPage({ data, openTicket, setPage }: { data: Bootstrap; openTicket: (id: string) => void; setPage: (page: Page) => void }) {
  const open = data.tickets.filter(ticket => ticket.status !== 'Đã giải quyết');
  const escalated = data.tickets.filter(ticket => ['Cao', 'Khẩn cấp'].includes(ticket.priority));
  const pending = data.knowledge.filter(item => item.status === 'pending');
  return <section className="page-content">
    <div className="page-heading"><div><h1>Tổng quan</h1><p>Hàng đợi và công việc đang cần nhóm hỗ trợ xử lý.</p></div><button className="button button-quiet" onClick={() => setPage('inbox')}><Inbox size={15}/> Mở hộp thư</button></div>
    <div className="metric-grid">
      <Metric label="Tổng ticket" value={data.tickets.length} note="Trong phạm vi được cấp quyền" icon={Inbox} tone="blue"/>
      <Metric label="Đang mở" value={open.length} note="Chưa giải quyết hoặc chờ khách" icon={Clock3} tone="amber"/>
      <Metric label="Ưu tiên cao" value={escalated.length} note="Cao và khẩn cấp" icon={ArrowUpRight} tone="red"/>
      <Metric label="Chờ duyệt kiến thức" value={pending.length} note="Cần người có quyền xem lại" icon={BookOpen} tone="green"/>
    </div>
    <div className="dashboard-grid">
      <section className="panel queue-panel"><div className="panel-heading"><div><h2>Ticket cần chú ý</h2><p>Ưu tiên cao trước, sau đó theo thời gian cập nhật</p></div><button className="text-link" onClick={() => setPage('inbox')}>Tất cả ticket <ArrowRight size={13}/></button></div>
        <div className="queue-list">{[...open].sort((a, b) => ['Khẩn cấp', 'Cao', 'Bình thường', 'Thấp'].indexOf(a.priority) - ['Khẩn cấp', 'Cao', 'Bình thường', 'Thấp'].indexOf(b.priority) || new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()).slice(0, 6).map(ticket => <button key={ticket.id} className="queue-row" onClick={() => openTicket(ticket.id)}>
          <span className={`priority-dot ${ticket.priority === 'Khẩn cấp' ? 'urgent' : ticket.priority === 'Cao' ? 'high' : ''}`}/><span className="queue-main"><b>{ticket.subject}</b><small>{ticket.customer} · {ticket.code}</small></span><span className="queue-team">{ticket.team}</span><Priority value={ticket.priority}/><Status value={ticket.status}/><ArrowRight size={14}/>
        </button>)}{open.length === 0 && <div className="inline-empty">Không có ticket đang mở trong phạm vi này.</div>}</div>
      </section>
      <section className="panel side-panel"><div className="panel-heading"><div><h2>Hàng đợi theo nhóm</h2><p>Ticket được phép xem</p></div><Users size={16}/></div><div className="team-list">{data.teams.map(team => <div className="team-row" key={team.id}><i className={`team-swatch ${team.color}`}/><span>{team.name}</span><b>{team.count || 0}</b></div>)}</div><button className="panel-footer-link" onClick={() => setPage('teams')}>Nhóm & thành viên <ArrowRight size={13}/></button></section>
      <section className="panel activity-panel"><div className="panel-heading"><div><h2>Hoạt động gần đây</h2><p>Thay đổi trong workspace</p></div><button className="text-link" onClick={() => setPage('audit')}>Nhật ký <ArrowRight size={13}/></button></div><div className="activity-list">{data.events.slice(0, 5).map(event => <div className="activity-row" key={event.id}><span className="activity-avatar">{event.actor.split(' ').slice(-2).map(part => part[0]).join('')}</span><span className="activity-copy"><b>{event.actor}</b><small>{event.detail}{event.ticketCode ? ` · ${event.ticketCode}` : ''}</small></span><time>{new Date(event.createdAt).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</time></div>)}</div></section>
      <section className="panel knowledge-summary"><div className="panel-heading"><div><h2>Căn cứ trả lời</h2><p>Tài liệu có thể truy xuất</p></div><ShieldCheck size={17}/></div><div className="knowledge-total"><strong>{data.knowledge.filter(item => item.status === 'approved' && item.processingStatus === 'ready').length}</strong><span>đã duyệt<br/>và sẵn sàng</span></div><p className="summary-note">Tài liệu mới phải được xử lý và duyệt trước khi AI dùng làm nguồn.</p><button className="panel-footer-link" onClick={() => setPage('knowledge')}>Mở kho kiến thức <ArrowRight size={13}/></button></section>
    </div>
  </section>;
}

import { BrandMark } from './BrandMark';
import { subscriptionLabel } from './BillingSection';
import { Activity, BookOpen, ChevronRight, Clock3, LogOut, LayoutDashboard, LifeBuoy, Settings2, Users } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap, Page } from '../types';

const navigation = [
  { id: 'overview', title: 'Tổng quan', icon: LayoutDashboard },
  { id: 'inbox', title: 'Hộp thư', icon: LifeBuoy },
  { id: 'knowledge', title: 'Kho kiến thức', icon: BookOpen },
  { id: 'teams', title: 'Nhóm & thành viên', icon: Users },
  { id: 'reports', title: 'Chất lượng AI', icon: Activity },
  { id: 'audit', title: 'Nhật ký hoạt động', icon: Clock3 },
  { id: 'settings', title: 'Cấu hình', icon: Settings2 },
] as const;

export function Sidebar({ data, page, setPage, notify }: {
  data: Bootstrap; page: Page; setPage: (page: Page) => void; notify: (message: string) => void;
}) {
  const role = data.user.role === 'admin' ? 'Quản trị viên' : data.user.role === 'manager' ? 'Quản lý nhóm' : 'Nhân viên hỗ trợ';
  const pending = data.knowledge.filter(item => item.status === 'pending').length;
  return <aside className="sidebar">
    <div className="brand" role="img" aria-label="Support Ops — Support Operations"><BrandMark/><span className="brand-copy"><b>Support Ops</b><small>SUPPORT OPERATIONS</small></span></div>
    <div className="workspace-switch"><span className="workspace-logo">{data.workspace[0]}</span><span><b>{data.workspace}</b><small>{subscriptionLabel(data.subscription.status)}</small></span><select aria-label="Chuyển workspace" value={data.user.id} onChange={async event => { try { await api.switchWorkspace(event.target.value); window.location.reload(); } catch (reason) { notify(reason instanceof Error ? reason.message : 'Không thể chuyển workspace.'); } }}>{data.memberships.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
    
    <nav className="navigation">{navigation.map(item => {
      const Icon = item.icon; const id = item.id as Page;
      const count = id === 'inbox' ? data.tickets.filter(ticket => ticket.status === 'Mới').length : id === 'knowledge' ? pending : 0;
      return <button key={item.id} aria-label={item.title} title={item.title} aria-current={page === id ? 'page' : undefined} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => setPage(id)}>
        <Icon size={16}/><span>{item.title}</span>{count > 0 && <em>{count}</em>}
      </button>;
    })}</nav>
    <div className="sidebar-bottom">
      <div className="help-card"><div className="help-heading"><LifeBuoy size={15}/><b>Quy trình hỗ trợ</b></div><p>Kiểm tra nguồn AI trước khi xác nhận phản hồi.</p><button onClick={() => setPage('settings')}>Xem hướng dẫn <ChevronRight size={13}/></button></div>
      <div className="profile"><span className="avatar">{data.user.name.split(' ').slice(-2).map(part => part[0]).join('')}</span><span className="profile-copy"><b>{data.user.name}</b><small>{role}</small></span>
        <button className="icon-btn signout-button" aria-label="Đăng xuất" title="Đăng xuất" onClick={async () => { try { await api.logout(); window.location.reload(); } catch (reason) { notify(reason instanceof Error ? reason.message : 'Không thể đăng xuất.'); } }}><LogOut size={17}/></button>
      </div>
    </div>
  </aside>;
}

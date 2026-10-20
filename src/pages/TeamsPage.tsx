import { useEffect, useState } from 'react';
import { ArrowRight, Check, Copy, MailPlus, Plus, Users, X } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap, User } from '../types';
import { Button, EmptyState } from '../components/ui';

type FormKind = 'workspace' | 'team' | 'member';
type Invitation = { id: string; email: string; role: string; teamId: string; expiresAt: string; emailDelivery: { status: string; message: string } };

export function TeamsPage({ data, user, refresh, notify }: {
  data: Bootstrap; user: User; refresh: () => Promise<void>; notify: (message: string) => void;
}) {
  const [form, setForm] = useState<FormKind | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [teamId, setTeamId] = useState(user.teamId || data.teams[0]?.id || '');
  const [role, setRole] = useState<'agent' | 'manager'>('agent');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [inviteLink, setInviteLink] = useState('');
  const [emailDelivery, setEmailDelivery] = useState<{ status: string; message: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const isAdmin = user.role === 'admin';
  const canInvite = isAdmin || user.role === 'manager';

  useEffect(() => {
    if (!canInvite) return;
    let cancelled = false;
    api.invitations().then(value => { if (!cancelled) setInvitations(value); }).catch(reason => { if (!cancelled) notify(reason.message); });
    return () => { cancelled = true; };
  }, [user.id, canInvite, notify]);

  const openForm = (kind: FormKind) => { setForm(kind); setError(''); setName(''); setEmail(''); };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true); setError('');
    try {
      if (form === 'workspace') {
        await api.createWorkspace(user.id, name.trim());
        window.location.reload();
        return;
      }
      if (form === 'team') { await api.createTeam(user.id, name.trim(), 'blue'); await refresh(); notify('Đã tạo nhóm hỗ trợ.'); }
      else {
        const result = await api.inviteMember({ email: email.trim(), role: isAdmin ? role : 'agent', team_id: user.role === 'manager' ? user.teamId! : teamId });
        setInviteLink(result.url || `${window.location.origin}/#invite=${encodeURIComponent(result.token)}`);
        setEmailDelivery(result.emailDelivery);
        setCopied(false);
        try { setInvitations(await api.invitations()); } catch { notify('Lời mời đã tạo nhưng chưa tải lại được danh sách. Hãy giữ link bên dưới.'); }
      }
      setForm(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể lưu thay đổi.'); }
    finally { setSaving(false); }
  };

  return <section className="page-content">
    <div className="page-heading"><div><h1>Nhóm & thành viên</h1><p>Quản lý nhóm và lời mời trong {data.workspace}.</p></div><div className="heading-actions"><Button onClick={() => openForm('workspace')}><Plus size={15}/> Workspace mới</Button>{isAdmin && <Button onClick={() => openForm('team')}><Plus size={15}/> Tạo nhóm</Button>}{canInvite && <Button variant="primary" disabled={!data.teams.length} onClick={() => openForm('member')}><MailPlus size={16}/> Mời thành viên</Button>}</div></div>
    {form && <section className="panel workspace-form"><header className="panel-heading"><div><h2>{form === 'workspace' ? 'Tạo workspace riêng' : form === 'team' ? 'Tạo nhóm hỗ trợ' : 'Mời thành viên'}</h2><p>{form === 'member' ? 'Gửi lời mời qua email, đồng thời giữ link để bạn sao chép. Lời mời có hiệu lực 7 ngày.' : form === 'workspace' ? 'Bạn sẽ là quản trị viên của workspace mới, với dữ liệu độc lập.' : 'Phân chia công việc hỗ trợ theo nhóm của bạn.'}</p></div><button className="icon-btn" onClick={() => setForm(null)} aria-label="Đóng biểu mẫu"><X size={18}/></button></header>
      <form onSubmit={event => void submit(event)}><div className="workspace-form-fields">
        {form !== 'member' ? <label className="form-field">{form === 'team' ? 'Tên nhóm' : 'Tên doanh nghiệp / cửa hàng'}<input autoFocus value={name} onChange={event => setName(event.target.value)} minLength={2} maxLength={form === 'team' ? 120 : 180} required/></label> : <><label className="form-field">Email thành viên<input type="email" autoFocus value={email} onChange={event => setEmail(event.target.value)} placeholder="dongnghiep@congty.vn" maxLength={200} required/></label><label className="form-field">Nhóm hỗ trợ<select value={teamId} onChange={event => setTeamId(event.target.value)} required>{data.teams.filter(team => isAdmin || team.id === user.teamId).map(team => <option key={team.id} value={team.id}>{team.name}</option>)}</select></label>{isAdmin && <label className="form-field">Vai trò<select value={role} onChange={event => setRole(event.target.value as 'agent' | 'manager')}><option value="agent">Nhân viên hỗ trợ</option><option value="manager">Quản lý nhóm</option></select></label>}</>}
      </div>{error && <p className="auth-error" role="alert">{error}</p>}<div className="workspace-form-actions"><Button type="button" onClick={() => setForm(null)}>Hủy</Button><Button type="submit" variant="primary" loading={saving}>{form === 'member' ? 'Gửi lời mời' : 'Tạo'}</Button></div></form>
    </section>}
    {inviteLink && <section className="invite-share" aria-live="polite"><div><MailPlus size={20}/><span><b>{emailDelivery?.status === 'sent' ? 'Đã gửi lời mời tới máy chủ email' : 'Đã tạo lời mời, email chưa được xác nhận'}</b><small>{emailDelivery?.message} Link bên dưới vẫn có thể sao chép để gửi trực tiếp.</small></span><button className="icon-btn" onClick={() => setInviteLink('')} aria-label="Ẩn link lời mời"><X size={18}/></button></div><label className="form-field">Link lời mời<input readOnly value={inviteLink} onFocus={event => event.target.select()}/></label><Button onClick={async () => { try { await navigator.clipboard.writeText(inviteLink); setCopied(true); } catch { notify('Chọn link và sao chép thủ công.'); } }}>{copied ? <Check size={15}/> : <Copy size={15}/>} {copied ? 'Đã sao chép' : 'Sao chép link'}</Button></section>}
    <div className="team-grid">{data.teams.map(team => <article className="team-card" key={team.id}><header className="team-card-head"><i className={`team-swatch ${team.color}`}/><span><b>{team.name}</b><small>{data.users.filter(person => person.teamId === team.id).length} thành viên · {team.count || 0} ticket</small></span><Users size={18}/></header><div className="team-members">{data.users.filter(person => person.teamId === team.id).map(person => <div className="member-row" key={person.id}><span className="avatar">{person.name.split(' ').slice(-2).map(part => part[0]).join('')}</span><span><b>{person.name}</b><small>{person.email}</small></span><em>{person.role === 'admin' ? 'Quản trị viên' : person.role === 'manager' ? 'Quản lý' : 'Nhân viên'}</em></div>)}{!data.users.some(person => person.teamId === team.id) && <p className="team-empty">Chưa có thành viên trong phạm vi bạn được xem.</p>}</div></article>)}</div>
    {canInvite && <section className="panel pending-invitations"><header className="panel-heading"><div><h2>Lời mời đang chờ</h2><p>Chỉ người dùng đúng email mới có thể nhận lời mời.</p></div><MailPlus size={18}/></header>{invitations.length ? invitations.map(item => <div className="invitation-row" key={item.id}><span><b>{item.email}</b><small>{data.teams.find(team => team.id === item.teamId)?.name} · {item.role === 'manager' ? 'Quản lý' : 'Nhân viên'} · {new Date(item.expiresAt).getTime() < Date.now() ? 'Đã hết hạn' : `Hết hạn ${new Date(item.expiresAt).toLocaleDateString('vi-VN')}`}</small><small>{item.emailDelivery.message}</small></span><Button disabled={saving} onClick={async () => { setSaving(true); try { await api.revokeInvitation(item.id); setInvitations(await api.invitations()); notify('Đã thu hồi lời mời.'); } catch (reason) { notify(reason instanceof Error ? reason.message : 'Không thể thu hồi.'); } finally { setSaving(false); } }}>Thu hồi</Button></div>) : <EmptyState title="Chưa có lời mời" detail="Mời đồng nghiệp vào nhóm để cùng xử lý ticket."/>}</section>}
    <p className="workspace-security-note"><ArrowRight size={14}/> Thành viên chỉ xem dữ liệu theo quyền trong workspace đang chọn.</p>
  </section>;
}

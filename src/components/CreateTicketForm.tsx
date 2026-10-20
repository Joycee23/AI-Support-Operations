import { useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap, Ticket } from '../types';
import { Button } from './ui';

export function CreateTicketForm({ data, onCreated, onClose }: { data: Bootstrap; onCreated: (ticket: Ticket) => Promise<void>; onClose: () => void }) {
  const [values, setValues] = useState({ customer_name: '', customer_email: '', subject: '', body: '', team_id: data.user.teamId || data.teams[0]?.id || '', channel: 'Email' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const update = (key: keyof typeof values, value: string) => setValues(current => ({ ...current, [key]: value }));
  return <section className="panel workspace-form"><header className="panel-heading"><div><h2>Tạo ticket hỗ trợ</h2><p>Ghi nhận yêu cầu của khách hàng trong workspace hiện tại.</p></div><button className="icon-btn" aria-label="Đóng biểu mẫu ticket" onClick={onClose}><X size={18}/></button></header><form onSubmit={async event => { event.preventDefault(); setSaving(true); setError(''); try { const ticket = await api.createTicket(values); await onCreated(ticket); onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể tạo ticket.'); } finally { setSaving(false); } }}>
    <div className="workspace-form-fields"><label className="form-field">Tên khách hàng<input required minLength={2} maxLength={120} autoFocus value={values.customer_name} onChange={event => update('customer_name', event.target.value)}/></label><label className="form-field">Email khách hàng<input required type="email" maxLength={200} value={values.customer_email} onChange={event => update('customer_email', event.target.value)}/></label><label className="form-field">Nhóm xử lý<select required value={values.team_id} onChange={event => update('team_id', event.target.value)}>{data.teams.filter(team => data.user.role === 'admin' || team.id === data.user.teamId).map(team => <option value={team.id} key={team.id}>{team.name}</option>)}</select></label><label className="form-field">Kênh tiếp nhận<select value={values.channel} onChange={event => update('channel', event.target.value)}>{['Email', 'Chat', 'Điện thoại', 'Khác'].map(channel => <option key={channel}>{channel}</option>)}</select></label></div>
    <label className="form-field">Tiêu đề<input required minLength={3} maxLength={300} value={values.subject} onChange={event => update('subject', event.target.value)}/></label><label className="form-field">Nội dung yêu cầu<textarea required minLength={3} maxLength={8000} rows={4} value={values.body} onChange={event => update('body', event.target.value)}/></label>{error && <div className="auth-error" role="alert">{error}</div>}<div className="workspace-form-actions"><Button type="button" onClick={onClose}>Hủy</Button><Button type="submit" variant="primary" loading={saving}>Tạo ticket</Button></div>
  </form></section>;
}

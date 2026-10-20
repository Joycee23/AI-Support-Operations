import { useState } from 'react';
import { Building2, FileCheck2, LockKeyhole, Sparkles } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap } from '../types';
import { BillingSection, subscriptionLabel } from '../components/BillingSection';
import { Button } from '../components/ui';
import { AccountSecurity } from '../components/AccountSecurity';

export function SettingsPage({ data, refresh }: { data: Bootstrap; refresh: () => Promise<void> }) {
  const [name, setName] = useState(data.workspace);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  return <section className="page-content"><div className="page-heading"><div><h1>Cấu hình workspace</h1><p>Thông tin và cách vận hành không gian của doanh nghiệp.</p></div></div><div className="workspace-settings">
    <BillingSection data={data} refresh={refresh}/>
    <AccountSecurity/>
    <section className="panel workspace-form"><header className="panel-heading"><div><h2>Doanh nghiệp của bạn</h2><p>{subscriptionLabel(data.subscription.status)} · {data.workspace}</p></div><Building2 size={20}/></header><form onSubmit={async event => { event.preventDefault(); setSaving(true); setMessage(''); setError(''); try { await api.renameWorkspace(data.user.id, name.trim()); await refresh(); setMessage('Đã lưu tên doanh nghiệp.'); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể lưu.'); } finally { setSaving(false); } }}><label className="form-field">Tên doanh nghiệp / cửa hàng<input value={name} onChange={event => setName(event.target.value)} required minLength={2} maxLength={180} disabled={data.user.role !== 'admin'}/></label>{data.user.role === 'admin' && <Button type="submit" variant="primary" loading={saving} disabled={name.trim() === data.workspace}>Lưu thay đổi</Button>}{message && <p role="status">{message}</p>}{error && <p className="auth-error" role="alert">{error}</p>}</form></section>
    <section className="panel"><header className="panel-heading"><div><h2>Quyền và tài khoản</h2><p>Đang đăng nhập bằng {data.user.email}</p></div><LockKeyhole size={20}/></header><div className="settings-summary"><p><b>Workspace riêng.</b> Ticket, tài liệu, lời mời và lịch sử hoạt động được giới hạn trong workspace đang chọn.</p><p><b>Phân quyền theo công việc.</b> Quản trị viên quản lý doanh nghiệp; quản lý điều phối nhóm; nhân viên xử lý ticket được phép xem.</p><p><b>Mời đồng nghiệp.</b> Gửi lời mời qua email trong Nhóm & thành viên, hoặc sao chép link để chia sẻ. Người nhận dùng đúng email được mời.</p></div></section>
    <section className="panel integration-section"><header className="panel-heading"><div><h2>AI và căn cứ trả lời</h2><p>AI gợi ý, nhân viên xác nhận</p></div><Sparkles size={20}/></header><div className="settings-summary"><p>AI chỉ truy xuất tài liệu đã được duyệt trong phạm vi của bạn. Khi model quá tải, hệ thống tự thử các model dự phòng đã cấu hình.</p><p><FileCheck2 size={14}/> Phản hồi được lưu trong lịch sử ticket. Ứng dụng chưa kết nối gửi email hoặc tin nhắn tới khách hàng.</p></div></section>
  </div></section>;
}

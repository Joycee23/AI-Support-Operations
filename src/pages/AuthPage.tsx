import { BrandMark } from '../components/BrandMark';
import { useEffect, useState } from 'react';
import { ArrowRight, Building2, LockKeyhole, LogOut, Mail, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import type { User } from '../types';
import { Button } from '../components/ui';

type InvitationInfo = { workspace: string; email: string; role: string; expiresAt: string };

export function AuthPage({ invitationToken, signedIn }: { invitationToken: string | null; signedIn?: User }) {
  const [mode, setMode] = useState<'login' | 'register'>(() => new URLSearchParams(window.location.hash.slice(1)).has('login') ? 'login' : 'register');
  const [name, setName] = useState('');
  const [company, setCompany] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [recoveryEmail, setRecoveryEmail] = useState('');
  const [recoveryMessage, setRecoveryMessage] = useState('');
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [invitation, setInvitation] = useState<InvitationInfo | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(!!invitationToken);

  useEffect(() => {
    if (!invitationToken) return;
    let cancelled = false;
    api.previewInvitation(invitationToken).then(value => {
      if (!cancelled) { setInvitation(value); setEmail(value.email); }
    }).catch(reason => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, [invitationToken]);

  const enterWorkspace = () => { window.history.replaceState(null, '', window.location.pathname); window.location.reload(); };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true); setError('');
    try {
      if (signedIn && invitationToken) await api.acceptInvitation(invitationToken);
      else if (mode === 'register') await api.register({ name, email, password, workspace_name: company, invitation_token: invitationToken });
      else {
        await api.login(email, password, code);
        if (invitationToken) await api.acceptInvitation(invitationToken);
      }
      enterWorkspace();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể tiếp tục. Vui lòng thử lại.'); }
    finally { setSaving(false); }
  };

  return <main className="auth-shell">
    <section className="auth-context">
      <a className="auth-brand" href="/"><BrandMark/><b>AI Support Operations</b></a>
      <div className="auth-intro"><h1>Một nơi để nhóm bạn<br/>chăm sóc khách hàng.</h1><p>Tập trung ticket, kiến thức và gợi ý AI trong không gian riêng của doanh nghiệp.</p>
        <div className="auth-principles"><span><Building2 size={20}/><b>Mỗi doanh nghiệp một workspace</b><small>Tự quản lý nhóm, thành viên và tài liệu.</small></span><span><ShieldCheck size={20}/><b>Quyền truy cập theo vai trò</b><small>AI chỉ dùng nguồn được phép trong workspace.</small></span><span><LockKeyhole size={20}/><b>Bạn kiểm soát mọi phản hồi</b><small>Kiểm tra bản nháp và nguồn trước khi xác nhận.</small></span></div>
      </div><p className="auth-context-footer">Dùng thử miễn phí 1 tháng · Không cần thẻ thanh toán</p>
    </section>
    <section className="auth-form-area"><div className="auth-form-wrap">
      <div className="auth-title"><span className="auth-title-icon">{invitationToken ? <Mail size={24}/> : <Building2 size={24}/>}</span><h2>{invitationToken ? 'Tham gia cùng nhóm' : mode === 'register' ? 'Tạo workspace của bạn' : 'Chào mừng bạn trở lại'}</h2><p>{invitation ? `Bạn được mời vào ${invitation.workspace}.` : invitationToken ? checking ? 'Đang kiểm tra lời mời của bạn.' : 'Không thể sử dụng lời mời này. Xem thông báo bên dưới.' : mode === 'register' ? 'Dùng thử 1 tháng, sau đó 499.000đ/doanh nghiệp/tháng. Thanh toán qua SePay, không tự trừ tiền.' : 'Đăng nhập để tiếp tục công việc.'}</p></div>
      {checking ? <p role="status">Đang kiểm tra lời mời…</p> : <>
        {!signedIn && <div className="auth-tabs" role="group" aria-label="Chọn đăng nhập hoặc đăng ký"><button aria-pressed={mode === 'register'} className={mode === 'register' ? 'selected' : ''} onClick={() => { setMode('register'); setError(''); }}>Dùng thử 1 tháng</button><button aria-pressed={mode === 'login'} className={mode === 'login' ? 'selected' : ''} onClick={() => { setMode('login'); setError(''); }}>Đã có tài khoản</button></div>}
        <form onSubmit={event => void submit(event)}>
          {signedIn ? <div className="invitation-identity"><b>{signedIn.name}</b><p>Đang đăng nhập bằng {signedIn.email}</p>{invitation && signedIn.email !== invitation.email && <p>Lời mời dành cho {invitation.email}. Vui lòng đăng xuất và dùng đúng tài khoản.</p>}</div> : <>
            {mode === 'register' && <><label className="form-field">Họ và tên<input autoComplete="name" value={name} onChange={event => setName(event.target.value)} minLength={2} maxLength={120} required/></label>{!invitationToken && <label className="form-field">Tên doanh nghiệp hoặc cửa hàng<input autoComplete="organization" value={company} onChange={event => setCompany(event.target.value)} placeholder="Tên sẽ hiển thị trong workspace" minLength={2} maxLength={180} required/></label>}</>}
            <label className="form-field">Email<input type="email" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} readOnly={!!invitationToken} maxLength={200} required/></label>
            <label className="form-field">Mật khẩu<input type="password" autoComplete={mode === 'register' ? 'new-password' : 'current-password'} value={password} onChange={event => setPassword(event.target.value)} minLength={mode === 'register' ? 12 : 1} maxLength={128} required/>{mode === 'register' && <small>Dùng ít nhất 12 ký tự để bảo vệ tài khoản.</small>}</label>
            {mode === 'login' && <label className="form-field">Mã xác thực hai bước<input autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} maxLength={64}/><small>Để trống nếu chưa bật. Có thể dùng mã khôi phục khi mất ứng dụng xác thực.</small></label>}
          </>}
          {error && <div className="auth-error" role="alert">{error}</div>}
          <Button className="auth-submit" variant="primary" loading={saving} disabled={!!invitationToken && !invitation || !!signedIn && !!invitation && signedIn.email !== invitation.email} type="submit">{invitationToken ? 'Tham gia workspace' : mode === 'register' ? 'Tạo tài khoản & workspace' : 'Đăng nhập'}<ArrowRight size={17}/></Button>
        </form>
        {!signedIn && mode === 'login' && <details className="auth-recovery"><summary>Quên mật khẩu?</summary><form onSubmit={event => { event.preventDefault(); setRecoveryBusy(true); setRecoveryMessage(''); setError(''); void api.forgotPassword(recoveryEmail).then(result => setRecoveryMessage(result.message)).catch(reason => setError(reason.message)).finally(() => setRecoveryBusy(false)); }}>
          <label className="form-field">Email khôi phục<input type="email" autoComplete="email" value={recoveryEmail} onChange={event => setRecoveryEmail(event.target.value)} maxLength={200} required disabled={recoveryBusy}/></label>
          <Button type="submit" loading={recoveryBusy}>Gửi link đặt lại mật khẩu</Button>
          {recoveryMessage && <p role="status">{recoveryMessage}</p>}
        </form></details>}
        {signedIn && <Button className="auth-signout" onClick={async () => { await api.logout(); window.location.reload(); }}><LogOut size={16}/> Đăng xuất</Button>}
        {invitationToken && !invitation && <a className="text-link" href="/">Quay lại trang đăng ký</a>}
      </>}
      <p className="auth-footnote">Tài liệu và ticket được giới hạn theo workspace và quyền của bạn. Lời mời chỉ có thể được chấp nhận bằng đúng email người nhận.</p>
    </div></section>
  </main>;
}

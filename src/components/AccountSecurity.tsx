import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { Button } from './ui';

export function AccountSecurity() {
  const [status, setStatus] = useState<{ mfaEnabled: boolean; recoveryCodesRemaining: number; emailVerified: boolean } | null>(null);
  const [current, setCurrent] = useState('');
  const [mfaPassword, setMfaPassword] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [code, setCode] = useState('');
  const [secret, setSecret] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [savedCodes, setSavedCodes] = useState(false);
  const [logoutConfirmed, setLogoutConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => {
    let cancelled = false;
    api.accountSecurity().then(value => { if (!cancelled) setStatus(value); }).catch(reason => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, []);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); setStatus(await api.accountSecurity()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể cập nhật bảo mật. Vui lòng thử lại.'); }
    finally { setBusy(false); setCurrent(''); setMfaPassword(''); setCode(''); }
  };
  return <section className="panel workspace-form account-security">
    <header className="panel-heading"><div><h2>Bảo mật tài khoản</h2><p>Áp dụng cho tài khoản của bạn trong mọi workspace.</p></div><ShieldCheck size={20}/></header>
    <div className="account-security-content">
      {error && <p className="auth-error" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {!status ? error ? <Button disabled={busy} onClick={() => void run(async () => {})}>Tải lại cài đặt bảo mật</Button> : <p role="status">Đang tải cài đặt bảo mật…</p> : <>
        <div><h3>Xác minh email</h3><p>{status.emailVerified ? 'Email đã được xác minh.' : 'Xác minh quyền sở hữu email để bảo vệ tài khoản và khôi phục quyền truy cập khi cần.'}</p>
          {!status.emailVerified && <Button disabled={busy} onClick={() => void run(async () => { const result = await api.requestVerification(); setMessage(result.message); })}>Gửi email xác minh</Button>}
        </div>
        <form onSubmit={event => { event.preventDefault(); if (next !== confirm) { setError('Hai lần nhập mật khẩu mới chưa khớp.'); return; } void run(async () => { await api.changePassword(current, next, code); setNext(''); setConfirm(''); setMessage('Đã đổi mật khẩu và đăng xuất các thiết bị khác.'); }); }}>
          <h3>Đổi mật khẩu</h3>
          <label className="form-field">Mật khẩu hiện tại<input type="password" autoComplete="current-password" value={current} onChange={event => setCurrent(event.target.value)} required maxLength={128} disabled={busy}/></label>
          <label className="form-field">Mật khẩu mới<input type="password" autoComplete="new-password" value={next} onChange={event => setNext(event.target.value)} minLength={12} maxLength={128} required disabled={busy}/><small>Ít nhất 12 ký tự. Nên dùng mật khẩu riêng cho ứng dụng này.</small></label>
          <label className="form-field">Nhập lại mật khẩu mới<input type="password" autoComplete="new-password" value={confirm} onChange={event => setConfirm(event.target.value)} minLength={12} maxLength={128} required disabled={busy}/></label>
          {status.mfaEnabled && <label className="form-field">Mã xác thực hoặc mã khôi phục<input autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} maxLength={64} required disabled={busy}/></label>}
          <Button type="submit" variant="primary" loading={busy}>Đổi mật khẩu</Button>
        </form>
        <form onSubmit={event => { event.preventDefault(); void run(async () => {
          if (secret) { const result = await api.enableMFA(code); setSecret(''); setCodes(result.recoveryCodes); setSavedCodes(false); setMessage('Đã bật xác thực hai bước. Hãy lưu các mã khôi phục bên dưới.'); }
          else if (status.mfaEnabled) { await api.disableMFA(mfaPassword, code); setMessage('Đã tắt xác thực hai bước và đăng xuất các thiết bị khác.'); }
          else { const result = await api.setupMFA(mfaPassword); setSecret(result.secret); }
        }); }}>
          <h3>Xác thực hai bước</h3>
          <p>{status.mfaEnabled ? `Đang bật · Còn ${status.recoveryCodesRemaining} mã khôi phục.` : 'Thêm mã từ Google Authenticator, Microsoft Authenticator hoặc ứng dụng tương thích khi đăng nhập.'}</p>
          {secret ? <>
            <p>Trong ứng dụng xác thực, chọn nhập khóa thiết lập, loại mã theo thời gian. Khóa này chỉ hiển thị trong lần thiết lập hiện tại.</p>
            <label className="form-field">Khóa thiết lập<input readOnly value={secret} autoComplete="off" spellCheck={false}/></label>
          </> : <label className="form-field">Xác nhận mật khẩu hiện tại<input type="password" autoComplete="current-password" value={mfaPassword} onChange={event => setMfaPassword(event.target.value)} required maxLength={128} disabled={busy}/></label>}
          {(secret || status.mfaEnabled) && <label className="form-field">{secret ? 'Mã 6 số từ ứng dụng xác thực' : 'Mã xác thực hoặc mã khôi phục'}<input autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} required maxLength={64} disabled={busy}/></label>}
          <Button type="submit" loading={busy}>{secret ? 'Xác nhận bật hai bước' : status.mfaEnabled ? 'Tắt xác thực hai bước' : 'Thiết lập xác thực hai bước'}</Button>
          {secret && <Button type="button" disabled={busy} onClick={() => { setSecret(''); setCode(''); }}>Hủy thiết lập</Button>}
        </form>
        {codes.length > 0 && <section aria-label="Mã khôi phục tài khoản" className="recovery-codes">
          <h3>Lưu mã khôi phục</h3><p>Mỗi mã chỉ dùng một lần khi mất ứng dụng xác thực. Lưu trong trình quản lý mật khẩu hoặc nơi riêng tư. Các mã sẽ không hiển thị lại sau khi rời trang.</p>
          <ul>{codes.map(value => <li key={value}><code>{value}</code></li>)}</ul>
          <label className="security-check"><input type="checkbox" checked={savedCodes} onChange={event => setSavedCodes(event.target.checked)}/>Tôi đã lưu các mã khôi phục an toàn.</label>
          <Button disabled={!savedCodes} onClick={() => setCodes([])}>Ẩn mã khôi phục</Button>
        </section>}
        <div><h3>Đăng xuất mọi thiết bị</h3><p>Thu hồi mọi phiên đăng nhập, bao gồm thiết bị đang dùng.</p>
          <label className="security-check"><input type="checkbox" checked={logoutConfirmed} onChange={event => setLogoutConfirmed(event.target.checked)} disabled={busy}/>Tôi muốn đăng xuất tất cả thiết bị.</label>
          <Button disabled={!logoutConfirmed || busy} onClick={() => void run(async () => { await api.logoutAll(); window.dispatchEvent(new Event('session-expired')); })}>Đăng xuất tất cả</Button>
        </div>
      </>}
    </div>
  </section>;
}

import { useState } from 'react';
import { api } from '../api';
import { Button } from '../components/ui';

export function AccountLinkPage({ purpose, token }: { purpose: 'verify' | 'reset'; token: string }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  return <main className="account-link-shell"><section className="panel workspace-form"><header className="panel-heading"><div><h1>{purpose === 'verify' ? 'Xác minh email' : 'Đặt lại mật khẩu'}</h1><p>AI Support Operations</p></div></header>
    {done ? <div className="settings-summary"><p role="status">{purpose === 'verify' ? 'Đã xác minh email. Bạn có thể quay lại workspace.' : 'Đã đổi mật khẩu và đăng xuất mọi thiết bị. Hãy đăng nhập bằng mật khẩu mới.'}</p><a className="text-link" href="/#login=1">Quay lại ứng dụng</a></div> : <form onSubmit={event => { event.preventDefault(); if (purpose === 'reset' && password !== confirm) { setError('Hai lần nhập mật khẩu chưa khớp.'); return; } setBusy(true); setError(''); const action = purpose === 'verify' ? api.verifyEmail(token) : api.resetPassword(token, password, code); void action.then(() => { setDone(true); setPassword(''); setConfirm(''); setCode(''); window.history.replaceState(null, '', '/'); }).catch(reason => setError(reason.message)).finally(() => setBusy(false)); }}>
      <p>Link có hiệu lực 30 phút và chỉ dùng một lần.</p>
      {purpose === 'reset' && <>
        <label className="form-field">Mật khẩu mới<input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} required disabled={busy}/></label>
        <label className="form-field">Nhập lại mật khẩu<input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={confirm} onChange={event => setConfirm(event.target.value)} required disabled={busy}/></label>
        <label className="form-field">Mã xác thực hai bước hoặc mã khôi phục<input autoComplete="one-time-code" maxLength={64} value={code} onChange={event => setCode(event.target.value)} disabled={busy}/><small>Để trống nếu tài khoản chưa bật xác thực hai bước.</small></label>
      </>}
      {error && <p role="alert" className="auth-error">{error}</p>}
      <Button type="submit" variant="primary" loading={busy}>{purpose === 'verify' ? 'Xác nhận email của tôi' : 'Lưu mật khẩu mới'}</Button>
      <a className="text-link" href="/#login=1">Quay lại ứng dụng</a>
    </form>}
  </section></main>;
}

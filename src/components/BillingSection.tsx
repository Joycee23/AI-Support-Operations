import { useEffect, useState } from 'react';
import { CheckCircle2, Copy, CreditCard, RefreshCw } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap, PaymentOrder } from '../types';
import { Button } from './ui';

const money = (value: number) => new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value);
export const billingDate = (value: string) => new Date(value).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'medium', timeStyle: 'short' });
export const subscriptionLabel = (status: string) => status === 'trialing' ? 'Dùng thử 1 tháng' : status === 'active' ? 'Gói doanh nghiệp' : 'Đã hết hạn';

export function BillingSection({ data, refresh }: { data: Bootstrap; refresh: () => Promise<void> }) {
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [orders, setOrders] = useState<PaymentOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [qrError, setQrError] = useState(false);
  const admin = data.user.role === 'admin';
  const sub = data.subscription;

  useEffect(() => {
    let cancelled = false;
    api.billing().then(value => {
      if (cancelled) return;
      setOrders(value.orders);
      setOrder(value.orders.find(item => item.status === 'pending') || null);
    }).catch(reason => { if (!cancelled) setError(reason.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!order || order.status !== 'pending') return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.paymentOrder(order.id);
        if (cancelled) return;
        setOrder(next); setError('');
        if (next.status === 'paid') {
          setMessage('Đã nhận thanh toán. Workspace được gia hạn thêm 1 tháng.');
          setOrders((await api.billing()).orders);
          if (!cancelled) await refresh();
        }
        if (next.status !== 'pending') return;
      } catch (reason) { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Chưa cập nhật được trạng thái thanh toán.'); }
      if (!cancelled) timer = setTimeout(() => void poll(), 5000);
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [order?.id, order?.status, refresh]);

  async function createOrder() {
    setBusy(true); setError(''); setMessage(''); setQrError(false);
    try { const next = await api.createPaymentOrder(); setOrder(next); setOrders((await api.billing()).orders); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể tạo yêu cầu thanh toán.'); }
    finally { setBusy(false); }
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setMessage('Đã sao chép.'); }
    catch { setError('Trình duyệt chưa cho phép sao chép. Hãy chọn và sao chép thông tin bên dưới.'); }
  }

  return <section className="panel billing-section" id="billing" aria-labelledby="billing-title">
    <header className="panel-heading"><div><h2 id="billing-title">Gói dịch vụ & thanh toán</h2><p>Mỗi doanh nghiệp một gói, thanh toán qua SePay.</p></div><CreditCard size={20}/></header>
    <div className="billing-content">
      <div className="billing-plan"><div><span className={`billing-state ${sub.status}`}>{subscriptionLabel(sub.status)}</span><h3>{money(sub.monthlyPrice)}<small> / tháng / doanh nghiệp</small></h3><p>{sub.status === 'trialing' ? `Dùng thử đến ${billingDate(sub.trialEndsAt)}.` : `Thời hạn sử dụng: ${billingDate(sub.accessUntil)}.`}</p>{sub.paidUntil && sub.status === 'trialing' && <p>Đã gia hạn đến {billingDate(sub.paidUntil)}.</p>}<p>Trả trước 1 tháng. Thanh toán sớm được cộng tiếp vào thời hạn còn lại. Không tự trừ tiền.</p></div>
      {admin ? <Button variant="primary" loading={busy || loading} disabled={!sub.paymentConfigured || order?.status === 'pending'} onClick={() => void createOrder()}>{order?.status === 'pending' ? 'Đang chờ thanh toán' : 'Gia hạn 1 tháng'}</Button> : <p>Liên hệ quản trị viên workspace để gia hạn.</p>}</div>
      {!sub.paymentConfigured && <p className="billing-help" role="status">Thanh toán chưa sẵn sàng. Đơn vị cung cấp cần hoàn tất cấu hình tài khoản nhận tiền SePay.</p>}
      {!sub.canWrite && <p className="auth-error">Workspace đã hết hạn. Bạn vẫn xem được dữ liệu; tạo, chỉnh sửa và sử dụng AI sẽ mở lại sau khi gia hạn.</p>}
      {error && <div className="auth-error" role="alert">{error}<Button onClick={() => { setLoading(true); api.billing().then(value => { setOrders(value.orders); setError(''); }).catch(reason => setError(reason.message)).finally(() => setLoading(false)); }}>Thử lại</Button></div>}
      {message && <p className="billing-message" role="status">{message}</p>}
      {order && order.status === 'pending' && <div className="bank-checkout"><div className="bank-qr">{order.qrUrl && !qrError ? <img src={order.qrUrl} width="240" height="280" alt={`Mã VietQR thanh toán ${money(order.amount)}`} onError={() => setQrError(true)}/> : <p>Chưa tải được mã QR. Bạn có thể chuyển khoản theo thông tin bên cạnh.</p>}</div><div className="bank-details"><h3>Quét mã bằng ứng dụng ngân hàng</h3><p>Giữ nguyên số tiền và nội dung để hệ thống xác nhận đúng workspace.</p><dl><div><dt>Ngân hàng</dt><dd>{order.bank}</dd></div><div><dt>Chủ tài khoản</dt><dd>{order.accountName}</dd></div><div><dt>Số tài khoản</dt><dd>{order.accountNumber}<Button aria-label="Sao chép số tài khoản" onClick={() => void copy(order.accountNumber)}><Copy size={14}/></Button></dd></div><div><dt>Số tiền</dt><dd>{money(order.amount)}</dd></div><div><dt>Nội dung</dt><dd><strong>{order.transferCode}</strong><Button aria-label="Sao chép nội dung chuyển khoản" onClick={() => void copy(order.transferCode)}><Copy size={14}/></Button></dd></div></dl><p className="payment-wait"><RefreshCw size={14}/> Tự cập nhật khi ngân hàng xác nhận.</p><small>Mã có hiệu lực đến {billingDate(order.expiresAt)}. Nếu đã chuyển tiền, hãy chờ xác nhận và không chuyển lại.</small></div></div>}
      {order?.status === 'paid' && <p className="billing-message" role="status"><CheckCircle2 size={17}/> Thanh toán {money(order.amount)} đã được xác nhận.</p>}
      {order?.status === 'expired' && <p className="billing-help">Mã đã hết hạn. Nếu đã chuyển khoản, giao dịch đúng thông tin vẫn được ghi nhận khi SePay gửi xác nhận. Đừng chuyển lần hai.</p>}
      {admin && <div className="billing-history"><h3>Lịch sử yêu cầu thanh toán</h3>{loading ? <p role="status">Đang tải lịch sử…</p> : orders.length ? <div className="billing-history-list">{orders.map(item => <div className="billing-history-row" key={item.id}><div><b>{money(item.amount)}</b><small>{billingDate(item.createdAt)}</small></div><span>{item.transferCode}</span><span className={`billing-state ${item.status}`}>{item.status === 'paid' ? 'Đã thanh toán' : item.status === 'expired' ? 'Hết hạn' : 'Chờ chuyển khoản'}</span></div>)}</div> : <p>Chưa có yêu cầu thanh toán.</p>}</div>}
    </div>
  </section>;
}

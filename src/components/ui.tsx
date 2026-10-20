import type { LucideIcon } from 'lucide-react';
import { Inbox, CheckCircle2, Circle, LoaderCircle, ShieldAlert } from 'lucide-react';

export function Button({ children, variant = 'quiet', loading = false, disabled, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'quiet' | 'subtle'; loading?: boolean }) {
  return <button {...props} disabled={disabled || loading} className={`button button-${variant} ${props.className || ''}`}>
    {loading && <LoaderCircle className="spin" size={15}/>} {children}
  </button>;
}

export function Metric({ label, value, note, icon: Icon, tone = 'blue' }: { label: string; value: string | number; note: string; icon: LucideIcon; tone?: string }) {
  return <article className="metric"><div className="metric-top"><span>{label}</span><i className={`metric-icon ${tone}`}><Icon size={16}/></i></div><strong className="metric-value">{value}</strong><span className="metric-sub">{note}</span></article>;
}

export function Status({ value }: { value: string }) {
  const state = value === 'Đã giải quyết' || value === 'Đã duyệt' ? 'done' : value === 'Đang xử lý' ? 'progress' : value.startsWith('Chờ') ? 'waiting' : value === 'Lỗi' ? 'error' : 'new';
  const Icon = state === 'done' ? CheckCircle2 : state === 'error' ? ShieldAlert : Circle;
  return <span className={`status ${state}`}><Icon size={11}/>{value}</span>;
}

export function Priority({ value }: { value: string }) {
  const state = value === 'Khẩn cấp' ? 'urgent' : value === 'Cao' ? 'high' : value === 'Bình thường' ? 'normal' : 'low';
  return <span className={`priority-label ${state}`}><i/>{value}</span>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return <div className="empty-state"><span className="empty-mark"><Inbox size={28}/></span><b>{title}</b><span>{detail}</span>{action}</div>;
}

export function Notice({ tone = 'info', children }: { tone?: string; children: React.ReactNode }) {
  return <div className={`notice ${tone}`}>{children}</div>;
}

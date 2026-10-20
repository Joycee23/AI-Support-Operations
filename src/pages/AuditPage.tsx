import { Activity } from 'lucide-react';
import type { AuditEvent } from '../types';
import { EmptyState } from '../components/ui';

export function AuditPage({ events }: { events: AuditEvent[] }) {
  return <section className="page-content"><div className="page-heading"><div><h1>Nhật ký hoạt động</h1><p>Thay đổi đã ghi nhận trong workspace hiện tại.</p></div></div><section className="audit-list">{events.length ? events.map((event, index) => <article className="audit-row" key={event.id}><span className={`audit-mark mark-${index % 4}`}><Activity size={15}/></span><span className="audit-copy"><b>{event.detail}</b><small>{event.actor}{event.ticketCode ? ` · ${event.ticketCode}` : ''}</small></span><time>{new Date(event.createdAt).toLocaleString('vi-VN')}</time></article>) : <EmptyState title="Chưa có hoạt động" detail="Thao tác sẽ được ghi nhận ở đây."/>}</section></section>;
}

import { useEffect, useState } from 'react';
import { AlertCircle, CheckCheck, CircleHelp, RotateCcw, Settings2, ShieldAlert, X } from 'lucide-react';
import { api } from '../api';
import type { Report, User } from '../types';
import { EmptyState, Metric } from '../components/ui';

export function ReportsPage({ user, notify }: { user: User; notify: (message: string) => void }) {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); api.report(user.id).then(setReport).catch(error => notify(error.message)).finally(() => setLoading(false)); };
  useEffect(load, [user.id]);
  const total = report ? report.accepted + report.edited + report.rejected : 0;
  const max = Math.max(1, report?.accepted || 0, report?.edited || 0, report?.rejected || 0);
  return <section className="page-content">
    <div className="page-heading"><div><h1>Chất lượng AI</h1><p>Quyết định đã lưu từ các gợi ý AI trong workspace.</p></div><button className="button button-quiet" onClick={load}><RotateCcw size={14}/> Làm mới</button></div>
    <div className="metric-grid"><Metric label="Được chấp nhận" value={report?.accepted || 0} note="Nhân viên xác nhận dùng" icon={CheckCheck} tone="green"/><Metric label="Được chỉnh sửa" value={report?.edited || 0} note="Sửa trước khi xác nhận" icon={Settings2} tone="blue"/><Metric label="Đã bỏ" value={report?.rejected || 0} note="Nhân viên bỏ gợi ý" icon={X} tone="red"/><Metric label="Chuyển người / thiếu nguồn" value={report?.missingKnowledge || 0} note="Không tạo bản nháp gửi khách" icon={ShieldAlert} tone="amber"/></div>
    <div className="report-grid"><section className="panel report-chart"><header className="panel-heading"><span><h2>Quyết định với gợi ý</h2><p>Dữ liệu tích lũy đã được ghi nhận</p></span><small>{total} quyết định</small></header>
      {loading ? <div className="chart-placeholder">Đang tải báo cáo…</div> : total === 0 ? <EmptyState title="Chưa có feedback" detail="Sau khi nhân viên xử lý gợi ý AI, các quyết định sẽ xuất hiện tại đây."/> : <div className="bar-chart">{[['Chấp nhận', report!.accepted, 'green'], ['Chỉnh sửa', report!.edited, 'blue'], ['Bỏ gợi ý', report!.rejected, 'red']].map(([label, value, color]) => <div className="bar-row" key={String(label)}><span>{label}</span><div><i className={String(color)} style={{ width: `${Number(value) / max * 100}%` }}/></div><b>{value}</b></div>)}</div>}
      <p className="chart-footnote">Số liệu phản ánh các quyết định đã lưu; chưa phải đánh giá hiệu quả hay độ chính xác mô hình.</p>
    </section><section className="panel report-insights"><header className="panel-heading"><span><h2>Thiếu kiến thức và lỗi</h2><p>Trạng thái cần theo dõi</p></span><CircleHelp size={16}/></header><div className="insight-line"><span className="insight-mark amber-mark"><AlertCircle size={13}/></span><p><b>{report?.missingKnowledge || 0}</b> gợi ý đã abstain do thiếu căn cứ hoặc nội dung nhạy cảm.</p></div><div className="insight-line"><span className="insight-mark red-mark"><X size={13}/></span><p><b>{report?.errors || 0}</b> lỗi AI hoặc truy xuất được ghi trong audit.</p></div><div className="insight-line"><span className="insight-mark"><ShieldAlert size={13}/></span><p>Nhân viên cần kiểm tra nguồn, ngữ cảnh và bản nháp trước khi xác nhận.</p></div></section></div>
    <section className="panel recent-analyses"><header className="panel-heading"><span><h2>Phân tích gần đây</h2><p>Ticket đã nhận gợi ý AI</p></span></header>{report?.recent.length ? report.recent.map(item => <div className="analysis-row" key={item.id}><b>{item.ticketCode || 'Ticket'}</b><span>{item.topic}</span><span>{item.grounded ? 'Có căn cứ' : 'Cần người xem xét'}</span><small>{item.feedback === 'accepted' ? 'Chấp nhận' : item.feedback === 'edited' ? 'Đã sửa' : item.feedback === 'rejected' ? 'Đã bỏ' : 'Chưa quyết định'}</small><time>{new Date(item.createdAt).toLocaleString('vi-VN')}</time></div>) : <EmptyState title="Chưa có phân tích" detail="Dùng AI từ chi tiết ticket để ghi nhận phân tích đầu tiên."/>}</section>
  </section>;
}

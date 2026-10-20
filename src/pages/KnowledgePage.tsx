import { useEffect, useState } from 'react';
import { Archive, BookOpen, Check, ChevronRight, FilePlus2, FileText, History, LoaderCircle, Plus, Search, ShieldCheck, Sparkles, UploadCloud, X } from 'lucide-react';
import { api } from '../api';
import type { Bootstrap, Knowledge, KnowledgeVersion, User } from '../types';
import { Button, EmptyState, Notice, Status } from '../components/ui';

type Props = { data: Bootstrap; user: User; refresh: () => Promise<void>; notify: (message: string) => void };
type Mode = 'manual' | 'faq' | 'file';

export function KnowledgePage({ data, user, refresh, notify }: Props) {
  const [items, setItems] = useState<Knowledge[]>(data.knowledge);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Knowledge | null>(null);
  const [mode, setMode] = useState<Mode>('manual');
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [answer, setAnswer] = useState('');
  const [teamId, setTeamId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [actingId, setActingId] = useState<string | null>(null);
  const [versions, setVersions] = useState<KnowledgeVersion[] | null>(null);
  const canEditItem = (item: Knowledge) => user.role === 'admin' || user.role === 'manager' && item.teamId === user.teamId;
  const readOnly = !!selected && (!canEditItem(selected) || selected.status === 'archived');
  const canManage = user.role !== 'agent';

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api.knowledge(user.id, status || undefined, query).then(value => { if (!cancelled) setItems(value); })
        .catch(error => { if (!cancelled) notify(error.message); });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [user.id, status, query, data.knowledge, notify]);

  const hasProcessing = items.some(item => item.processingStatus === 'queued' || item.processingStatus === 'processing');
  useEffect(() => {
    if (!hasProcessing) return;
    let cancelled = false;
    let busy = false;
    const timer = window.setInterval(async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const next = await api.knowledge(user.id, status || undefined, query);
        if (!cancelled) setItems(next);
      } catch { /* Keep current content; the next visible poll can recover. */ }
      finally { busy = false; }
    }, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [user.id, status, query, hasProcessing]);

  useEffect(() => {
    if (!open && !versions) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () => [...(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]') || [])];
    focusable()[0]?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { if (!saving) { setOpen(false); setVersions(null); } return; }
      if (event.key !== 'Tab') return;
      const controls = focusable();
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', keyboard);
    return () => { document.removeEventListener('keydown', keyboard); previous?.focus(); };
  }, [open, versions, saving]);

  const resetForm = () => { setSelected(null); setMode('manual'); setTitle(''); setCategory(''); setContent(''); setAnswer(''); setTeamId(user.role === 'manager' ? user.teamId || '' : ''); setFile(null); };
  const openCreate = () => { resetForm(); setOpen(true); };
  const openEdit = (item: Knowledge) => { setSelected(item); setTitle(item.title); setCategory(item.category); setContent(item.content); setTeamId(item.teamId || ''); setMode('manual'); setOpen(true); };
  const save = async () => {
    setSaving(true);
    try {
      if (mode === 'file' && file) {
        const form = new FormData(); form.set('title', title); form.set('category', category); form.set('file', file); if (teamId) form.set('team_id', teamId);
        await api.uploadKnowledge(user.id, form);
      } else if (selected) {
        await api.updateKnowledge(selected.id, user.id, { title, category, content, team_id: teamId || null, change_note: 'Sửa trong kho kiến thức' });
      } else {
        await api.createKnowledge(user.id, { title, category, content, team_id: teamId || null });
      }
      setOpen(false); resetForm(); await refresh(); notify('Đã lưu. Nội dung mới cần xử lý và duyệt trước khi dùng.');
    } catch (error) { notify(error instanceof Error ? error.message : 'Không thể lưu kiến thức.'); }
    finally { setSaving(false); }
  };
  const createDraft = async () => {
    setSaving(true);
    try { const draft = await api.draftFAQ(user.id, title, answer); setTitle(draft.title || title); setCategory(draft.category || category); setContent(draft.content || ''); if (draft.notes?.length) notify(`Bản nháp đã tạo. Cần xác nhận: ${draft.notes.join(' · ')}`); }
    catch (error) { notify(`AI chưa thể soạn bản nháp: ${error instanceof Error ? error.message : 'Thử lại sau.'}`); }
    finally { setSaving(false); }
  };
  const showVersions = async (item: Knowledge) => {
    try { setSelected(item); setVersions(await api.knowledgeVersions(item.id, user.id)); }
    catch (error) { notify(error instanceof Error ? error.message : 'Không thể tải lịch sử phiên bản.'); }
  };
  const actOnItem = async (item: Knowledge, action: 'approve' | 'archive' | 'retry') => {
    if (actingId) return;
    setActingId(item.id);
    try {
      if (action === 'retry') await api.retryKnowledge(item.id, user.id);
      else if (action === 'approve') await api.approveKnowledge(item.id, user.id); else await api.archiveKnowledge(item.id, user.id);
      await refresh(); notify(action === 'retry' ? 'Đã xếp hàng xử lý lại tài liệu.' : action === 'approve' ? 'Đã duyệt tài liệu.' : 'Đã lưu trữ tài liệu.');
    } catch (error) { notify(error instanceof Error ? error.message : 'Không thể cập nhật trạng thái tài liệu.'); }
    finally { setActingId(null); }
  };

  return <section className="page-content">
    <div className="page-heading"><div><h1>Kho kiến thức</h1><p>Chỉ nội dung đã duyệt, xử lý xong và được phép truy cập mới làm căn cứ cho AI.</p></div>{canManage && <Button variant="primary" onClick={openCreate}><FilePlus2 size={15}/> Thêm kiến thức</Button>}</div>
    <Notice><ShieldCheck size={16}/><span><b>Kiểm duyệt trước khi sử dụng</b><small>Mọi mục mới đều ở trạng thái chờ duyệt. AI chỉ truy xuất tài liệu có embedding sẵn sàng và quyền phù hợp.</small></span></Notice>
    <div className="knowledge-toolbar"><div className="knowledge-tabs">{[['', 'Tất cả'], ['approved', 'Đã duyệt'], ['pending', 'Chờ duyệt'], ['archived', 'Lưu trữ']].map(([value, label]) => <button key={value} className={status === value ? 'selected' : ''} onClick={() => setStatus(value)}>{label}</button>)}</div><label className="global-search"><Search size={14}/><input aria-label="Tìm tài liệu" value={query} onChange={event => setQuery(event.target.value)} placeholder="Tìm tài liệu…"/></label></div>
    <div className="knowledge-table"><div className="table-header"><span>TÀI LIỆU</span><span>TRẠNG THÁI</span><span>PHIÊN BẢN</span><span>CẬP NHẬT</span><span/></div>
      {items.map(item => <article className="knowledge-row" key={item.id}><button className="doc-title" disabled={!!actingId} onClick={() => openEdit(item)}><span className="doc-icon"><FileText size={15}/></span><span><b>{item.title}</b><small>{item.category} · {item.createdBy || 'Workspace'}</small></span></button><span className="knowledge-state"><Status value={item.status === 'approved' ? 'Đã duyệt' : item.status === 'archived' ? 'Lưu trữ' : 'Chờ duyệt'}/><small className={`processing ${item.processingStatus}`}>{processingLabel(item.processingStatus)}</small></span><code className="version-tag">v{item.version}</code><time className="updated-cell">{new Date(item.updatedAt).toLocaleDateString('vi-VN')}</time><div className="row-actions">
        {item.status === 'pending' && canEditItem(item) && <button className="approve-button" disabled={!!actingId || item.processingStatus !== 'ready'} onClick={() => void actOnItem(item, 'approve')}><Check size={13}/> Duyệt</button>}
        {item.processingStatus === 'failed' && canEditItem(item) && item.status !== 'archived' && <button className="approve-button" disabled={!!actingId} onClick={() => void actOnItem(item, 'retry')}>Thử xử lý lại</button>}
        {canEditItem(item) && item.status !== 'archived' && <button className="icon-btn" disabled={!!actingId} title="Sửa tài liệu" onClick={() => openEdit(item)}><FileText size={14}/></button>}
        <button className="icon-btn" title="Lịch sử phiên bản" onClick={() => void showVersions(item)}><History size={14}/></button>
        {canEditItem(item) && item.status !== 'archived' && <button className="icon-btn" disabled={!!actingId} title="Lưu trữ" onClick={() => void actOnItem(item, 'archive')}><Archive size={14}/></button>}
      </div></article>)}
      {items.length === 0 && <EmptyState title="Không có tài liệu phù hợp" detail="Thử đổi trạng thái hoặc từ khóa tìm kiếm."/>}
    </div>

    {open && <div className="overlay" onMouseDown={event => { if (!saving && event.target === event.currentTarget) { setOpen(false); resetForm(); } }}><section className="dialog knowledge-dialog" role="dialog" aria-modal="true" aria-label={readOnly ? "Xem kiến thức" : "Biểu mẫu kiến thức"}><header className="dialog-head"><div><h2>{selected ? readOnly ? 'Xem kiến thức' : 'Cập nhật kiến thức' : 'Thêm kiến thức'}</h2><p>{readOnly ? 'Nội dung được hiển thị theo quyền truy cập của bạn.' : 'Bản mới sẽ chờ duyệt trước khi AI có thể truy xuất.'}</p></div><button className="icon-btn" disabled={saving} onClick={() => { setOpen(false); resetForm(); }} aria-label="Đóng"><X size={17}/></button></header>
      {!selected && <div className="mode-tabs">{([['manual', 'Nhập nội dung'], ['faq', 'Soạn cùng AI'], ['file', 'Tải tệp']] as const).map(([value, label]) => <button key={value} className={mode === value ? 'selected' : ''} disabled={saving} onClick={() => setMode(value)}>{label}</button>)}</div>}
      <label className="form-field">Tiêu đề<input disabled={saving} readOnly={readOnly} maxLength={240} value={title} onChange={event => setTitle(event.target.value)} placeholder="Ví dụ: Chính sách đổi hàng"/></label>
      <label className="form-field">Danh mục<input disabled={saving} readOnly={readOnly} maxLength={100} value={category} onChange={event => setCategory(event.target.value)} placeholder="Ví dụ: Đổi trả"/></label>
      {user.role === 'manager' ? <label className="form-field">Phạm vi nhóm<input value={data.teams.find(team => team.id === user.teamId)?.name || 'Nhóm của bạn'} disabled readOnly /></label> : <label className="form-field">Phạm vi nhóm<select disabled={readOnly || saving} value={teamId} onChange={event => setTeamId(event.target.value)}><option value="">Toàn workspace</option>{data.teams.map(team => <option value={team.id} key={team.id}>{team.name}</option>)}</select></label>}
      {mode === 'faq' && !content && <label className="form-field">Thông tin đã được xác nhận<textarea disabled={saving} maxLength={4000} rows={4} value={answer} onChange={event => setAnswer(event.target.value)} placeholder="Trả lời những câu hỏi quan trọng về chính sách…"/><Button variant="quiet" loading={saving} disabled={!title || !answer} onClick={() => void createDraft()}><Sparkles size={14}/> Tạo bản nháp bằng AI</Button></label>}
      {mode === 'file' && !selected && <label className="upload-drop"><UploadCloud size={21}/><b>{file?.name || 'Chọn tệp TXT, MD hoặc PDF'}</b><small>Giới hạn 10 MB. Tệp scan không OCR.</small><input disabled={saving} type="file" accept=".txt,.md,.pdf" onChange={event => setFile(event.target.files?.[0] || null)}/></label>}
      {(mode === 'manual' || content || mode === 'faq' && content) && <label className="form-field">Nội dung<textarea disabled={saving} readOnly={readOnly} maxLength={30000} rows={7} value={content} onChange={event => setContent(event.target.value)} placeholder="Nhập chính sách đã được xác nhận…"/></label>}
      <Notice tone="success"><ShieldCheck size={15}/><span>Nội dung chỉ dùng sau khi xử lý xong và được người có quyền duyệt.</span></Notice>
      <footer className="dialog-actions"><Button disabled={saving} onClick={() => { setOpen(false); resetForm(); }}>{readOnly ? 'Đóng' : 'Hủy'}</Button>{!readOnly && <Button variant="primary" loading={saving} disabled={!title || !category || mode === 'file' && !file || mode !== 'file' && content.trim().length < 20} onClick={() => void save()}><Plus size={14}/> Lưu bản chờ duyệt</Button>}</footer>
    </section></div>}

    {versions && <div className="overlay" onMouseDown={event => { if (event.target === event.currentTarget) setVersions(null); }}><section className="dialog version-dialog" role="dialog" aria-modal="true" aria-label="Lịch sử phiên bản"><header className="dialog-head"><div><h2>Lịch sử phiên bản</h2><p>{selected?.title}</p></div><button className="icon-btn" aria-label="Đóng lịch sử phiên bản" onClick={() => setVersions(null)}><X size={17}/></button></header>{versions.length ? versions.map(version => <article className="version-row" key={version.version}><div><b>Phiên bản {version.version}</b><small>{version.changeNote} · {version.changedBy} · {new Date(version.createdAt).toLocaleString('vi-VN')}</small></div><details><summary>Xem nội dung</summary><p>{version.content}</p></details></article>) : <EmptyState title="Chưa có lịch sử" detail="Phiên bản sẽ xuất hiện sau lần cập nhật đầu tiên."/>}</section></div>}
  </section>;
}

function processingLabel(status: string) { return ({ queued: 'Đang chờ xử lý', processing: 'Đang tạo embedding', ready: 'Sẵn sàng', failed: 'Lỗi xử lý' } as Record<string, string>)[status] || status; }

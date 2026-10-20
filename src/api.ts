import type { AISuggestion, Bootstrap, PaymentOrder, Subscription, Knowledge, KnowledgeVersion, Report, TicketDetail } from './types';

let activeMembership = '';
const API_URL = `${import.meta.env.VITE_API_URL || ''}/api`;
export class ApiError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

async function request<T>(path: string, _userId: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...((_userId || activeMembership) ? { 'X-Workspace-Membership': _userId || activeMembership } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError('Không thể kết nối API. Kiểm tra kết nối mạng và thử lại sau.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 402) window.dispatchEvent(new Event('subscription-expired'));
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('session-expired'));
    const baseMessage = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? 'Thông tin chưa hợp lệ. Vui lòng kiểm tra các trường và độ dài nội dung.' : 'Thao tác chưa hoàn tất. Vui lòng thử lại.';
    const retryAfter = Number(response.headers.get('Retry-After'));
    const message = response.status === 429 && retryAfter > 0 ? `${baseMessage} Thử lại sau khoảng ${Math.ceil(retryAfter / 60)} phút.` : baseMessage;
    throw new ApiError(message, response.status);
  }
  return data as T;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const api = {
  billing: () => request<{ subscription: Subscription; orders: PaymentOrder[] }>('/billing', ''),
  createPaymentOrder: () => request<PaymentOrder>('/billing/orders', '', json({})),
  paymentOrder: (id: string) => request<PaymentOrder>(`/billing/orders/${id}`, ''),
  bootstrap: async (userId: string) => { const data = await request<Bootstrap>('/bootstrap', userId); activeMembership = data.user.id; return data; },
  ticket: (id: string, userId: string) => request<TicketDetail>(`/tickets/${id}`, userId),
  updateTicket: (id: string, userId: string, body: Record<string, unknown>) => request(`/tickets/${id}`, userId, { ...json(body), method: 'PATCH' }),
  suggest: (id: string, userId: string) => request<AISuggestion>(`/ai/tickets/${id}/suggest`, userId, json({})),
  feedback: (id: string, userId: string, decision: string, editedDraft?: string) => request(`/ai/analyses/${id}/feedback`, userId, json({ decision, edited_draft: editedDraft, save_reply: true })),
  createKnowledge: (userId: string, body: { title: string; category: string; content: string; team_id: string | null }) => request('/knowledge', userId, json(body)),
  updateKnowledge: (id: string, userId: string, body: Record<string, unknown>) => request(`/knowledge/${id}`, userId, { method: 'PUT', body: JSON.stringify(body) }),
  knowledgeVersions: (id: string, userId: string) => request<KnowledgeVersion[]>(`/knowledge/${id}/versions`, userId),
  retryKnowledge: (id: string, userId: string) => request(`/knowledge/${id}/retry`, userId, json({})),
  approveKnowledge: (id: string, userId: string) => request(`/knowledge/${id}/approve`, userId, json({})),
  archiveKnowledge: (id: string, userId: string) => request(`/knowledge/${id}/archive`, userId, json({})),
  draftFAQ: (userId: string, subject: string, answer: string) => request<{ title: string; category: string; content: string; notes: string[]; status: string }>('/knowledge/draft-faq', userId, json({ subject, answers: { answer } })),
  uploadKnowledge: (userId: string, form: FormData) => request('/knowledge/upload?' + new URLSearchParams({ title: String(form.get('title')), category: String(form.get('category')), ...(form.get('team_id') ? { team_id: String(form.get('team_id')) } : {}) }), userId, { method: 'POST', body: form }),
  createTeam: (userId: string, name: string, color: string) => request('/admin/teams', userId, json({ name, color })),
  inviteMember: (body: { email: string; role: string; team_id: string }) => request<{ token: string; url: string | null; email: string; expiresAt: string; emailDelivery: { status: string; message: string } }>('/auth/invitations', '', json(body)),
  invitations: () => request<Array<{ id: string; email: string; role: string; teamId: string; expiresAt: string; emailDelivery: { status: string; message: string } }>>('/auth/invitations', ''),
  revokeInvitation: (id: string) => request(`/auth/invitations/${id}`, '', { method: 'DELETE' }),
  login: (email: string, password: string, code = '') => request('/auth/login', '', json({ email, password, code })),
  accountSecurity: () => request<{ mfaEnabled: boolean; recoveryCodesRemaining: number; emailVerified: boolean }>('/auth/security', ''),
  requestVerification: () => request<{ message: string }>('/auth/request-verification', '', json({})),
  verifyEmail: (token: string) => request('/auth/verify-email', '', json({ token })),
  forgotPassword: (email: string) => request<{ message: string }>('/auth/forgot-password', '', json({ email })),
  resetPassword: (token: string, password: string, code: string) => request('/auth/reset-password', '', json({ token, password, code })),
  setupMFA: (password: string) => request<{ secret: string; uri: string }>('/auth/security/mfa/setup', '', json({ password })),
  enableMFA: (code: string) => request<{ recoveryCodes: string[] }>('/auth/security/mfa/enable', '', json({ code })),
  disableMFA: (password: string, code: string) => request('/auth/security/mfa/disable', '', json({ password, code })),
  changePassword: (current_password: string, new_password: string, code: string) => request('/auth/change-password', '', json({ current_password, new_password, code })),
  logoutAll: () => request('/auth/logout-all', '', json({})),
  register: (body: { name: string; email: string; password: string; workspace_name: string; invitation_token: string | null }) => request('/auth/register', '', json(body)),
  logout: () => request('/auth/logout', '', json({})),
  switchWorkspace: (membershipId: string) => request('/auth/switch-workspace', '', json({ membership_id: membershipId })),
  previewInvitation: (token: string) => request<{ workspace: string; email: string; role: string; expiresAt: string }>('/auth/invitations/preview', '', json({ token })),
  acceptInvitation: (token: string) => request('/auth/invitations/accept', '', json({ token })),
  createTicket: (body: { customer_name: string; customer_email: string; subject: string; body: string; team_id: string; channel: string }) => request<TicketDetail['ticket']>('/tickets', '', json(body)),
  renameWorkspace: (userId: string, name: string) => request('/admin/workspace', userId, { method: 'PATCH', body: JSON.stringify({ name }) }),
  createWorkspace: (userId: string, name: string) => request<{ workspaceId: string; workspace: string; adminUserId: string }>('/admin/workspaces', userId, json({ name })),
  report: (userId: string) => request<Report>('/reports/quality', userId),
  knowledge: (userId: string, status?: string, search?: string) => {
    const query = new URLSearchParams(); if (status) query.set('status', status); if (search) query.set('search', search);
    return request<Knowledge[]>(`/knowledge${query.size ? `?${query}` : ''}`, userId);
  },
};

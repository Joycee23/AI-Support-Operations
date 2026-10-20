export type Role = 'admin' | 'manager' | 'agent';
export type User = { id: string; name: string; email: string; role: Role; teamId: string | null };
export type Team = { id: string; name: string; color: string; count?: number };
export type Ticket = {
  id: string; code: string; customer: string; customerEmail: string; subject: string; body: string;
  channel: string; status: string; priority: string; topic: string; teamId: string; team: string;
  teamColor: string; assigneeId: string | null; assignee: string; createdAt: string; updatedAt: string;
};
export type Message = { author: string; body: string; internal: boolean; createdAt: string };
export type TicketDetail = { ticket: Ticket; messages: Message[] };
export type Knowledge = {
  id: string; title: string; category: string; content: string; status: string; processingStatus: string;
  version: number; updatedAt: string; teamId: string | null; createdBy?: string; approvedBy?: string | null;
};
export type KnowledgeVersion = {
  version: number; title: string; category: string; content: string; changedBy: string;
  changeNote: string; createdAt: string;
};
export type AuditEvent = { id: string | number; actor: string; kind: string; detail: string; createdAt: string; ticketCode?: string };
export type Bootstrap = {
  subscription: Subscription; user: User; workspace: string; workspaceId: string; memberships: Array<{ id: string; workspaceId: string; name: string }>; tickets: Ticket[]; teams: Team[]; users: User[];
  knowledge: Knowledge[]; events: AuditEvent[];
  feedback: { accepted: number; edited: number; rejected: number; ungrounded: number };
};
export type Citation = { id: string; chunkId: string; title: string; excerpt: string };
export type AISuggestion = {
  id: string; ticketId: string; topic: string; priority: string; suggestedTeamId: string | null;
  reason: string; draft: string; citations: Citation[]; grounded: boolean; handoffReason: string | null;
};
export type Report = { accepted: number; edited: number; rejected: number; missingKnowledge: number; errors: number; recent: Array<{ id: string; ticketId: string; ticketCode: string; topic: string; grounded: boolean; feedback: string | null; createdAt: string }> };
export type Page = 'overview' | 'inbox' | 'knowledge' | 'teams' | 'reports' | 'audit' | 'settings';

export type Subscription = { status: 'trialing' | 'active' | 'expired'; trialEndsAt: string; accessUntil: string; paidUntil: string | null; canWrite: boolean; monthlyPrice: number; currency: 'VND'; paymentConfigured: boolean };
export type PaymentOrder = { id: string; amount: number; currency: 'VND'; transferCode: string; bank: string; accountNumber: string; accountName: string; status: 'pending' | 'paid' | 'expired'; createdAt: string; expiresAt: string; paidAt: string | null; qrUrl: string | null };

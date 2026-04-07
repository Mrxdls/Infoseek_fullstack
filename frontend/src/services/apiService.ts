/**
 * API service layer — typed wrappers around all backend endpoints.
 */

import api from './api';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  full_name?: string;
  role: 'admin' | 'staff' | 'student';
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Conversation {
  id: string;
  title?: string;
  session_type: 'permanent' | 'temporary';
  summary?: string;
  created_at: string;
  message_count: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface ConversationHistory {
  conversation: Conversation;
  messages: Message[];
}

export interface CitedChunk {
  chunk_id: string;
  source_type: string;        // 'exam' | 'notes'
  subject_name?: string;
  subject_code?: string;
  excerpt: string;
  relevance_score: number;
}

export interface ChatResponse {
  message_id: string;
  conversation_id: string;
  answer: string;
  intent?: string;
  sources: CitedChunk[];
  model_used: string;
  latency_ms: number;
}

export interface Document {
  document_id: string;
  status: string;
  filename: string;
  document_type: string;
  subject_name?: string;
  subject_code?: string;
  page_count?: number;
  chunk_count?: number;
  created_at: string;
  error_message?: string;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const authService = {
  register: (email: string, password: string, fullName?: string) =>
    api.post<User>('/auth/register', { email, password, full_name: fullName }),

  login: async (email: string, password: string): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>('/auth/login', { email, password });
    return data;
  },

  getMe: () => api.get<User>('/auth/me'),

  refreshToken: (refreshToken: string) =>
    api.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken }),
};

// ─── Documents ────────────────────────────────────────────────────────────────

export const documentService = {
  upload: (file: File, documentType: string, subjectName?: string, subjectCode?: string) => {
    const form = new FormData();
    form.append('file', file);
    form.append('document_type', documentType);
    if (subjectName) form.append('subject_name', subjectName);
    if (subjectCode) form.append('subject_code', subjectCode);
    return api.post('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  getStatus: (documentId: string) =>
    api.get<Document>(`/documents/${documentId}/status`),

  list: (page = 1, pageSize = 20, documentType?: string) =>
    api.get('/documents/', { params: { page, page_size: pageSize, document_type: documentType } }),

  delete: (documentId: string) => api.delete(`/documents/${documentId}`),
};

// ─── Chat ─────────────────────────────────────────────────────────────────────

export const chatService = {
  createConversation: (title?: string) =>
    api.post<Conversation>('/chat/conversations', { title, session_type: 'permanent' }),

  listConversations: (page = 1, pageSize = 20) =>
    api.get<Conversation[]>('/chat/conversations', { params: { page, page_size: pageSize } }),

  getHistory: (conversationId: string) =>
    api.get<ConversationHistory>(`/chat/conversations/${conversationId}`),

  sendMessage: (conversationId: string, message: string) =>
    api.post<ChatResponse>('/chat/query', { conversation_id: conversationId, message }),

  streamMessageFetch: async (
    conversationId: string,
    message: string,
    onToken: (token: string) => void,
    onDone: (sources?: CitedChunk[]) => void,
    onError: (err: string) => void
  ) => {
    const token = localStorage.getItem('rag_access_token');
    try {
      const response = await fetch(
        `${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/api/v1/chat/query/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ conversation_id: conversationId, message }),
        }
      );

      if (!response.ok) {
        onError('Failed to start stream');
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) { onError('No response body'); return; }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value);
        const lines = text.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) onToken(data.token);
              if (data.done) onDone(data.sources);
              if (data.error) onError(data.error);
            } catch {}
          }
        }
      }
    } catch (err: any) {
      onError(err?.message || 'Stream connection failed');
    }
  },
};

// ─── Admin ────────────────────────────────────────────────────────────────────

export const adminService = {
  listUsers: (page = 1, pageSize = 50) => api.get<User[]>('/admin/users', { params: { page, page_size: pageSize } }),

  updateRole: (userId: string, role: string) =>
    api.patch<User>(`/admin/users/${userId}/role`, { role }),

  blockUser: (userId: string, isActive: boolean) =>
    api.patch<User>(`/admin/users/${userId}/block`, { is_active: isActive }),

  getUserConversations: (userId: string) =>
    api.get(`/admin/users/${userId}/conversations`),

  getConversation: (conversationId: string) =>
    api.get<ConversationHistory>(`/admin/conversations/${conversationId}`),

  getStats: () => api.get('/admin/stats'),
};

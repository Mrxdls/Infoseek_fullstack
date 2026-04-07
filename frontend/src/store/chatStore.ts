/**
 * Zustand chat store.
 * Manages conversations list, active conversation, messages, and streaming state.
 */

import { create } from 'zustand';
import { chatService, Conversation, Message, CitedChunk } from '../services/apiService';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  sources?: CitedChunk[];
  isStreaming?: boolean;
}

interface ChatState {
  conversations: Conversation[];
  activeConversationId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  isSending: boolean;
  isStreaming: boolean;
  error: string | null;

  loadConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  createConversation: (title?: string) => Promise<string>;
  sendMessage: (message: string, stream?: boolean) => Promise<void>;
  appendStreamToken: (token: string) => void;
  finalizeStream: (sources?: CitedChunk[]) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  messages: [],
  isLoading: false,
  isSending: false,
  isStreaming: false,
  error: null,

  loadConversations: async () => {
    set({ isLoading: true });
    try {
      const { data } = await chatService.listConversations();
      set({ conversations: Array.isArray(data) ? data : [] });
    } catch (err: any) {
      set({ error: 'Failed to load conversations' });
    } finally {
      set({ isLoading: false });
    }
  },

  selectConversation: async (id) => {
    set({ isLoading: true, activeConversationId: id, messages: [] });
    try {
      const { data } = await chatService.getHistory(id);
      const messages: ChatMessage[] = data.messages.map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        created_at: m.created_at,
      }));
      set({ messages });
    } catch {
      set({ error: 'Failed to load conversation history' });
    } finally {
      set({ isLoading: false });
    }
  },

  createConversation: async (title) => {
    const { data } = await chatService.createConversation(title);
    set((state) => ({
      conversations: [data, ...state.conversations],
      activeConversationId: data.id,
      messages: [],
    }));
    return data.id;
  },

  sendMessage: async (message, stream = false) => {
    const { activeConversationId } = get();
    if (!activeConversationId) return;

    // Optimistically add user message
    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
    };
    set((state) => ({
      messages: [...state.messages, tempUserMsg],
      isSending: true,
      error: null,
    }));

    if (stream) {
      // Add placeholder streaming message
      const streamingMsg: ChatMessage = {
        id: `streaming-${Date.now()}`,
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        isStreaming: true,
      };
      set((state) => ({
        messages: [...state.messages, streamingMsg],
        isStreaming: true,
      }));

      await chatService.streamMessageFetch(
        activeConversationId,
        message,
        (token) => get().appendStreamToken(token),
        (sources) => get().finalizeStream(sources),
        (err) => {
          set({ error: err, isStreaming: false, isSending: false });
        }
      );
    } else {
      try {
        const { data } = await chatService.sendMessage(activeConversationId, message);
        const assistantMsg: ChatMessage = {
          id: data.message_id,
          role: 'assistant',
          content: data.answer,
          created_at: new Date().toISOString(),
          sources: data.sources,
        };
        set((state) => ({ messages: [...state.messages, assistantMsg] }));
      } catch (err: any) {
        const detail = err?.response?.data?.detail || 'Failed to get response';
        set({ error: detail });
      } finally {
        set({ isSending: false });
      }
    }
  },

  appendStreamToken: (token) => {
    set((state) => ({
      messages: state.messages.map((m, i) =>
        i === state.messages.length - 1 && m.isStreaming
          ? { ...m, content: m.content + token }
          : m
      ),
    }));
  },

  finalizeStream: (sources?: CitedChunk[]) => {
    set((state) => ({
      messages: state.messages.map((m) =>
        m.isStreaming ? { ...m, isStreaming: false, sources } : m
      ),
      isStreaming: false,
      isSending: false,
    }));
  },

  clearMessages: () => set({ messages: [], activeConversationId: null }),
}));

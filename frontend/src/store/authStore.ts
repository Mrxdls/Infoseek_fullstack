/**
 * Zustand global auth store.
 * Manages current user state, login/logout, and token persistence.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authService, User } from '../services/apiService';
import { tokenStorage } from '../services/api';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchMe: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const tokens = await authService.login(email, password);
          tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);
          await get().fetchMe();
          set({ isAuthenticated: true });
        } catch (err: any) {
          const msg = err?.response?.data?.detail || 'Login failed. Please check your credentials.';
          set({ error: msg, isAuthenticated: false });
          throw err;
        } finally {
          set({ isLoading: false });
        }
      },

      logout: () => {
        tokenStorage.clear();
        set({ user: null, isAuthenticated: false, error: null });
      },

      fetchMe: async () => {
        try {
          const { data } = await authService.getMe();
          set({ user: data, isAuthenticated: true });
        } catch {
          set({ user: null, isAuthenticated: false });
          tokenStorage.clear();
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: 'rag-auth',
      partialize: (state) => ({ user: state.user, isAuthenticated: state.isAuthenticated }),
    }
  )
);

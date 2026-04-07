/**
 * Axios API client with:
 * - Automatic JWT injection
 * - Token refresh on 401
 * - Request/response logging in dev
 */

import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';

const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// ─── Token Storage (httpOnly cookies preferred in production) ────────────────

const TOKEN_KEY = 'rag_access_token';
const REFRESH_KEY = 'rag_refresh_token';

export const tokenStorage = {
  getAccess: () => localStorage.getItem(TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  setTokens: (access: string, refresh: string) => {
    localStorage.setItem(TOKEN_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// ─── Axios Instance ───────────────────────────────────────────────────────────

const api: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor — inject access token
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = tokenStorage.getAccess();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor — handle 401 with token refresh
let isRefreshing = false;
let refreshQueue: Array<(token: string) => void> = [];

/**
 * Soft logout — clears tokens + Zustand persisted state, then fires a custom
 * DOM event so App.tsx can react-route to /login WITHOUT a hard reload.
 * This prevents the "choked" redirect loop when stale tokens exist in storage.
 */
function softLogout() {
  tokenStorage.clear();
  localStorage.removeItem('rag-auth');
  window.dispatchEvent(new CustomEvent('auth:logout'));
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !originalRequest._retry) {
      // Never try to refresh on auth endpoints themselves — just let the
      // error propagate so the UI (login form, etc.) can handle it.
      const requestUrl = originalRequest.url || '';
      const isAuthEndpoint = /\/auth\/(login|register|refresh)/.test(requestUrl);
      if (isAuthEndpoint) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // Queue requests while refresh is in progress
        return new Promise((resolve) => {
          refreshQueue.push((token: string) => {
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${token}`;
            }
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const refreshToken = tokenStorage.getRefresh();
        if (!refreshToken) throw new Error('No refresh token');

        const { data } = await axios.post(`${BASE_URL}/api/v1/auth/refresh`, {
          refresh_token: refreshToken,
        });

        tokenStorage.setTokens(data.access_token, data.refresh_token);
        refreshQueue.forEach((cb) => cb(data.access_token));
        refreshQueue = [];

        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        }
        return api(originalRequest);
      } catch {
        softLogout();
        return Promise.reject(error);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default api;

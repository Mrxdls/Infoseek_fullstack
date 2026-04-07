import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ChatPage from './pages/ChatPage';
import AdminPage from './pages/AdminPage';

function AppRoutes() {
  const navigate = useNavigate();
  const { isAuthenticated, fetchMe, logout } = useAuthStore();

  useEffect(() => {
    // Rehydrate user on page reload if token exists
    const token = localStorage.getItem('rag_access_token');
    if (token && !isAuthenticated) {
      fetchMe();
    }
  }, []);

  useEffect(() => {
    // Listen for soft logout events fired by the axios interceptor
    // instead of doing a hard window.location.href reload.
    const handleSoftLogout = () => {
      logout();
      navigate('/login', { replace: true });
    };
    window.addEventListener('auth:logout', handleSoftLogout);
    return () => window.removeEventListener('auth:logout', handleSoftLogout);
  }, [logout, navigate]);

  return (
    <Routes>
      <Route path="/login" element={isAuthenticated ? <Navigate to="/chat" replace /> : <LoginPage />} />
      <Route path="/register" element={isAuthenticated ? <Navigate to="/chat" replace /> : <RegisterPage />} />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute requiredRole="admin">
            <AdminPage />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to={isAuthenticated ? '/chat' : '/login'} replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

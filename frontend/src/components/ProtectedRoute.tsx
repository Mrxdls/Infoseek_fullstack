import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

interface Props {
  children: React.ReactNode;
  requiredRole?: 'admin' | 'staff' | 'student';
}

export default function ProtectedRoute({ children, requiredRole }: Props) {
  const { isAuthenticated, user } = useAuthStore();

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRole === 'admin' && !['admin', 'staff'].includes(user.role)) {
    return <Navigate to="/chat" replace />;
  }

  if (requiredRole === 'staff' && !['admin', 'staff'].includes(user.role)) {
    return <Navigate to="/chat" replace />;
  }

  return <>{children}</>;
}

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, FileText, MessageSquare, BarChart2,
  ShieldCheck, BookOpen, LogOut, ArrowLeft,
  Ban, CheckCircle, ChevronDown
} from 'lucide-react';
import { adminService, User } from '../services/apiService';
import { useAuthStore } from '../store/authStore';

// ─── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, color }: any) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-3 ${color}`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="text-2xl font-bold text-white">{value ?? '—'}</p>
      <p className="text-slate-400 text-sm mt-0.5">{label}</p>
    </div>
  );
}

// ─── User Row ─────────────────────────────────────────────────────────────────

function UserRow({ user, currentUser, onUpdate }: { user: User; currentUser: User; onUpdate: () => void }) {
  const [loading, setLoading] = useState(false);
  const isSelf = user.id === currentUser.id;

  const ROLES = ['student', 'staff', 'admin'];

  const handleRoleChange = async (role: string) => {
    if (isSelf) return;
    setLoading(true);
    try { await adminService.updateRole(user.id, role); onUpdate(); }
    catch { alert('Failed to update role'); }
    finally { setLoading(false); }
  };

  const handleBlock = async () => {
    if (isSelf) return;
    setLoading(true);
    try { await adminService.blockUser(user.id, !user.is_active); onUpdate(); }
    catch { alert('Failed to update user'); }
    finally { setLoading(false); }
  };

  return (
    <tr className="border-b border-slate-700/50 hover:bg-slate-700/20 transition-colors">
      <td className="px-4 py-3">
        <div>
          <p className="text-sm font-medium text-white">{user.full_name || '—'}</p>
          <p className="text-xs text-slate-400">{user.email}</p>
        </div>
      </td>
      <td className="px-4 py-3">
        {isSelf ? (
          <span className="text-xs text-slate-500 capitalize">{user.role}</span>
        ) : (
          <div className="relative inline-block">
            <select
              value={user.role}
              onChange={(e) => handleRoleChange(e.target.value)}
              disabled={loading}
              className="text-xs bg-slate-700 border border-slate-600 text-white rounded-lg px-2 py-1 pr-6 appearance-none focus:outline-none focus:ring-1 focus:ring-indigo-500 cursor-pointer"
            >
              {ROLES.map(r => <option key={r} value={r} className="capitalize">{r}</option>)}
            </select>
            <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" />
          </div>
        )}
      </td>
      <td className="px-4 py-3">
        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${
          user.is_active
            ? 'bg-green-500/10 text-green-400 border border-green-500/30'
            : 'bg-red-500/10 text-red-400 border border-red-500/30'
        }`}>
          {user.is_active ? <CheckCircle className="w-3 h-3" /> : <Ban className="w-3 h-3" />}
          {user.is_active ? 'Active' : 'Blocked'}
        </span>
      </td>
      <td className="px-4 py-3 text-xs text-slate-400">
        {new Date(user.created_at).toLocaleDateString()}
      </td>
      <td className="px-4 py-3">
        {!isSelf && (
          <button
            onClick={handleBlock}
            disabled={loading}
            className={`text-xs px-3 py-1 rounded-lg border transition-colors ${
              user.is_active
                ? 'border-red-500/30 text-red-400 hover:bg-red-500/10'
                : 'border-green-500/30 text-green-400 hover:bg-green-500/10'
            }`}
          >
            {user.is_active ? 'Block' : 'Unblock'}
          </button>
        )}
      </td>
    </tr>
  );
}

// ─── Admin Page ───────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [tab, setTab] = useState<'overview' | 'users'>('overview');

  const fetchStats = async () => {
    try {
      const { data } = await adminService.getStats();
      setStats(data);
    } catch {}
  };

  const fetchUsers = async () => {
    try {
      const { data } = await adminService.listUsers();
      setUsers(Array.isArray(data) ? data : []);
    } catch {}
  };

  useEffect(() => {
    fetchStats();
    fetchUsers();
  }, []);

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center gap-4">
        <div className="flex items-center gap-2.5 flex-1">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <BookOpen className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold">StudyRAG</span>
          <span className="text-slate-500 text-sm">/ Admin</span>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/chat')} className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors">
            <ArrowLeft className="w-4 h-4" /> Back to Chat
          </button>
          <button onClick={logout} className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors">
            <LogOut className="w-4 h-4" /> Logout
          </button>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Tab Nav */}
        <div className="flex gap-1 bg-slate-800 border border-slate-700 rounded-xl p-1 mb-8 w-fit">
          {(['overview', 'users'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
                tab === t ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === 'overview' && (
          <>
            <h2 className="text-xl font-bold text-white mb-6">System Overview</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard icon={Users} label="Total Users" value={stats?.total_users} color="bg-indigo-600" />
              <StatCard icon={FileText} label="Documents" value={stats?.total_documents} color="bg-emerald-600" />
              <StatCard icon={MessageSquare} label="Conversations" value={stats?.total_conversations} color="bg-violet-600" />
              <StatCard icon={BarChart2} label="Messages" value={stats?.total_messages} color="bg-amber-600" />
            </div>
          </>
        )}

        {tab === 'users' && (
          <>
            <h2 className="text-xl font-bold text-white mb-6">User Management</h2>
            <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700 bg-slate-700/30">
                    {['User', 'Role', 'Status', 'Joined', 'Actions'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <UserRow key={u.id} user={u} currentUser={user!} onUpdate={fetchUsers} />
                  ))}
                </tbody>
              </table>
              {users.length === 0 && (
                <div className="text-center py-12 text-slate-500 text-sm">No users found.</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

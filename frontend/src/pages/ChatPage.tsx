import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Send, Plus, BookOpen, LogOut, Upload, ChevronRight, Loader2, User, Bot, FileText, ShieldCheck } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import { useChatStore } from '../store/chatStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatDistanceToNow } from 'date-fns';

// ─── Source Citation Card ─────────────────────────────────────────────────────

function SourceCard({ source }: { source: any }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="text-xs bg-slate-700/50 border border-slate-600/50 rounded-lg p-2.5 mt-1">
      <button
        className="flex items-center gap-2 w-full text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <FileText className="w-3 h-3 text-indigo-400 shrink-0" />
        <span className="text-slate-300 font-medium truncate flex-1">
          {source.subject_name
            ? `${source.subject_name}${source.subject_code ? ` (${source.subject_code})` : ''}`
            : source.source_type === 'exam' ? 'Exam Paper' : 'Lecture Notes'}
        </span>
        <span className="text-slate-500 shrink-0">
          {Math.round(source.relevance_score * 100)}%
        </span>
        <ChevronRight className={`w-3 h-3 text-slate-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
      </button>
      {expanded && (
        <p className="mt-2 text-slate-400 leading-relaxed border-t border-slate-600/50 pt-2">
          {source.excerpt}
        </p>
      )}
    </div>
  );
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: any }) {
  const isUser = message.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${isUser ? 'bg-indigo-600' : 'bg-slate-600'}`}>
        {isUser ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-white" />}
      </div>
      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-indigo-600 text-white rounded-tr-sm'
            : 'bg-slate-700 text-slate-100 rounded-tl-sm'
        }`}>
          {isUser ? (
            <p>{message.content}</p>
          ) : (
            <div className="prose prose-sm prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {message.isStreaming && (
                <span className="inline-block w-2 h-4 bg-indigo-400 animate-pulse ml-1 rounded-sm" />
              )}
            </div>
          )}
        </div>
        {message.sources?.length > 0 && (
          <div className="w-full space-y-1">
            <p className="text-xs text-slate-500 px-1">Sources used:</p>
            {message.sources.map((s: any) => <SourceCard key={s.chunk_id} source={s} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

function Sidebar({ onUpload }: { onUpload: () => void }) {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { conversations, activeConversationId, selectConversation, createConversation, loadConversations } = useChatStore();

  useEffect(() => { loadConversations(); }, []);

  const handleNew = async () => {
    await createConversation('New Conversation');
  };

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-700/50 flex flex-col h-full">
      {/* Brand */}
      <div className="p-4 border-b border-slate-700/50">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <BookOpen className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-white text-sm">StudyRAG</span>
        </div>
      </div>

      {/* Actions */}
      <div className="p-3 space-y-1.5">
        <button
          onClick={handleNew}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New Chat
        </button>
        {user?.role !== 'student' && (
          <>
            <button
              onClick={onUpload}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded-lg transition-colors"
            >
              <Upload className="w-4 h-4" /> Upload Document
            </button>
            <button
              onClick={() => navigate('/admin')}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded-lg transition-colors"
            >
              <ShieldCheck className="w-4 h-4" /> Admin Panel
            </button>
          </>
        )}
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto p-2">
        <p className="text-xs font-medium text-slate-500 px-2 mb-2 uppercase tracking-wider">Conversations</p>
        {conversations.map((conv) => (
          <button
            key={conv.id}
            onClick={() => selectConversation(conv.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors mb-0.5 ${
              activeConversationId === conv.id
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-600/30'
                : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
            }`}
          >
            <p className="truncate font-medium">{conv.title || 'Untitled'}</p>
            <p className="text-xs text-slate-500 mt-0.5">
              {formatDistanceToNow(new Date(conv.created_at), { addSuffix: true })}
            </p>
          </button>
        ))}
      </div>

      {/* User footer */}
      <div className="p-3 border-t border-slate-700/50">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-slate-600 flex items-center justify-center">
            <User className="w-3.5 h-3.5 text-slate-300" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-white truncate">{user?.full_name || user?.email}</p>
            <p className="text-xs text-slate-500 capitalize">{user?.role}</p>
          </div>
          <button
            onClick={logout}
            className="text-slate-400 hover:text-white transition-colors"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

// ─── Upload Modal ─────────────────────────────────────────────────────────────

function UploadModal({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState('notes');
  const [subjectName, setSubjectName] = useState('');
  const [subjectCode, setSubjectCode] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  const handleUpload = async () => {
    if (!file) return;
    setIsUploading(true);
    setError('');
    try {
      const { documentService } = await import('../services/apiService');
      await documentService.upload(file, docType, subjectName || undefined, subjectCode || undefined);
      setSuccess(true);
      setTimeout(onClose, 1500);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((e: any) => e.msg || JSON.stringify(e)).join('; '));
      } else if (typeof detail === 'string') {
        setError(detail);
      } else {
        setError('Upload failed. Please try again.');
      }
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <h2 className="text-lg font-semibold text-white mb-4">Upload Document</h2>

        {success ? (
          <div className="text-center py-4">
            <div className="text-green-400 text-lg mb-2">✓ Uploaded successfully!</div>
            <p className="text-slate-400 text-sm">Processing queued in background.</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-slate-300 mb-1.5">Document</label>
              <input
                type="file"
                accept=".pdf,.docx,.txt,.md"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-indigo-600 file:text-white file:text-sm hover:file:bg-indigo-500 cursor-pointer"
              />
            </div>

            <div>
              <label className="block text-sm text-slate-300 mb-1.5">Document Type</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="notes">Lecture Notes</option>
                <option value="university_exam">University Exam Paper</option>
                <option value="syllabus">Syllabus</option>
                <option value="mid_term_exam" disabled>Mid-Term Exam (coming soon)</option>
              </select>
            </div>

            {docType === 'syllabus' && (
              <div className="text-xs text-slate-400 bg-slate-700/40 border border-slate-600/40 rounded-lg p-3">
                Subject details are extracted automatically from the syllabus PDF.
                Multiple subjects per file are supported.
              </div>
            )}

            {(docType === 'university_exam' || docType === 'mid_term_exam') && (
              <>
                <div>
                  <label className="block text-sm text-slate-300 mb-1.5">Subject Name</label>
                  <input
                    type="text"
                    value={subjectName}
                    onChange={(e) => setSubjectName(e.target.value)}
                    placeholder="e.g. Database Management Systems"
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-slate-300 mb-1.5">Subject Code</label>
                  <input
                    type="text"
                    value={subjectCode}
                    onChange={(e) => setSubjectCode(e.target.value)}
                    placeholder="e.g. CS301"
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </>
            )}

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <div className="flex gap-3 pt-2">
              <button onClick={onClose} className="flex-1 py-2 text-sm text-slate-400 hover:text-white border border-slate-600 rounded-lg transition-colors">Cancel</button>
              <button
                onClick={handleUpload}
                disabled={!file || isUploading}
                className="flex-1 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-white rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {isUploading ? <><Loader2 className="w-4 h-4 animate-spin" /> Uploading...</> : 'Upload'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Chat Page ───────────────────────────────────────────────────────────

export default function ChatPage() {
  const { messages, isSending, isStreaming, sendMessage, activeConversationId, createConversation } = useChatStore();
  const [input, setInput] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [useStream, setUseStream] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || isSending || isStreaming) return;
    setInput('');

    let convId = activeConversationId;
    if (!convId) {
      convId = await createConversation(msg.slice(0, 50));
    }

    await sendMessage(msg, useStream);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen bg-slate-900 text-white overflow-hidden">
      <Sidebar onUpload={() => setShowUpload(true)} />

      {/* Chat area */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <div className="w-16 h-16 bg-indigo-600/20 rounded-2xl flex items-center justify-center mb-4">
                <Bot className="w-8 h-8 text-indigo-400" />
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">Ask anything about your documents</h2>
              <p className="text-slate-400 text-sm max-w-sm">
                Your study assistant has access to all uploaded materials. Ask questions, request summaries, or explore exam topics.
              </p>
            </div>
          ) : (
            messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-slate-700/50 p-4">
          <div className="max-w-4xl mx-auto">
            <div className="flex items-end gap-3 bg-slate-800 border border-slate-700 rounded-2xl px-4 py-3 focus-within:border-indigo-500 transition-colors">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question about your study materials..."
                rows={1}
                className="flex-1 bg-transparent text-white placeholder-slate-500 text-sm resize-none focus:outline-none max-h-32 leading-relaxed"
                style={{ minHeight: '24px' }}
              />
              <div className="flex items-center gap-2 shrink-0">
                <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={useStream}
                    onChange={(e) => setUseStream(e.target.checked)}
                    className="w-3 h-3 accent-indigo-600"
                  />
                  Stream
                </label>
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isSending || isStreaming}
                  className="w-8 h-8 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 rounded-xl flex items-center justify-center transition-colors"
                >
                  {isSending || isStreaming
                    ? <Loader2 className="w-4 h-4 text-white animate-spin" />
                    : <Send className="w-4 h-4 text-white" />
                  }
                </button>
              </div>
            </div>
            <p className="text-xs text-slate-600 text-center mt-2">
              Answers are grounded in uploaded documents only.
            </p>
          </div>
        </div>
      </main>

      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}
    </div>
  );
}

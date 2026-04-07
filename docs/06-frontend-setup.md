# 06 — Frontend Setup

The frontend is a React + TypeScript single-page application styled with Tailwind CSS.

---

## 1. Navigate to Frontend Directory

```bash
cd /path/to/rag-app/frontend
```

---

## 2. Install Dependencies

```bash
npm install
```

This downloads ~1,500 packages into `node_modules/`. It takes 1–3 minutes the first time. Never commit `node_modules/` to git.

Key dependencies:

| Package | Purpose |
|---------|---------|
| `react` + `react-dom` | Core UI library |
| `react-router-dom` | Client-side routing (navigate between pages without full reload) |
| `zustand` | Global state management — simpler than Redux |
| `axios` | HTTP client for API calls |
| `react-markdown` + `remark-gfm` | Renders the AI's markdown-formatted responses |
| `lucide-react` | Icon library |
| `date-fns` | Formats dates like "5 minutes ago" |
| `tailwindcss` | Utility CSS classes |

---

## 3. Environment Variables (Optional)

By default the frontend expects the backend at `http://localhost:8000`. If your backend runs elsewhere, create a `.env` file in the `frontend/` directory:

```env
REACT_APP_API_URL=http://localhost:8000
```

React's build system automatically prefixes env vars with `REACT_APP_`. This is referenced in `src/services/apiService.ts`:
```typescript
`${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/api/v1/...`
```

---

## 4. Start the Development Server

```bash
npm start
```

This starts a development server on [http://localhost:3000](http://localhost:3000). It:
- Automatically reloads when you save a file
- Shows compilation errors in the browser
- Proxies API requests through CORS

You should see:
```
Compiled successfully!
You can now view rag-frontend in the browser.
  Local:            http://localhost:3000
```

Open [http://localhost:3000](http://localhost:3000) — you'll see the login page.

---

## 5. Application Pages

### Login Page (`/login`)
Email + password form. On success, stores JWT tokens in `localStorage` under `rag_access_token` and `rag_refresh_token`.

### Register Page (`/register`)
Creates a new student account. All new registrations default to the `student` role.

### Chat Page (`/chat`)
The main page. Three sections:
- **Left sidebar** — conversation list, New Chat button, Upload button (admin/staff only), Admin Panel link
- **Message area** — chat bubbles with markdown rendering; sources shown below assistant messages
- **Input area** — textarea (Enter to send, Shift+Enter for newline), Stream toggle, Send button

### Admin Page (`/admin`)
Two tabs:
- **Overview** — system stats (user count, document count, conversation count, message count)
- **Users** — table of all users with inline role change and block/unblock

---

## 6. Frontend Architecture

```
src/
├── App.tsx                   # Root — sets up BrowserRouter + routes
├── index.tsx                 # React DOM root render
├── index.css                 # Tailwind base imports
├── components/
│   └── ProtectedRoute.tsx    # Redirects unauthenticated users to /login
├── pages/
│   ├── LoginPage.tsx         # Login form
│   ├── RegisterPage.tsx      # Registration form
│   ├── ChatPage.tsx          # Main chat UI + upload modal
│   └── AdminPage.tsx         # Admin dashboard
├── store/
│   ├── authStore.ts          # Zustand: user, login, logout, fetchMe
│   └── chatStore.ts          # Zustand: conversations, messages, streaming
└── services/
    ├── api.ts                # Axios instance with auth interceptors
    └── apiService.ts         # Typed functions for every API endpoint
```

### How Authentication Works in the Frontend

1. User submits login form → `authStore.login()` → calls `/api/v1/auth/login`
2. Tokens are saved to `localStorage`
3. `api.ts` (Axios) has a **request interceptor** that adds `Authorization: Bearer <token>` to every request
4. `api.ts` also has a **response interceptor** that catches 401 errors and tries to refresh the token automatically
5. `ProtectedRoute` component checks `authStore.isAuthenticated` — redirects to `/login` if false

### How Streaming Works

When the user enables the "Stream" checkbox:
1. `chatStore.sendMessage()` calls `chatService.streamMessageFetch()`
2. This uses the browser's native `fetch` API (not Axios) to connect to `/api/v1/chat/query/stream`
3. The response is a Server-Sent Events (SSE) stream
4. Each line starting with `data: ` contains a JSON object: `{"token": "hello"}` or `{"done": true}`
5. Tokens are appended to the streaming message in real-time via `chatStore.appendStreamToken()`
6. When `done: true` arrives, `chatStore.finalizeStream()` removes the streaming indicator

---

## 7. Build for Production

```bash
npm run build
```

Creates an optimized static build in `frontend/build/`. These files can be served by any static file server (nginx, GitHub Pages, Firebase Hosting, etc.).

---

## 8. Tailwind CSS

The project uses Tailwind's utility class approach. There is no separate CSS file per component. Styling is done with class names in JSX like:

```tsx
<div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
```

The dark theme uses the `slate` color palette throughout.

> **Learn more:** [Tailwind CSS Docs](https://tailwindcss.com/docs)

---

## 9. Common Issues

**"Module not found" after `npm install`:**
```bash
rm -rf node_modules package-lock.json
npm install
```

**"CORS error" when calling the backend:**
Make sure the backend `.env` has:
```
CORS_ORIGINS=["http://localhost:3000"]
```

**Blank page after login:**
Open browser DevTools (F12) → Console. Usually a JavaScript error. Most commonly an API response shape mismatch.

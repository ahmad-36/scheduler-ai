# Scheduler AI

Intelligent personal scheduling assistant with Google Calendar, AI reasoning (Claude), web search, and persistent memory.

## Features
- **AI Chat** — Claude-powered assistant that reasons about your schedule
- **Google Calendar** — read and create events from the chat
- **Web Search** — transit times, business hours, local info (via Tavily)
- **Memory** — remembers your location, work hours, preferences, patterns across sessions
- **Encrypted storage** — all secrets and memory encrypted per-user passcode in Supabase

## Setup

### 1. Supabase tables

Run this SQL in your Supabase project (SQL editor):

```sql
create table users (
  id uuid default gen_random_uuid() primary key,
  username text unique not null,
  passcode_salt text not null
);

create table secrets (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references users(id),
  key text not null,
  ciphertext text not null,
  unique(user_id, key)
);

create table tasks (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references users(id),
  task_json jsonb,
  updated_at timestamptz default now(),
  unique(user_id)
);
```

### 2. Environment variables

Copy `.env.example` to `.env` and fill in:

```
APP_SECRET=          # any random string (used for encryption)
BASE_URL=            # e.g. https://your-app.onrender.com or http://localhost:8000
SUPABASE_URL=        # from Supabase project settings
SUPABASE_SERVICE_ROLE_KEY=   # from Supabase project settings > API

ANTHROPIC_API_KEY=   # from console.anthropic.com
TAVILY_API_KEY=      # optional, from app.tavily.com (1000 free searches/month)
TZ=Europe/London     # your timezone

GOOGLE_CLIENT_SECRET_FILE=client_secret.json
```

**Alternative**: API keys can also be set per-user via the UI (⚠ Set API key button), stored encrypted in Supabase.

### 3. Google Calendar OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → APIs & Services → Enable **Google Calendar API**
3. OAuth consent screen → External → add your email as test user
4. Credentials → Create OAuth 2.0 Client ID → Web application
5. Add Authorized redirect URI: `{BASE_URL}/oauth2/callback`
6. Download JSON → save as `client_secret.json` in project root

### 4. Run locally

```bash
python -m venv scheduler
source scheduler/bin/activate      # Windows: scheduler\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://localhost:8000

## Deploy for free on Render.com

1. Push to GitHub
2. New Web Service → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add environment variables in Render dashboard
6. Add `client_secret.json` contents as a secret file or env var

Note: Free Render instances spin down after inactivity (30s cold start). In-memory sessions reset on restart — Supabase data (memory, calendar tokens) persists.

## How memory works

The AI automatically saves things you tell it — your location, work schedule, commute route, preferences, goals. These are stored encrypted in Supabase and recalled in future sessions. You never have to repeat yourself.

To see what's stored, ask: *"What do you remember about me?"*
To update something: *"My work location has changed to..."*

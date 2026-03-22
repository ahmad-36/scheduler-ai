import json
import secrets

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.config import APP_SECRET, BASE_URL, TZ, GOOGLE_CLIENT_SECRET_FILE, TAVILY_API_KEY, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from store.crypto import encrypt, decrypt
from store.supabase_store import (
    get_or_create_user, set_secret, get_secret_cipher,
    set_tasks, get_tasks,
)
from integrations.google_calendar import (
    make_flow, authorization_url, exchange_code,
    service_from_token_dict, list_events, create_event,
)
from integrations.claude_agent import SchedulerAgent
from integrations.search import search_web

app = FastAPI()
templates = Jinja2Templates(directory="templates")

SESSION_COOKIE = "sched_session"
sessions: dict = {}  # in-memory; real data lives in Supabase


# ── Session helpers ────────────────────────────────────────────────────────────

def current_user(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    return sessions.get(sid) if sid else None


def store_user_secret(u: dict, key: str, value: str):
    ct = encrypt(u["passcode"], u["user_salt"], APP_SECRET, value)
    set_secret(u["user"]["id"], key, ct)


def load_user_secret(u: dict, key: str):
    ct = get_secret_cipher(u["user"]["id"], key)
    if not ct:
        return None
    return decrypt(u["passcode"], u["user_salt"], APP_SECRET, ct)


def get_calendar_service(u: dict):
    tok_str = load_user_secret(u, "GOOGLE_OAUTH_TOKEN")
    if not tok_str:
        return None
    try:
        return service_from_token_dict(json.loads(tok_str))
    except Exception:
        return None


def get_llm_key(u: dict) -> str:
    """Env var takes precedence; fall back to user-stored key."""
    if LLM_API_KEY:
        return LLM_API_KEY
    return load_user_secret(u, "LLM_API_KEY") or ""


def get_tavily_key(u: dict) -> str:
    if TAVILY_API_KEY:
        return TAVILY_API_KEY
    return load_user_secret(u, "TAVILY_API_KEY") or ""


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = current_user(request)
    return RedirectResponse("/dash" if u else "/login", 302)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), passcode: str = Form(...)):
    try:
        user = get_or_create_user(username)
    except Exception as e:
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Login failed: {e}"})

    user_salt = bytes.fromhex(user["passcode_salt"]) if isinstance(user["passcode_salt"], str) else user["passcode_salt"]
    sid = secrets.token_urlsafe(24)
    sessions[sid] = {
        "user": user,
        "passcode": passcode,
        "user_salt": user_salt,
        "oauth_state": None,
        "chat_history": [],
    }
    resp = RedirectResponse("/dash", 302)
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid in sessions:
        del sessions[sid]
    resp = RedirectResponse("/login", 302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/dash", response_class=HTMLResponse)
def dash(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", 302)

    has_google = load_user_secret(u, "GOOGLE_OAUTH_TOKEN") is not None
    has_anthropic = bool(get_llm_key(u))

    return templates.TemplateResponse("dash.html", {
        "request": request,
        "username": u["user"]["username"],
        "has_google": has_google,
        "has_anthropic": has_anthropic,
    })


# ── Secrets storage ────────────────────────────────────────────────────────────

@app.post("/secrets/set")
def secrets_set(request: Request, keyname: str = Form(...), value: str = Form(...)):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", 302)
    store_user_secret(u, keyname, value)
    return RedirectResponse("/dash", 302)


# ── Google OAuth ───────────────────────────────────────────────────────────────

@app.get("/oauth2/start")
def oauth2_start(request: Request):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", 302)
    flow = make_flow(GOOGLE_CLIENT_SECRET_FILE, BASE_URL)
    url, state = authorization_url(flow)
    u["oauth_state"] = state
    return RedirectResponse(url, 302)


@app.get("/oauth2/callback")
def oauth2_callback(request: Request, code: str, state: str | None = None):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", 302)
    if u.get("oauth_state") and state and state != u["oauth_state"]:
        return HTMLResponse("OAuth state mismatch. Please try again.")
    flow = make_flow(GOOGLE_CLIENT_SECRET_FILE, BASE_URL, state=state)
    tok = exchange_code(flow, code)
    store_user_secret(u, "GOOGLE_OAUTH_TOKEN", json.dumps(tok))
    return RedirectResponse("/dash", 302)


# ── Calendar API ───────────────────────────────────────────────────────────────

@app.get("/api/calendar/events")
def api_calendar_events(request: Request, days: int = 7):
    u = current_user(request)
    if not u:
        return JSONResponse({"error": "Not logged in"}, 401)
    service = get_calendar_service(u)
    if not service:
        return JSONResponse({"error": "Google Calendar not connected"})
    try:
        events = list_events(service, days_ahead=min(days, 30))
        return JSONResponse({"events": events})
    except Exception as e:
        return JSONResponse({"error": str(e)})


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat(request: Request, body: ChatRequest):
    u = current_user(request)
    if not u:
        return JSONResponse({"reply": "Session expired. Please log in again.", "calendar_updated": False})

    llm_key = get_llm_key(u)
    if not llm_key:
        return JSONResponse({
            "reply": "**API key missing.** Please set your Groq API key via the '⚠ Set API key' button in the header.",
            "calendar_updated": False,
        })

    tavily_key = get_tavily_key(u)

    def memory_getter(key: str):
        return load_user_secret(u, key)

    def memory_setter(key: str, value: str):
        store_user_secret(u, key, value)

    agent = SchedulerAgent(
        api_key=llm_key,
        tz_name=TZ,
        memory_getter=memory_getter,
        memory_setter=memory_setter,
        calendar_service=get_calendar_service(u),
        search_fn=(lambda q: search_web(q)) if tavily_key else None,
        base_url=LLM_BASE_URL or None,
        model=LLM_MODEL or None,
    )

    history = u.get("chat_history", [])
    try:
        reply, new_history, cal_updated = agent.chat(history, body.message)
    except Exception as e:
        return JSONResponse({"reply": f"Error: {e}", "calendar_updated": False})

    # Keep last 30 messages in session (15 turns)
    u["chat_history"] = new_history[-30:]

    return JSONResponse({"reply": reply, "calendar_updated": cal_updated})


# ── Legacy task endpoints (kept for compatibility) ─────────────────────────────

@app.post("/tasks/set")
def tasks_set(request: Request, tasks_json: str = Form(...)):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login", 302)
    try:
        tasks = json.loads(tasks_json)
        assert isinstance(tasks, list)
    except Exception:
        return HTMLResponse("Invalid JSON — must be a list.")
    set_tasks(u["user"]["id"], tasks)
    return RedirectResponse("/dash", 302)

import os
import datetime
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def make_flow(client_secret_file: str, base_url: str, state: str | None = None) -> Flow:
    import json
    # Prefer env var (for cloud hosting) over file
    secret_json = os.getenv("GOOGLE_CLIENT_SECRET_JSON", "")
    if secret_json:
        config = json.loads(secret_json)
        flow = Flow.from_client_config(config, scopes=SCOPES, state=state)
    elif os.path.exists(client_secret_file):
        flow = Flow.from_client_secrets_file(client_secret_file, scopes=SCOPES, state=state)
    else:
        raise FileNotFoundError("Google client secret not found. Set GOOGLE_CLIENT_SECRET_JSON env var or provide client_secret.json.")
    flow.redirect_uri = f"{base_url}/oauth2/callback"
    return flow

def authorization_url(flow: Flow) -> tuple[str, str]:
    url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    return url, state

def exchange_code(flow: Flow, code: str) -> dict:
    flow.fetch_token(code=code)
    c = flow.credentials
    return {
        "token": c.token,
        "refresh_token": c.refresh_token,
        "token_uri": c.token_uri,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "scopes": list(c.scopes) if c.scopes else [],
    }

def service_from_token_dict(tok: dict):
    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri"),
        client_id=tok.get("client_id"),
        client_secret=tok.get("client_secret"),
        scopes=tok.get("scopes"),
    )
    return build("calendar", "v3", credentials=creds)

def list_events(service, max_results: int = 15, days_ahead: int = 7) -> list[dict]:
    now = datetime.datetime.utcnow().isoformat() + "Z"
    until = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"
    result = service.events().list(
        calendarId="primary",
        timeMin=now,
        timeMax=until,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [
        {
            "id": e.get("id"),
            "summary": e.get("summary", "(No title)"),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
            "description": e.get("description", ""),
            "location": e.get("location", ""),
        }
        for e in result.get("items", [])
    ]

def create_event(service, summary: str, start_iso: str, end_iso: str, description: str = "", location: str = ""):
    ev = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if location:
        ev["location"] = location
    return service.events().insert(calendarId="primary", body=ev).execute()

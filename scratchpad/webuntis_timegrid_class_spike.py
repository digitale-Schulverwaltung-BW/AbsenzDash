import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

SERVER = os.environ.get("WEBUNTIS_SERVER")
SCHOOL = os.environ.get("WEBUNTIS_SCHOOL")
USERNAME = os.environ.get("WEBUNTIS_USERNAME")
PASSWORD = os.environ.get("WEBUNTIS_PASSWORD")


def rpc_url():
    return f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"


def rpc_call(client, session_id, method, params):
    payload = {"id": method, "method": method, "params": params, "jsonrpc": "2.0"}
    headers = {"Cookie": f"JSESSIONID={session_id}"} if session_id else {}
    resp = client.post(rpc_url(), json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        return None, body["error"]
    return body.get("result"), None


def authenticate(client):
    payload = {
        "id": "auth",
        "method": "authenticate",
        "params": {"user": USERNAME, "password": PASSWORD, "client": "AbsenzDashSpike"},
        "jsonrpc": "2.0",
    }
    resp = client.post(rpc_url(), json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Login fehlgeschlagen: {body['error']}")
    return body["result"]["sessionId"]


with httpx.Client() as client:
    session_id = authenticate(client)
    try:
        schuljahre, _ = rpc_call(client, session_id, "getSchoolyears", {})
        aktuell, _ = rpc_call(client, session_id, "getCurrentSchoolyear", {})
        schoolyear_id = aktuell["id"] if aktuell else max(s["id"] for s in schuljahre)
        klassen, err = rpc_call(client, session_id, "getKlassen", {"schoolyearId": schoolyear_id})
        print("getKlassen error:", err, "count:", len(klassen) if klassen else 0)
        if klassen:
            for k in klassen[:3]:
                kid = k["id"]
                print("\nklasse:", {kk: k.get(kk) for kk in ("id", "name")})
                for elementType in (1, 2):
                    res, e = rpc_call(
                        client, session_id, "getTimegridUnits", {"elementType": elementType, "elementId": kid}
                    )
                    print(f"  getTimegridUnits elementType={elementType} elementId={kid} error={e}")
                    if res:
                        print("  result=", json.dumps(res, ensure_ascii=False, indent=2)[:2000])
    finally:
        rpc_call(client, session_id, "logout", {})

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
        aktuell, aktuell_err = rpc_call(client, session_id, "getCurrentSchoolyear", {})
        print("getCurrentSchoolyear:", aktuell, aktuell_err)
        print("getSchoolyears:", json.dumps(schuljahre, ensure_ascii=False))

        candidate_ids = []
        if aktuell:
            candidate_ids.append(aktuell["id"])
        if schuljahre:
            candidate_ids += [s["id"] for s in schuljahre]

        seen = set()
        for sid in candidate_ids:
            if sid in seen:
                continue
            seen.add(sid)
            for params in (
                {"schoolyearId": sid},
                {"schoolYearId": sid},
            ):
                res, err = rpc_call(client, session_id, "getTimegridUnits", params)
                print(f"\ngetTimegridUnits params={params}")
                print("  error=", err)
                if res:
                    print("  result=", json.dumps(res, ensure_ascii=False, indent=2)[:3000])
    finally:
        rpc_call(client, session_id, "logout", {})

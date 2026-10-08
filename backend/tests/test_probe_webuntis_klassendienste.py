import base64
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.webuntis_client import WebUntisError
from scripts import probe_webuntis_klassendienste as probe


def test_maskiere_kuerzt_namensfelder_auf_zwei_zeichen():
    daten = {"firstName": "Maximilian", "lastName": "Mustermann", "email": "max@example.org", "longName": "Muster"}
    assert probe.maskiere(daten) == {
        "firstName": "Ma…",
        "lastName": "Mu…",
        "email": "ma…",
        "longName": "Mu…",
    }


def test_maskiere_laesst_ids_daten_kuerzel_und_keys_unveraendert():
    daten = {"id": 17, "startDate": 20260801, "datum": "2026-08-01", "klasse": "10a", "role": "Klassensprecher", "studentId": 99}
    assert probe.maskiere(daten) == daten


def test_maskiere_rekursiv_ueber_dict_und_liste_und_mutiert_nicht():
    daten = {"items": [{"id": 1, "student": {"name": "Erika", "id": 5}}, {"teacherName": "Schmidt"}], "teachers": ["Meier"]}
    ergebnis = probe.maskiere(daten)
    assert ergebnis == {
        "items": [{"id": 1, "student": {"name": "Er…", "id": 5}}, {"teacherName": "Sc…"}],
        "teachers": ["Me…"],
    }
    assert daten["items"][0]["student"]["name"] == "Erika"


def test_maskiere_ausnahmen_lassen_bestimmte_keys_lesbar():
    assert probe.maskiere({"name": "10a", "firstName": "Anna"}, ausnahmen={"name"}) == {"name": "10a", "firstName": "An…"}


def test_stichwortsuche_findet_keys_und_werte_case_insensitiv_ohne_wert_preiszugeben():
    daten = {"a": [{"Klassendienst": 1}, {"x": "Der KLASSENSPRECHER"}], "b": {"roleId": 3}, "c": "nichts"}
    treffer = probe.suche_stichworte(daten, "probe")
    assert ("probe.a[0].Klassendienst", "dienst") in treffer
    assert ("probe.a[1].x", "sprecher") in treffer
    assert ("probe.b.roleId", "role") in treffer
    assert all("nichts" not in t[0] for t in treffer)
    assert not any("KLASSENSPRECHER" in t[0] for t in treffer)


def test_stichwortsuche_ohne_treffer():
    assert probe.suche_stichworte({"id": 1, "name": "x"}, "p") == []


def test_kuerze_listen_auf_drei_beispiele_mit_laenge():
    ergebnis = probe.kuerze({"liste": list(range(10)), "kurz": [1, 2], "tief": [{"x": list(range(5))}]})
    assert ergebnis["liste"] == {"_laenge": 10, "_beispiele": [0, 1, 2]}
    assert ergebnis["kurz"] == [1, 2]
    assert ergebnis["tief"] == [{"x": {"_laenge": 5, "_beispiele": [0, 1, 2]}}]


def _client(antworten: dict):
    client = AsyncMock()
    client._session_id = "SESSION"

    async def call(method, params):
        antwort = antworten[method]
        if isinstance(antwort, Exception):
            raise antwort
        return antwort

    client.call.side_effect = call
    return client


SCHULJAHR = {"id": 9, "name": "2026/27", "startDate": 20260801, "endDate": 20270731}


@pytest.mark.asyncio
async def test_sonde_holidays_meldet_abdeckung():
    client = _client(
        {
            "getHolidays": [
                {"id": 1, "name": "Herbst", "longName": "Herbstferien", "startDate": 20261026, "endDate": 20261030},
                {"id": 2, "name": "Weih", "longName": "Weihnachten", "startDate": 20261223, "endDate": 20270108},
            ],
        }
    )
    sonde = await probe.sonde_holidays(client, SCHULJAHR)
    assert sonde.ok
    text = "\n".join(sonde.zeilen)
    assert "2" in text and "20261026" in text and "20270108" in text
    assert "abgedeckt: ja" in text


@pytest.mark.asyncio
async def test_sonde_holidays_leer_ist_fehlschlag():
    sonde = await probe.sonde_holidays(_client({"getHolidays": []}), SCHULJAHR)
    assert not sonde.ok


@pytest.mark.asyncio
async def test_sonde_klassen_zeigt_keys_und_dienst_indizien():
    client = _client({"getKlassen": [{"id": 1, "name": "10a", "longName": "Zehn", "klassensprecher": 5}]})
    sonde = await probe.sonde_klassen(client, SCHULJAHR)
    assert sonde.ok
    assert any("klassensprecher" in fundort for fundort, _ in sonde.treffer)
    assert "10a" in "\n".join(sonde.zeilen)


@pytest.mark.asyncio
async def test_sonde_rpc_kandidaten_faengt_fehler_pro_methode_ab():
    client = _client(
        {
            "getClassregCategories": WebUntisError("Method not found"),
            "getClassregCategoryGroups": [{"id": 1, "name": "Attest"}],
            "getRemarkCategories": [],
            "getStatusData": {"lstypes": [{"id": 1}], "codes": []},
        }
    )
    sonden = await probe.sonde_rpc_kandidaten(client)
    ok = {s.name: s.ok for s in sonden}
    assert ok["getClassregCategories"] is False
    assert ok["getClassregCategoryGroups"] is True
    assert ok["getRemarkCategories"] is False
    assert ok["getStatusData"] is True
    gruppen = next(s for s in sonden if s.name == "getClassregCategoryGroups")
    assert any(stich == "attest" for _, stich in gruppen.treffer)


def _http_mit(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x.example")


@pytest.mark.asyncio
async def test_rest_get_meldet_status_content_type_laenge_und_keys():
    def handler(request: httpx.Request):
        assert request.method == "GET"
        return httpx.Response(200, json={"data": [1], "meta": {}})

    async with _http_mit(handler) as http:
        sonde = await probe.rest_sonde(http, "classreg/classroles", {}, "Cookie")
    assert sonde.ok
    text = "\n".join(sonde.zeilen)
    assert "200" in text and "application/json" in text and "data" in text and "meta" in text


@pytest.mark.asyncio
async def test_rest_get_500_kuerzt_body_und_maskiert():
    def handler(request: httpx.Request):
        return httpx.Response(500, text="x" * 1000, headers={"content-type": "text/plain"})

    async with _http_mit(handler) as http:
        sonde = await probe.rest_sonde(http, "classreg/absences/students", {}, "Cookie")
    assert not sonde.ok
    assert "500" in "\n".join(sonde.zeilen)
    assert "x" * 301 not in "\n".join(sonde.zeilen)


@pytest.mark.asyncio
async def test_rest_netzwerkfehler_bricht_nicht_ab():
    def handler(request: httpx.Request):
        raise httpx.ConnectTimeout("timeout")

    async with _http_mit(handler) as http:
        sonde = await probe.rest_sonde(http, "classreg/classroles", {}, "Cookie")
    assert not sonde.ok


@pytest.mark.asyncio
async def test_befund_fasst_sonden_und_fundorte_zusammen():
    ok = probe.Sonde("A", True, ["z"], [("A.rolle", "role")])
    fehl = probe.Sonde("B", False, ["z"], [])
    zeilen = probe.befund([ok, fehl])
    text = "\n".join(zeilen)
    assert "✔ A" in text and "✖ B" in text
    assert "Klassendienst-Indizien: ja" in text and "A.rolle" in text
    assert "Klassendienst-Indizien: nein" in "\n".join(probe.befund([fehl]))


@pytest.mark.asyncio
async def test_alle_sonden_laufen_mit_gemocktem_client_und_http():
    client = _client(
        {
            "getCurrentSchoolyear": SCHULJAHR,
            "getHolidays": [{"id": 1, "name": "F", "startDate": 20261026, "endDate": 20261030}],
            "getKlassen": [{"id": 1, "name": "10a"}],
            "getClassregCategories": WebUntisError("nope"),
            "getClassregCategoryGroups": WebUntisError("nope"),
            "getRemarkCategories": WebUntisError("nope"),
            "getStatusData": {"codes": []},
        }
    )
    aufgerufen = []

    def handler(request: httpx.Request):
        assert request.method == "GET" or "jsonrpc_web" in request.url.path
        aufgerufen.append(request.url.path)
        if request.url.path.endswith("token/new"):
            return httpx.Response(200, text="TOKEN")
        return httpx.Response(404, text="nicht da")

    async with _http_mit(handler) as http:
        sonden = await probe.fuehre_alle_sonden_aus(client, http)
    assert any(s.name == "getHolidays" and s.ok for s in sonden)
    assert any("classreg/classservices" in s.name for s in sonden)
    assert any(p.endswith("classreg/classroles") for p in aufgerufen)
    assert "\n".join(probe.befund(sonden))


# --- jsonrpc_web-Dienst ---


@pytest.mark.parametrize("name", ["getStudentDuties", "listDuties", "findDuty", "system.listMethods"])
def test_methoden_whitelist_erlaubt_lesende_namen(name):
    assert probe.pruefe_methode(name) == name


@pytest.mark.parametrize("name", ["deleteDuty", "setDuty", "createDuty", "updateX", "saveStudentDuty", "", "xgetFoo", "getFoo;drop", "system.shutdown"])
def test_methoden_whitelist_lehnt_alles_andere_ab(name):
    with pytest.raises(ValueError):
        probe.pruefe_methode(name)


def test_pfadpruefung_normalisiert_und_haelt_unter_webuntis():
    assert probe.pruefe_pfad("jsonrpc_web/jsonStudentDutyService") == "/WebUntis/jsonrpc_web/jsonStudentDutyService"
    assert probe.pruefe_pfad("/WebUntis/jsonrpc_web/x") == "/WebUntis/jsonrpc_web/x"


@pytest.mark.parametrize("pfad", ["", "../etc/passwd", "WebUntis/../admin", "https://evil.example/x", "a?b=1", "/WebUntis/"])
def test_pfadpruefung_lehnt_ab(pfad):
    with pytest.raises(ValueError):
        probe.pruefe_pfad(pfad)


def test_parse_args_bricht_bei_schreibender_methode_ab():
    with pytest.raises(SystemExit):
        probe.parse_args(["--rpc-method", "deleteDuty"])
    args = probe.parse_args(["--rpc-method", "getFoo", "--rpc-params", '{"a": 1}'])
    assert args.rpc_params == {"a": 1} and args.rpc_path == "/WebUntis/jsonrpc_web/jsonStudentDutyService"
    with pytest.raises(SystemExit):
        probe.parse_args(["--rpc-path", "https://x/y"])


def _rpc_kategorie(response: httpx.Response) -> str:
    return probe.klassifiziere_antwort(response)[0]


def test_klassifikation_unterscheidet_http_redirect_html_und_rpc_fehler():
    assert _rpc_kategorie(httpx.Response(401)) == "http_auth"
    assert _rpc_kategorie(httpx.Response(403, text="x")) == "http_auth"
    assert _rpc_kategorie(httpx.Response(302, headers={"location": "/WebUntis/login"})) == "login_umleitung"
    assert _rpc_kategorie(httpx.Response(200, text="<html>Login</html>", headers={"content-type": "text/html"})) == "login_umleitung"
    assert _rpc_kategorie(httpx.Response(200, json={"error": {"code": -32601, "message": "Method not found"}})) == "methode_unbekannt"
    assert _rpc_kategorie(httpx.Response(200, json={"error": {"code": -8520, "message": "not authenticated"}})) == "auth"
    assert _rpc_kategorie(httpx.Response(200, json={"error": {"code": -8509, "message": "no right"}})) == "permission"
    assert _rpc_kategorie(httpx.Response(200, json={"error": {"code": -1, "message": "boom"}})) == "rpc_fehler"
    assert _rpc_kategorie(httpx.Response(200, json={"result": []})) == "ok"
    assert _rpc_kategorie(httpx.Response(200, text="plain", headers={"content-type": "text/plain"})) == "unerwartet"


@pytest.mark.asyncio
async def test_rpc_web_sonde_postet_jsonrpc_maskiert_und_klassifiziert():
    gesehen = {}

    def handler(request: httpx.Request):
        gesehen["pfad"] = request.url.path
        gesehen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": [{"id": 1, "studentName": "Maximilian", "dienst": "Klassensprecher"}]})

    async with _http_mit(handler) as http:
        sonde = await probe.rpc_web_sonde(http, "jsonrpc_web/jsonStudentDutyService", "getStudentDuties", {}, {})
    assert gesehen["pfad"] == "/WebUntis/jsonrpc_web/jsonStudentDutyService"
    assert gesehen["body"]["method"] == "getStudentDuties" and gesehen["body"]["jsonrpc"] == "2.0"
    text = "\n".join(sonde.zeilen)
    assert sonde.ok and sonde.kategorie == "ok" and "GERATEN" in sonde.name
    assert "Maximilian" not in text and "Ma…" in text
    assert sonde.treffer


@pytest.mark.asyncio
async def test_rpc_web_sonde_lehnt_schreibende_methode_ohne_request_ab():
    def handler(request: httpx.Request):
        raise AssertionError("darf nicht gesendet werden")

    async with _http_mit(handler) as http:
        with pytest.raises(ValueError):
            await probe.rpc_web_sonde(http, "jsonrpc_web/x", "deleteDuty", {}, {})


@pytest.mark.asyncio
async def test_befund_unterscheidet_dienst_erreichbar_und_auth_problem():
    erreichbar = probe.Sonde("RPC a", False, [], [], None, "methode_unbekannt")
    zu = probe.Sonde("RPC b", False, [], [], None, "login_umleitung")
    assert "jsonrpc_web-Dienst: erreichbar" in "\n".join(probe.befund([erreichbar, zu]))
    text = "\n".join(probe.befund([zu]))
    assert "NICHT nutzbar" in text and "login_umleitung" in text
    assert "jsonrpc_web" not in "\n".join(probe.befund([probe.Sonde("A", True)]))


@pytest.mark.asyncio
async def test_duty_sonden_mit_gemocktem_httpx_login_redirect():
    def handler(request: httpx.Request):
        assert request.method == "POST"
        return httpx.Response(302, headers={"location": "/WebUntis/login"})

    async with _http_mit(handler) as http:
        sonden = await probe.sonde_duty_service(http, "S", "schule")
    assert len(sonden) == len(probe.DUTY_KANDIDATEN)
    assert all(s.kategorie == "login_umleitung" for s in sonden)


# --- token/new-Diagnose, Cookies, CSRF-Suche, Duty-Matrix (Erweiterung) ---

GEHEIM = "SEHR-GEHEIMER-WERT"


def _jwt(claims: dict) -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64(claims)}.c2lnbmF0dXI"


def _text(sonde: probe.Sonde) -> str:
    return "\n".join([sonde.name, *sonde.zeilen, json.dumps(sonde.roh, default=str)])


def test_analysiere_jwt_liefert_claim_namen_ohne_werte():
    jetzt = 1_000_000.0
    token = _jwt({"sub": GEHEIM, "exp": jetzt + 3600, "tenant_id": 1234})
    info = probe.analysiere_jwt(token, jetzt=jetzt)
    assert info is not None
    assert info.claim_namen == ["exp", "sub", "tenant_id"]
    assert info.gueltig_min == pytest.approx(60.0)
    assert info.tenant_id == "1234"
    assert GEHEIM not in repr(info) and token not in repr(info)


@pytest.mark.parametrize("text", ["TOKEN", "", "eyJabc.def", "eyJabc.def.ghi.jkl", "abc.def.ghi", "eyJ!!.x.y", "<html>eyJ</html>"])
def test_analysiere_jwt_erkennt_nicht_jwt(text):
    assert probe.analysiere_jwt(text) is None


def test_analysiere_jwt_ohne_exp_und_abgelaufen():
    assert probe.analysiere_jwt(_jwt({"a": 1})).gueltig_min is None
    assert probe.analysiere_jwt(_jwt({"exp": 100}), jetzt=700.0).gueltig_min == pytest.approx(-10.0)


def _kontext(cookies: dict | None = None, session: str = "SESSION") -> probe.Kontext:
    k = probe.Kontext("Meine Schule")
    for n, v in (cookies or {"JSESSIONID": session}).items():
        k.setze(n, v)
    return k


@pytest.mark.asyncio
async def test_token_diagnose_jwt_nur_claim_namen_und_gueltigkeit():
    token = _jwt({"sub": GEHEIM, "exp": time.time() + 3600})
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, text=token, headers={"content-type": "text/plain"})

    async with _http_mit(handler) as http:
        sonde, bearer = await probe.diagnose_token(http, _kontext())
    assert bearer == token and sonde.ok and sonde.tag == "token" and sonde.extra["jwt"] is True
    text = _text(sonde)
    assert "JWT-Form: ja" in text and "exp" in text and "sub" in text
    assert "Gueltigkeit: noch 60" in text
    assert token not in text and GEHEIM not in text
    assert "JSESSIONID=SESSION" in seen[0].headers["cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, klasse",
    [
        (httpx.Response(302, headers={"location": "https://x.example/WebUntis/login?secret=1"}), "redirect"),
        (httpx.Response(200, text="<html>Login</html>", headers={"content-type": "text/html"}), "login_html"),
        (httpx.Response(403, text="nein"), "http_auth"),
        (httpx.Response(500, text="boom"), "http_fehler"),
        (httpx.Response(200, text=""), "leer"),
    ],
)
async def test_token_diagnose_fehlerklassen(response, klasse):
    async with _http_mit(lambda r: response) as http:
        sonde, bearer = await probe.diagnose_token(http, _kontext())
    assert bearer is None and not sonde.ok and sonde.extra["klasse"] == klasse
    assert f"Klasse: {klasse}" in _text(sonde)
    assert "secret=1" not in _text(sonde)


@pytest.mark.asyncio
async def test_token_diagnose_nicht_jwt_text_ist_trotzdem_verwendbar_aber_markiert():
    async with _http_mit(lambda r: httpx.Response(200, text="OPAKES-TOKEN")) as http:
        sonde, bearer = await probe.diagnose_token(http, _kontext())
    assert bearer == "OPAKES-TOKEN" and sonde.ok and sonde.extra["jwt"] is False
    assert "JWT-Form: nein" in _text(sonde) and "OPAKES-TOKEN" not in _text(sonde)


@pytest.mark.asyncio
async def test_token_diagnose_netzwerkfehler():
    def handler(request):
        raise httpx.ConnectTimeout("t")

    async with _http_mit(handler) as http:
        sonde, bearer = await probe.diagnose_token(http, _kontext())
    assert bearer is None and not sonde.ok


def test_kontext_cookie_uebersicht_nur_namen_und_selbst_gesetzte():
    k = _kontext({"JSESSIONID": GEHEIM, "traceId": "t-" + GEHEIM})
    sonde = probe.cookie_uebersicht(k)
    text = _text(sonde)
    assert "JSESSIONID" in text and "traceId" in text and GEHEIM not in text
    assert "Tenant-Id: nein" in text and "schoolname: nein" in text
    k.setze_schoolname()
    assert k.herkunft["schoolname"] == "selbst"
    assert k.cookies["schoolname"] == '"_' + base64.b64encode(b"Meine Schule").decode() + '"'
    assert "Tenant-Id" not in k.cookies  # nicht ableitbar -> weggelassen
    assert "schoolname=" in k.header()["Cookie"]


def test_kontext_vorhandene_cookies_werden_nicht_ueberschrieben_und_tenant_aus_set_cookie():
    k = _kontext({"JSESSIONID": "S", "schoolname": '"_VORHANDEN"'})
    k.setze_schoolname()
    assert k.cookies["schoolname"] == '"_VORHANDEN"' and k.herkunft["schoolname"] == "jar"
    antwort = httpx.Response(200, headers=[("set-cookie", "Tenant-Id=4711; Path=/WebUntis; Secure")])
    k.uebernimm_set_cookie(antwort)
    assert k.cookies["Tenant-Id"] == "4711" and k.herkunft["Tenant-Id"] == "abgeleitet"


def test_lese_cookie_jar_und_kontext_aus_client():
    client = AsyncMock()
    client._session_id = "SESS"
    client._http = httpx.AsyncClient()
    client._http.cookies.set("Tenant-Id", "42", domain="x.example", path="/")
    k = probe.Kontext.aus_client(client, "Schule")
    assert k.cookies["Tenant-Id"] == "42" and k.cookies["JSESSIONID"] == "SESS"
    assert probe.Kontext.aus_client(AsyncMock(_session_id="S"), "Schule").cookies == {"JSESSIONID": "S"}


# CSRF-Suche

CSRF_WERT = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def _html(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def test_suche_csrf_findet_meta_skript_input_json_header_cookie_ohne_wert():
    html = (
        f'<html><head><meta name="_csrf" content="{CSRF_WERT}"></head><body>'
        f'<script>var csrfToken = "{CSRF_WERT}1"; window.xsrf_value: \'{CSRF_WERT}2\';</script>'
        f'<input type="hidden" name="_csrf_input" value="{CSRF_WERT}3"></body></html>'
    )
    resp = httpx.Response(
        200, text=html, headers=[("content-type", "text/html"), ("X-CSRF-TOKEN", CSRF_WERT + "4"), ("set-cookie", f"XSRF-TOKEN={CSRF_WERT}5; Path=/")]
    )
    orte = {f.ort: f for f in probe.suche_csrf(resp)}
    assert "meta[name=_csrf]" in orte
    assert "Skriptvariable csrfToken" in orte
    assert "input[name=_csrf_input]" in orte
    assert "Header X-CSRF-TOKEN" in orte or "Header x-csrf-token" in orte
    assert "Cookie XSRF-TOKEN" in orte
    assert orte["meta[name=_csrf]"].laenge == len(CSRF_WERT)
    assert orte["meta[name=_csrf]"].form == "url-safe base64"
    assert CSRF_WERT not in repr(list(orte.values()))


def test_suche_csrf_json_key():
    resp = httpx.Response(200, json={"data": {"csrfToken": CSRF_WERT}, "x": 1})
    funde = probe.suche_csrf(resp)
    assert [f.ort for f in funde] == ["JSON-Key data.csrfToken"]


@pytest.mark.parametrize(
    "wert, form",
    [("xyz123456789", "url-safe base64"), ("abcdef0123456789" * 2, "hex"), ("Ab-_Cd" * 10, "url-safe base64"), ("Ab+/Cd" * 6 + "==", "base64"), ("ab c!" * 5, "sonstige Zeichen")],
)
def test_beschreibe_form(wert, form):
    assert probe.beschreibe_form(wert) == form


@pytest.mark.asyncio
async def test_csrf_quellensuche_gibt_nie_den_wert_aus_und_folgt_keinem_redirect():
    pfade = []

    def handler(request: httpx.Request):
        pfade.append(request.url.path)
        if request.url.path == "/WebUntis/index.do":
            return httpx.Response(302, headers={"location": "https://login.example/sso/start?t=" + CSRF_WERT})
        if request.url.path == "/WebUntis/embedded.do":
            return httpx.Response(
                200, text=f'<meta name="_csrf" content="{CSRF_WERT}">', headers=[("content-type", "text/html"), ("set-cookie", "Tenant-Id=77; Path=/")]
            )
        return httpx.Response(404, text="nix")

    k = _kontext()
    async with _http_mit(handler) as http:
        sonden, token = await probe.csrf_quellensuche(http, k)
    assert token == CSRF_WERT
    alles = "\n".join(_text(s) for s in sonden) + "\n".join(probe.befund(sonden))
    assert CSRF_WERT not in alles
    assert "login.example" in alles and "/sso/start" in alles and "?t=" not in alles
    assert "meta[name=_csrf]" in alles and f"url-safe base64, {len(CSRF_WERT)} Zeichen" in alles
    assert pfade.count("/WebUntis/index.do") == 1 and not any("sso" in p for p in pfade)  # Redirect nicht gefolgt
    assert any("/WebUntis/api/csrf" in s.name and "geraten" in s.name.lower() for s in sonden)
    assert any("/WebUntis/api/token/csrf" in s.name for s in sonden)
    assert k.cookies["Tenant-Id"] == "77"
    csrf = next(s for s in sonden if s.tag == "csrf" and s.extra["fundorte"])
    assert "meta[name=_csrf]" in csrf.extra["fundorte"]


@pytest.mark.asyncio
async def test_csrf_quellensuche_ohne_fund_und_mit_netzwerkfehler():
    def handler(request: httpx.Request):
        if request.url.path == "/WebUntis/":
            raise httpx.ConnectTimeout("t")
        return _html("<html>nichts</html>")

    async with _http_mit(handler) as http:
        sonden, token = await probe.csrf_quellensuche(http, _kontext())
    assert token is None and len(sonden) == 5
    assert "CSRF-Quelle gefunden: nein" in "\n".join(probe.befund(sonden))


@pytest.mark.asyncio
async def test_csrf_erwaehnung_ohne_extrahierbaren_wert_wird_gemeldet():
    async with _http_mit(lambda r: _html("<p>CSRF protection, xsrf</p>")) as http:
        sonden, token = await probe.csrf_quellensuche(http, _kontext())
    assert token is None and "Erwaehnung" in _text(sonden[0])


# Duty-Matrix

STRUKTUR_ERGEBNIS = {
    "klasseName": "10a",
    "dutyName": "Entschuldigungspflicht",
    "dutyOptions": [{"id": 26, "label": "Entschuldigungspflicht"}, {"id": 27, "label": "Attest"}],
    "klasseOptions": [{"id": 1, "label": "10a"}, {"id": 2, "label": "10b"}],
    "studentOptions": [{"id": 5, "label": "Maximilian Mustermann"}],
    "config": {"canWrite": False},
    "matrix": {
        "columns": [{"id": 20260907, "numberOfWorkdays": 5, "holidays": []}, {"id": 20260914, "numberOfWorkdays": 5}, {"id": 20260921}],
        "rows": [
            {
                "studentDTO": {"id": 5, "firstName": "Maximilian", "lastName": "Mustermann", "klasse": "10a"},
                "relations": [20260907, 20260914, 20260921],
                "absences": [20260914],
            },
            {"studentDTO": {"id": 6, "name": "Erika Musterfrau"}, "relations": [], "absences": []},
        ],
    },
}


def _duty_handler(aufgezeichnet: list, antwort):
    def handler(request: httpx.Request):
        aufgezeichnet.append(request)
        return antwort(request) if callable(antwort) else antwort

    return handler


@pytest.mark.asyncio
async def test_duty_matrix_setzt_erwartete_header_je_kombination():
    req: list = []
    handler = _duty_handler(req, httpx.Response(403, text="<html>no</html>", headers={"content-type": "text/html"}))
    k = _kontext()
    async with _http_mit(handler) as http:
        sonden = await probe.sonde_duty_matrix(http, k, 3821, [26], csrf="CSRF123456789012345", jwt="JWT.TOKEN.X")
    assert [s.tag for s in sonden] == ["duty:a", "duty:b", "duty:c", "duty:d", "duty:e", "duty:e+"]
    assert len(req) == 6
    for r in req:
        assert r.url.path == "/WebUntis/jsonrpc_web/jsonStudentDutyService" and r.method == "POST"
        assert r.headers["content-type"].startswith("application/json")
        assert r.headers["x-requested-with"] == "XMLHttpRequest"
        assert r.headers["origin"] == "https://x.example"
        assert r.headers["referer"] == "https://x.example/WebUntis/embedded.do?showSidebar=true"
        assert "JSESSIONID=SESSION" in r.headers["cookie"]
        body = json.loads(r.content)
        assert body["method"] == "getStudentDutySchedulerData" and body["params"] == [3821, 26]
    a, b, c, d, e, e2 = req
    assert "x-csrf-token" not in a.headers and "authorization" not in a.headers
    assert b.headers["x-csrf-token"] == "CSRF123456789012345" and "authorization" not in b.headers
    assert c.headers["authorization"] == "Bearer JWT.TOKEN.X" and "x-csrf-token" not in c.headers
    assert d.headers["x-csrf-token"] == "CSRF123456789012345" and d.headers["authorization"] == "Bearer JWT.TOKEN.X"
    assert e.headers["x-csrf-token"] == "JWT.TOKEN.X" and "authorization" not in e.headers
    assert e2.headers["x-csrf-token"] == "JWT.TOKEN.X" and e2.headers["authorization"] == "Bearer JWT.TOKEN.X"
    namen = {s.tag: s.name for s in sonden}
    assert "HYPOTHESE" in namen["duty:e"] and "HYPOTHESE" in namen["duty:e+"]
    assert all("JWT.TOKEN.X" not in _text(s) and "CSRF1234567" not in _text(s) for s in sonden)


@pytest.mark.asyncio
async def test_duty_matrix_ueberspringt_ohne_csrf_und_jwt_ohne_request_und_mehrere_duty_ids():
    req: list = []
    async with _http_mit(_duty_handler(req, httpx.Response(403, text="x"))) as http:
        sonden = await probe.sonde_duty_matrix(http, _kontext(), 3821, [26, 27], csrf=None, jwt=None)
    assert len(req) == 2 and [json.loads(r.content)["params"] for r in req] == [[3821, 26], [3821, 27]]
    uebersprungen = [s for s in sonden if "uebersprungen" in _text(s)]
    assert {s.tag for s in uebersprungen} >= {"duty:b", "duty:c", "duty:d", "duty:e", "duty:e+"}
    assert all(not s.ok and s.kategorie is None for s in uebersprungen)


@pytest.mark.asyncio
async def test_duty_403_html_body_wird_auf_200_zeichen_gekuerzt_ohne_tags():
    html = "<html><head><style>p{}</style><title>T</title></head><body><h1>Forbidden</h1>\n\n<p>CSRF   token\tmissing</p>" + "<b>lang</b> " * 100 + ("Z" * 80) + "</body></html>"
    async with _http_mit(lambda r: httpx.Response(403, text=html, headers={"content-type": "text/html"})) as http:
        sonde = await probe.rpc_web_sonde(http, "jsonrpc_web/x", "getStudentDutySchedulerData", [1, 2], {}, geraten=False)
    zeile = next(z for z in sonde.zeilen if z.startswith("Body (gekuerzt)"))
    inhalt = zeile.split(": ", 1)[1]
    assert len(inhalt) <= 201 and "<" not in inhalt and "p{}" not in inhalt
    assert inhalt.startswith("T Forbidden CSRF token missing")
    assert sonde.kategorie == "http_auth" and sonde.extra["status"] == 403 and sonde.extra["body_csrf"] is True


def test_kuerze_body_maskiert_lange_token_artige_laeufe():
    assert "A" * 40 not in probe.kuerze_body("Fehler " + "A" * 60 + " ende")


@pytest.mark.asyncio
async def test_strukturbericht_bei_erfolg_ohne_namen_und_studentdto():
    async with _http_mit(lambda r: httpx.Response(200, json={"result": STRUKTUR_ERGEBNIS})) as http:
        sonde = await probe.rpc_web_sonde(http, "jsonrpc_web/x", "getStudentDutySchedulerData", [3821, 26], {}, geraten=False)
    assert sonde.ok and sonde.kategorie == "ok"
    text = _text(sonde)
    for verboten in ("Maximilian", "Mustermann", "Erika", "Musterfrau", "studentDTO", "firstName", "Ma…"):
        assert verboten not in text
    assert "klasseName: 10a" in text and "dutyName: Entschuldigungspflicht" in text
    assert "columns: 3" in text and "rows: 2" in text
    assert "Schueler 1: relations=3 (20260907 .. 20260921), absences=1" in text
    assert "Schueler 2: relations=0" in text
    assert "26=Entschuldigungspflicht" in text and "27=Attest" in text
    assert "klasseOptions: 2" in text and "studentOptions: 1" in text and "canWrite: vorhanden" in text


def test_strukturbericht_toleriert_fehlende_felder():
    zeilen, _daten = probe.struktur_bericht({"matrix": {"rows": [{"relations": ["Max Muster", 20260907]}]}})
    text = "\n".join(zeilen)
    assert "canWrite: nicht vorhanden" in text and "columns: 0" in text and "Max" not in text


# Befund

def _duty(tag, status, kat, body_csrf=False):
    return probe.Sonde(f"Duty {tag}", kat == "ok", [], [], None, kat, tag, {"status": status, "body_csrf": body_csrf})


def test_befund_schlussfolgerung_alle_403_trotz_csrf_und_token():
    sonden = [
        probe.Sonde("token", True, [], tag="token", extra={"jwt": True, "klasse": "jwt"}),
        probe.Sonde("csrf", True, [], tag="csrf", extra={"fundorte": ["meta[name=_csrf]"]}),
        *[_duty(f"duty:{k}", 403, "http_auth") for k in "abcde"],
    ]
    text = "\n".join(probe.befund(sonden))
    assert "token/new: ✔ (JWT: ja)" in text
    assert "CSRF-Quelle gefunden: ja (meta[name=_csrf])" in text
    assert "Duty-Kombinationen ohne HTTP 403: keine" in text
    assert "403 unabhaengig von Token/CSRF → vermutlich Rechte-Problem des Service-Accounts" in text


def test_befund_schlussfolgerung_csrf_genuegt_und_andere_faelle():
    mit_b = [probe.Sonde("csrf", True, [], tag="csrf", extra={"fundorte": ["x"]}), _duty("duty:a", 403, "http_auth"), _duty("duty:b", 200, "ok")]
    text = "\n".join(probe.befund(mit_b))
    assert "Duty-Kombinationen ohne HTTP 403: b (ok)" in text
    assert "Kombination (b) liefert Daten → CSRF-Token genuegt" in text
    c = [probe.Sonde("token", True, [], tag="token", extra={"jwt": True, "klasse": "jwt"}), _duty("duty:a", 403, "http_auth"), _duty("duty:c", 200, "ok")]
    assert "Bearer-JWT genuegt" in "\n".join(probe.befund(c))
    nur_a = "\n".join(probe.befund([_duty("duty:a", 200, "ok")]))
    assert "Kombination (a) liefert Daten → Cookies genuegen" in nur_a
    nicht_403 = "\n".join(probe.befund([_duty("duty:a", 403, "http_auth"), _duty("duty:d", 200, "rpc_fehler")]))
    assert "d (rpc_fehler)" in nicht_403 and "Kein 403" in nicht_403
    ohne_csrf = "\n".join(probe.befund([probe.Sonde("csrf", False, [], tag="csrf", extra={"fundorte": []}), _duty("duty:a", 403, "http_auth", body_csrf=True)]))
    assert "CSRF-Quelle gefunden: nein" in ohne_csrf and "CSRF" in ohne_csrf.splitlines()[-1]


def test_befund_token_fehlgeschlagen_und_cookies():
    sonden = [
        probe.Sonde("token", False, [], tag="token", extra={"jwt": False, "klasse": "redirect"}),
        probe.Sonde("cookies", False, [], tag="cookies", extra={"Tenant-Id": "fehlt", "schoolname": "selbst"}),
    ]
    text = "\n".join(probe.befund(sonden))
    assert "token/new: ✖ (JWT: nein, Klasse: redirect)" in text
    assert "Cookies: Tenant-Id fehlt, schoolname selbst gesetzt" in text


# REST-Varianten und Gesamtlauf

@pytest.mark.asyncio
async def test_rest_sonden_haben_bearer_ohne_cookie_und_bearer_plus_cookie():
    req: list = []
    async with _http_mit(_duty_handler(req, httpx.Response(302, headers={"location": "/WebUntis/login"}))) as http:
        sonden = await probe.sonde_rest(http, _kontext(), "TOK", SCHULJAHR)
    labels = {s.name.split("[")[1].split(",")[0] for s in sonden}
    assert labels == {"Cookie", "Bearer", "Bearer+Cookie"}
    nur_bearer = [r for r in req if "authorization" in r.headers and "cookie" not in r.headers]
    beides = [r for r in req if "authorization" in r.headers and "cookie" in r.headers]
    assert nur_bearer and len(nur_bearer) == len(beides)


@pytest.mark.asyncio
async def test_rest_ohne_token_nur_cookie_variante():
    async with _http_mit(lambda r: httpx.Response(404)) as http:
        sonden = await probe.sonde_rest(http, _kontext(), None, None)
    assert {s.name.split("[")[1].split(",")[0] for s in sonden} == {"Cookie"}


@pytest.mark.asyncio
async def test_gesamtlauf_nutzt_erste_klasse_und_default_duty_26_und_gibt_keine_werte_aus():
    token = _jwt({"sub": GEHEIM, "exp": time.time() + 600})
    client = _client(
        {
            "getCurrentSchoolyear": SCHULJAHR,
            "getHolidays": [],
            "getKlassen": [{"id": 3821, "name": "10a"}],
            "getClassregCategories": WebUntisError("n"),
            "getClassregCategoryGroups": WebUntisError("n"),
            "getRemarkCategories": WebUntisError("n"),
            "getStatusData": WebUntisError("n"),
        }
    )
    client._http = httpx.AsyncClient()
    client._http.cookies.set("traceId", GEHEIM, domain="x.example", path="/")
    duty_params = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("token/new"):
            return httpx.Response(200, text=token)
        if request.url.path == "/WebUntis/embedded.do":
            return _html(f'<meta name="_csrf" content="{CSRF_WERT}">')
        if request.url.path.endswith("jsonStudentDutyService"):
            body = json.loads(request.content)
            if body["method"] == probe.DUTY_METHODE:
                duty_params.append(body["params"])
                return httpx.Response(403, text="Forbidden", headers={"content-type": "text/html"})
        return httpx.Response(404, text="nix")

    async with _http_mit(handler) as http:
        sonden = await probe.fuehre_alle_sonden_aus(client, http)
    assert duty_params == [[3821, 26]] * 6
    ausgabe = "\n".join(_text(s) for s in sonden) + "\n".join(probe.befund(sonden))
    for geheim in (GEHEIM, token, CSRF_WERT):
        assert geheim not in ausgabe
    assert "traceId" in ausgabe and "schoolname selbst gesetzt" in ausgabe
    assert "403 unabhaengig von Token/CSRF" in ausgabe


def test_parse_args_klasse_und_duty_ids():
    args = probe.parse_args([])
    assert args.klasse_id is None and args.duty_id == [26]
    args = probe.parse_args(["--klasse-id", "3821", "--duty-id", "26", "--duty-id", "27"])
    assert args.klasse_id == 3821 and args.duty_id == [26, 27]
    with pytest.raises(SystemExit):
        probe.parse_args(["--klasse-id", "abc"])


# --- ID-Abgleich: getStudents, Matrix, DB (read-only), dutyOptions ---

UUID_A = "3f2b8c1e-5a4d-4e6f-9a1b-0c2d3e4f5a6b"
UUID_B = "7a1c9d2e-1b3f-4c5d-8e7f-6a5b4c3d2e1f"
UUID_C = "0b9e8d7c-6a5f-4e3d-9c2b-1a0f9e8d7c6b"


def _studenten():
    return [
        {"id": 52911, "foreName": "Anna-Lena", "longName": "Müller", "key": UUID_A, "name": "MuellerA", "birthDate": 20080315, "externKey": "x1"},
        {"id": 52912, "foreName": "Jonas", "longName": "Groß", "key": UUID_B, "name": "GrossJ", "birthDate": 20070101, "externKey": "x2"},
        {"id": 52913, "foreName": "Jonas", "longName": "Gross", "key": UUID_C, "name": "GrossJ2", "birthDate": 20070202, "externKey": ""},
    ]


@pytest.mark.parametrize(
    "wert,klasse",
    [
        (5, "numerisch"), ("123", "numerisch"), (1.5, "numerisch"), (UUID_A, "UUID"), (UUID_A.upper(), "UUID"),
        ("2026-08-01", "Datum"), ("01.08.2026", "Datum"), (20260801, "Datum"), ("MuellerA", "kurzer String"),
        ("ein langer Satz mit Leerzeichen", "Freitext"), ("", "leer"), (None, "leer"), (True, "bool"), ([1], "Struktur"),
    ],
)
def test_klassifiziere_wert(wert, klasse):
    assert probe.klassifiziere_wert(wert) == klasse


def test_profil_und_uuid_key_erkennung():
    profil = probe.profil_keys(_studenten())
    assert profil["id"]["klassen"] == {"numerisch": 3}
    assert profil["externKey"]["befuellt"] == 2 and profil["externKey"]["n"] == 3
    assert probe.uuid_keys(profil) == ["key"]
    text = "\n".join(probe.profil_zeilen(profil))
    assert "key: befuellt 3/3 (100%); Form: UUID 100%" in text and "externKey: befuellt 2/3 (67%)" in text
    gemischt = probe.profil_keys([{"k": UUID_A}, {"k": "abc"}, {"k": "def"}])
    assert probe.uuid_keys(gemischt) == []


@pytest.mark.parametrize(
    "a,b",
    [("Müller", "Mueller"), ("Groß", "gross"), ("Anna-Lena", "anna lena"), ("ANNALENA", "Anna-Lena"), ("O'Brien", "obrien"), ("José", "jose")],
)
def test_namensnormalisierung(a, b):
    assert probe.normalisiere_name(a) == probe.normalisiere_name(b)


def test_namensnormalisierung_unterscheidet_verschiedene_namen():
    assert probe.normalisiere_name("Mayer") != probe.normalisiere_name("Meier")
    assert probe.normalisiere_name(None) == ""


@pytest.mark.asyncio
async def test_sonde_students_profil_beispiel_maskiert_und_uuid_key():
    sonde = await probe.sonde_students(_client({"getStudents": _studenten()}), SCHULJAHR)
    assert sonde.ok and sonde.extra["uuid_keys"] == ["key"]
    text = _text(sonde)
    assert "Anzahl Eintraege: 3" in text and "UUID-foermige Keys (Kandidat fuer externe_id): key" in text
    for verboten in ("Anna", "Müller", "MuellerA", UUID_A, "20080315", "Lena"):
        assert verboten not in text
    assert "<Datum>" in text and "3f2b…" in text


@pytest.mark.asyncio
async def test_sonde_students_fehlerklasse_und_geratene_alternative():
    aufrufe = []

    async def call(method, params):
        aufrufe.append((method, params))
        if params == {}:
            raise WebUntisError("WebUntis-Aufruf 'getStudents' fehlgeschlagen: {'code': -8509, 'message': 'no right for getStudents()'}")
        return _studenten()

    client = AsyncMock()
    client.call.side_effect = call
    sonde = await probe.sonde_students(client, SCHULJAHR)
    assert aufrufe == [("getStudents", {}), ("getStudents", {"schoolyearId": 9})]
    text = _text(sonde)
    assert sonde.ok and "keine Berechtigung" in text and "[GERATEN]" in text


@pytest.mark.asyncio
async def test_sonde_students_nicht_verfuegbar():
    sonde = await probe.sonde_students(_client({"getStudents": WebUntisError("{'code': -32601, 'message': 'Method not found'}")}), None)
    assert not sonde.ok and "Methode nicht vorhanden" in _text(sonde)


def test_fehlerklassen():
    assert probe.fehlerklasse(WebUntisError("x -32601")) == "Methode nicht vorhanden"
    assert probe.fehlerklasse(WebUntisError("-8509 no right")) == "keine Berechtigung"
    assert probe.fehlerklasse(WebUntisError("-8520 not authenticated")) == "nicht authentifiziert"
    assert probe.fehlerklasse(ValueError("zzz")).startswith("sonstiger Fehler")


DTOS = [
    {"id": 52911, "firstname": "Anna Lena", "lastname": "Mueller", "displayName": "Müller Anna-Lena", "catalogNo": 1},
    {"id": 52912, "firstname": "Jonas", "lastname": "Gross", "displayName": "Gross Jonas"},  # mehrdeutig
    {"id": 99999, "firstname": "Nobody", "lastname": "Nirgends", "displayName": "Nirgends Nobody"},
]


def test_abgleich_matrix_zahlen_ohne_namen():
    a = probe.abgleich_matrix(_studenten(), DTOS)
    assert a["m"] == 3 and a["id_key"] == "id" and a["id_n"] == 2 and a["id_treffer"] == {"id": 2}
    assert a["name"] == (1, 1, 1)  # eindeutig: Anna Lena; mehrdeutig: Jonas Gross/Groß; nicht gefunden: Nobody
    assert a["display"] == (1, 1, 1)
    assert set(a["zuordnung"]) == {"52911", "52912"}
    text = "\n".join(probe.abgleich_zeilen(a))
    assert "id: 2/3" in text and "eindeutig 1, mehrdeutig 1, nicht gefunden 1" in text
    for verboten in ("Anna", "Mueller", "Jonas", "Nobody"):
        assert verboten not in text


def test_abgleich_matrix_ohne_treffer():
    a = probe.abgleich_matrix([{"id": 1, "foreName": "A", "longName": "B"}], [{"id": 7, "firstname": "X", "lastname": "Y"}])
    assert a["id_key"] is None and a["id_n"] == 0 and a["name"] == (0, 0, 1)


DB_ZEILEN = [(UUID_A, "Anna-Lena", "Müller", 1), (UUID_B, "Jonas", "Groß", 1), ("andere-id", "Jonas", "Groß", 2), ("fremd", "Zed", "Zorn", None)]


def test_abgleich_db_zahlen():
    a = probe.abgleich_matrix(_studenten(), DTOS)
    d = probe.abgleich_db(_studenten(), a, DTOS, DB_ZEILEN, ["key"])
    assert d["bruecke"] == "key" and d["treffer"] == {"key": 2}
    assert d["via_uuid"] == 2 and d["m"] == 3
    assert d["name"] == (1, 1, 1)  # Anna-Lena eindeutig, Jonas Groß doppelt in DB, Nobody keiner
    text = "\n".join(probe.abgleich_db_zeilen(d, 3))
    assert "key: 2/3 (67%)" in text and "ueber UUID" not in text and "2/3" in text
    for verboten in (UUID_A, UUID_B, "Anna", "Müller", "andere-id", "fremd", "Zorn"):
        assert verboten not in text


def test_schlussfolgerung_faelle():
    basis = {"students_ok": True, "uuid_keys": ["key"], "id_key": "id", "id_n": 2, "m": 3, "name": (1, 1, 1)}
    s = probe.schlussfolgerung({**basis, "db": True, "bruecke": "key", "via_uuid": 2})
    assert "Schluessel `key` aus getStudents entspricht Schueler.externe_id → Zuordnung ueber numerische ID" in s
    assert "--mit-db" in probe.schlussfolgerung(basis)
    k = probe.schlussfolgerung({**basis, "db": True, "bruecke": None, "via_uuid": 0, "db_name": (4, 3, 2)})
    assert k == "keine ID-Bruecke gefunden → nur Namensabgleich (3 mehrdeutig)"
    assert "nicht verfuegbar" in probe.schlussfolgerung({"students_ok": False})


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, protokoll):
        self.protokoll = protokoll

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, *a, **k):
        self.protokoll.append(("execute", str(stmt)))
        return _FakeResult(DB_ZEILEN)

    async def commit(self):
        self.protokoll.append(("commit", ""))

    def add(self, *a):
        self.protokoll.append(("add", ""))

    async def flush(self):
        self.protokoll.append(("flush", ""))


@pytest.mark.asyncio
async def test_mit_db_fuehrt_nur_select_aus_und_gibt_keine_namen_oder_externe_ids_aus():
    protokoll: list = []
    students = await probe.sonde_students(_client({"getStudents": _studenten()}), SCHULJAHR)
    sonden = await probe.sonden_id_abgleich(students, [(3836, {"matrix": {"rows": [{"studentDTO": d} for d in DTOS]}}, "test")], True, lambda: _FakeSession(protokoll))
    assert [p[0] for p in protokoll] == ["execute"]
    stmt = protokoll[0][1].upper().split()
    assert stmt[0] == "SELECT" and not {"INSERT", "UPDATE", "DELETE", "DROP"} & set(stmt)
    assert "SCHUELER.EXTERNE_ID" in protokoll[0][1].upper() and "FROM SCHUELER" in protokoll[0][1].upper()
    ausgabe = "\n".join(_text(s) for s in sonden) + "\n".join(probe.befund([students, *sonden]))
    for verboten in (UUID_A, UUID_B, UUID_C, "andere-id", "fremd", "Anna", "Müller", "Zorn", "Jonas", "Nobody"):
        assert verboten not in ausgabe
    assert "(c) Abbildung auf Schueler: ueber UUID 2/3, ueber Namen eindeutig 1/3" in ausgabe
    assert "(b) Matrix-ID in getStudents: 2/3 (Key id)" in ausgabe
    assert "(a) getStudents: ✔; UUID-Key vorhanden: ja (key)" in ausgabe
    assert "Schluessel `key` aus getStudents entspricht Schueler.externe_id" in ausgabe


@pytest.mark.asyncio
async def test_ohne_mit_db_kein_db_zugriff():
    def verboten():
        raise AssertionError("DB-Zugriff ohne --mit-db")

    students = await probe.sonde_students(_client({"getStudents": _studenten()}), SCHULJAHR)
    sonden = await probe.sonden_id_abgleich(students, [(1, {"matrix": {"rows": [{"studentDTO": DTOS[0]}]}}, "t")], False, verboten)
    assert all(s.tag != "dbabgleich" for s in sonden)
    assert "(c) Abbildung auf Schueler: nicht geprueft" in "\n".join(probe.befund([students, *sonden]))


@pytest.mark.asyncio
async def test_db_fehler_bricht_nicht_ab():
    def kaputt():
        raise RuntimeError("keine DB")

    students = await probe.sonde_students(_client({"getStudents": _studenten()}), SCHULJAHR)
    sonden = await probe.sonden_id_abgleich(students, [(1, {"matrix": {"rows": [{"studentDTO": DTOS[0]}]}}, "t")], True, kaputt)
    assert sonden[-1].tag == "dbabgleich" and not sonden[-1].ok


@pytest.mark.asyncio
async def test_lade_schueler_readonly_gegen_echte_test_db_nur_select(db_session):
    """Echte Test-DB: der Statement-Text wird abgefangen; es wird nichts geschrieben."""
    from sqlalchemy import event

    statements: list[str] = []
    bind = db_session.bind
    sync_engine = getattr(bind, "sync_engine", bind)
    event.listen(sync_engine, "before_cursor_execute", lambda c, cur, stmt, *a: statements.append(stmt))

    class Factory:
        def __call__(self):
            return db_session_ctx(db_session)

    class db_session_ctx:
        def __init__(self, s):
            self.s = s

        async def __aenter__(self):
            return self.s

        async def __aexit__(self, *a):
            return False

    rows = await probe.lade_schueler_readonly(Factory())
    assert isinstance(rows, list)
    mine = [s for s in statements if "schueler" in s.lower()]
    assert mine and all(s.lstrip().upper().startswith("SELECT") for s in mine)


@pytest.mark.asyncio
async def test_duty_optionen_varianten_und_fund():
    req: list = []

    def handler(request: httpx.Request):
        req.append(json.loads(request.content)["params"])
        assert request.headers["x-csrf-token"] == CSRF_WERT
        if len(req) == 2:
            return httpx.Response(200, json={"result": STRUKTUR_ERGEBNIS})
        return httpx.Response(200, json={"result": {"matrix": {"columns": [], "rows": []}}})

    async with _http_mit(handler) as http:
        sonden = await probe.sonde_duty_optionen(http, _kontext(), 3821, CSRF_WERT)
    assert req == [[3821], [3821, None], [3821, 0]]
    assert all("GERATEN" in s.name for s in sonden)
    assert probe.duty_optionen_gefunden(sonden) == ["26=Entschuldigungspflicht", "27=Attest"]
    assert "result-Top-Level-Keys: ['config', 'dutyName', 'dutyOptions'" in _text(sonden[1])
    assert "result-Top-Level-Keys: ['matrix']" in _text(sonden[0])
    assert "(d) dutyOptions gefunden: ja (26=Entschuldigungspflicht, 27=Attest)" in "\n".join(probe.befund([probe.Sonde("s", True, [], tag="students", extra={"uuid_keys": []}), *sonden]))


@pytest.mark.asyncio
async def test_duty_optionen_ohne_csrf_und_ohne_fund():
    async with _http_mit(lambda r: httpx.Response(404)) as http:
        sonden = await probe.sonde_duty_optionen(http, _kontext(), 1, None)
    assert len(sonden) == 1 and "uebersprungen" in _text(sonden[0])
    befund = "\n".join(probe.befund([probe.Sonde("s", False, [], tag="students", extra={"uuid_keys": []})]))
    assert "(d) dutyOptions gefunden: nein" in befund
    assert "(e) Schlussfolgerung: getStudents nicht verfuegbar" in befund


@pytest.mark.asyncio
async def test_gesamtlauf_mit_abgleich_b_ok_ohne_geheimnisse():
    client = _client(
        {
            "getCurrentSchoolyear": SCHULJAHR, "getHolidays": [], "getKlassen": [{"id": 3836, "name": "10a"}],
            "getStudents": _studenten(), "getClassregCategories": WebUntisError("n"), "getClassregCategoryGroups": WebUntisError("n"),
            "getRemarkCategories": WebUntisError("n"), "getStatusData": WebUntisError("n"),
        }
    )  # fmt: skip
    client._http = httpx.AsyncClient()
    aufrufe = []
    ergebnis = {"matrix": {"columns": [], "rows": [{"studentDTO": d, "relations": [], "absences": []} for d in DTOS]}}

    def handler(request: httpx.Request):
        if request.url.path == "/WebUntis/embedded.do":
            return _html(f'<meta name="_csrf" content="{CSRF_WERT}">')
        if request.url.path.endswith("jsonStudentDutyService"):
            body = json.loads(request.content)
            if body["method"] == probe.DUTY_METHODE:
                aufrufe.append((body["params"], "x-csrf-token" in request.headers))
                if "x-csrf-token" in request.headers:
                    return httpx.Response(200, json={"result": ergebnis})
                return httpx.Response(403, text="Forbidden", headers={"content-type": "text/html"})
        return httpx.Response(404, text="nix")

    async with _http_mit(handler) as http:
        sonden = await probe.fuehre_alle_sonden_aus(client, http, klasse_id=3836, duty_ids=[26], abgleich_klassen=[3836], mit_db=False)
    # Matrix (Klasse 3836, Dienst 26, Kombination b) wird fuer den Abgleich wiederverwendet, nicht erneut geholt
    assert [p for p, c in aufrufe if c and p == [3836, 26]] == [[3836, 26]]
    assert [p for p, c in aufrufe if c and p != [3836, 26]] == [[3836], [3836, None], [3836, 0]]
    text = "\n".join(_text(s) for s in sonden) + "\n".join(probe.befund(sonden))
    assert "(b) Matrix-ID in getStudents: 2/3 (Key id)" in text and "wiederverwendet" in text
    for verboten in (CSRF_WERT, "Mueller", "Nobody", UUID_A):
        assert verboten not in text


def test_parse_args_abgleich_und_mit_db():
    args = probe.parse_args([])
    assert args.abgleich_klasse_id is None and args.mit_db is False
    args = probe.parse_args(["--klasse-id", "3836", "--abgleich-klasse-id", "3836", "--abgleich-klasse-id", "3837", "--mit-db"])
    assert args.abgleich_klasse_id == [3836, 3837] and args.mit_db is True


# --- getStudentDutyOptions (Dienst-Liste) ---


def test_optionen_struktur_liste_zeigt_laenge_und_drei_eintraege_mit_id_label():
    result = [{"id": i, "label": f"Dienst {i}", "x": 1} for i in range(1, 6)]
    zeilen = probe.optionen_struktur(result)
    assert zeilen[0] == "Top-Level: Liste" and "Laenge: 5" in zeilen
    eintraege = [z for z in zeilen if z.startswith("Eintrag:")]
    assert len(eintraege) == 3 and '"label": "Dienst 1"' in eintraege[0]


def test_optionen_struktur_objekt_mit_liste_und_unbekannte_form():
    zeilen = probe.optionen_struktur({"dutyOptions": [{"id": 26, "label": "Entschuldigungspflicht"}], "andere": 1})
    assert "Keys: ['andere', 'dutyOptions']" in zeilen[0]
    assert "Liste gefunden unter Key: dutyOptions" in zeilen and "Laenge: 1" in zeilen
    assert probe.optionen_struktur("text") == ["Top-Level: str"]
    assert "keine Liste enthalten" in probe.optionen_struktur({"a": 1})[-1]


@pytest.mark.asyncio
async def test_sonde_duty_bezeichnungen_postet_leere_params_mit_csrf():
    req: list = []
    antwort = httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "result": [{"id": 26, "label": "Entschuldigungspflicht"}]})
    async with _http_mit(_duty_handler(req, antwort)) as http:
        sonde = await probe.sonde_duty_bezeichnungen(http, _kontext(), "CSRF123456789012345")
    body = json.loads(req[0].content)
    assert body["method"] == "getStudentDutyOptions" and body["params"] == []
    assert req[0].headers["x-csrf-token"] == "CSRF123456789012345"
    assert sonde.ok and any("Entschuldigungspflicht" in z for z in sonde.zeilen)
    assert "CSRF1234567" not in _text(sonde)


@pytest.mark.asyncio
async def test_sonde_duty_bezeichnungen_ohne_csrf_wird_uebersprungen():
    async with _http_mit(lambda r: httpx.Response(500)) as http:
        sonde = await probe.sonde_duty_bezeichnungen(http, _kontext(), None)
    assert not sonde.ok and "uebersprungen" in sonde.zeilen[0]

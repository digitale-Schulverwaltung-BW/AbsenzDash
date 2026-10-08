import json
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

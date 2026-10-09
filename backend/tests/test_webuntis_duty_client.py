import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.webuntis_duty_client import (
    DutyOption,
    DutyServiceError,
    StudentDutyClient,
    extract_csrf,
    parse_duty_options,
)

SECRET_TOKEN = "tok-SECRET-1234567890abcdef"
INDEX_HTML = f"""<html><script>
var csrfToken = "{SECRET_TOKEN}";
var csrfHeader = "X-CSRF-TOKEN";
</script></html>"""


def test_extract_csrf_reads_token_and_header_name():
    assert extract_csrf(INDEX_HTML) == ("X-CSRF-TOKEN", SECRET_TOKEN)


def test_extract_csrf_accepts_other_header_name_and_json_style():
    html = """<script>window.cfg = {"csrfToken": "abc123def456", "csrfHeader": "X-Other-Token"};</script>"""
    assert extract_csrf(html) == ("X-Other-Token", "abc123def456")


def test_extract_csrf_defaults_header_when_variable_missing():
    assert extract_csrf("<script>var csrfToken = 'abc123def456';</script>") == ("X-CSRF-TOKEN", "abc123def456")


def test_extract_csrf_ignores_invalid_header_name():
    html = "<script>var csrfToken = 'abc123def456'; var csrfHeader = 'bad header\r\nx';</script>"
    assert extract_csrf(html)[0] == "X-CSRF-TOKEN"


def test_extract_csrf_missing_token_raises_classified_error():
    with pytest.raises(DutyServiceError) as exc_info:
        extract_csrf("<html>keine Variablen hier</html>")
    assert exc_info.value.kind == "csrf_missing"


def test_parse_duty_options_list_of_id_label():
    result = [{"id": 27, "label": "Pflicht zur Vorlage ärztl. Atteste"}, {"id": 26, "label": "Entschuldigungspflicht"}]
    assert parse_duty_options(result) == [
        DutyOption(26, "Entschuldigungspflicht"),
        DutyOption(27, "Pflicht zur Vorlage ärztl. Atteste"),
    ]


def test_parse_duty_options_object_with_duty_options_key():
    result = {"dutyOptions": [{"id": 1, "label": "Klassenordner"}], "other": 5}
    assert parse_duty_options(result) == [DutyOption(1, "Klassenordner")]


def test_parse_duty_options_other_list_key_and_name_field():
    assert parse_duty_options({"options": [{"id": "2", "name": "Klassensprecher"}]}) == [DutyOption(2, "Klassensprecher")]


def test_parse_duty_options_id_to_label_mapping():
    assert parse_duty_options({"26": "Entschuldigungspflicht"}) == [DutyOption(26, "Entschuldigungspflicht")]


@pytest.mark.parametrize("result", [None, "text", 5, [], {}, [1, 2], [{"id": "x", "label": "A"}], {"a": {"b": 1}}])
def test_parse_duty_options_unknown_shape_returns_empty(result):
    assert parse_duty_options(result) == []


class _FakeBase:
    def __init__(self, handler, students=None):
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.session_id = "SESSION123"
        self._students = students or []

    async def call(self, method, params):
        assert method == "getStudents"
        return self._students


SETTINGS = SimpleNamespace(webuntis_server="untis.test", webuntis_school="Meine Schule")
MATRIX = {"result": {"matrix": {"rows": [], "columns": []}}, "jsonrpc": "2.0", "id": 2}


def _handler(duty_responses, index_calls, duty_requests):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/WebUntis/index.do":
            index_calls.append(request)
            return httpx.Response(200, text=INDEX_HTML)
        duty_requests.append(request)
        status, body = duty_responses.pop(0)
        if status == 200:
            return httpx.Response(200, json=body)
        return httpx.Response(status, text="<html>forbidden</html>", headers={"content-type": "text/html"})

    return handler


async def test_scheduler_data_sends_csrf_and_expected_headers():
    index_calls, duty_requests = [], []
    base = _FakeBase(_handler([(200, MATRIX)], index_calls, duty_requests))
    client = StudentDutyClient(base, SETTINGS)
    result = await client.get_scheduler_data(3836, 26)
    assert result == MATRIX["result"]
    request = duty_requests[0]
    assert request.url == "https://untis.test/WebUntis/jsonrpc_web/jsonStudentDutyService"
    assert request.headers["X-CSRF-TOKEN"] == SECRET_TOKEN
    assert request.headers["X-Requested-With"] == "XMLHttpRequest"
    assert request.headers["Origin"] == "https://untis.test"
    assert request.headers["Referer"] == "https://untis.test/WebUntis/embedded.do?showSidebar=true"
    assert "JSESSIONID=SESSION123" in request.headers["Cookie"]
    assert "schoolname=" in request.headers["Cookie"]
    assert json.loads(request.content) == {
        "id": 2, "method": "getStudentDutySchedulerData", "params": [3836, 26], "jsonrpc": "2.0"
    }


async def test_csrf_fetched_once_per_run_and_reused():
    index_calls, duty_requests = [], []
    base = _FakeBase(_handler([(200, MATRIX), (200, MATRIX)], index_calls, duty_requests))
    client = StudentDutyClient(base, SETTINGS)
    await client.get_scheduler_data(1, 26)
    await client.get_scheduler_data(2, 26)
    assert len(index_calls) == 1


async def test_403_refetches_csrf_exactly_once_and_retries():
    index_calls, duty_requests = [], []
    base = _FakeBase(_handler([(403, None), (200, MATRIX)], index_calls, duty_requests))
    client = StudentDutyClient(base, SETTINGS)
    assert await client.get_scheduler_data(1, 26) == MATRIX["result"]
    assert len(index_calls) == 2  # initial + genau ein Neuholen
    assert len(duty_requests) == 2


async def test_403_twice_raises_forbidden_without_further_retries():
    index_calls, duty_requests = [], []
    base = _FakeBase(_handler([(403, None), (403, None), (200, MATRIX)], index_calls, duty_requests))
    client = StudentDutyClient(base, SETTINGS)
    with pytest.raises(DutyServiceError) as exc_info:
        await client.get_scheduler_data(1, 26)
    assert exc_info.value.kind == "forbidden"
    assert len(index_calls) == 2
    assert len(duty_requests) == 2


async def test_html_instead_of_json_is_login_required():
    base = _FakeBase(lambda r: httpx.Response(200, text=INDEX_HTML))
    client = StudentDutyClient(base, SETTINGS)
    with pytest.raises(DutyServiceError) as exc_info:
        await client.get_scheduler_data(1, 26)
    assert exc_info.value.kind == "login_required"


async def test_rpc_error_is_classified_and_message_has_no_token():
    def handler(request):
        if request.url.path == "/WebUntis/index.do":
            return httpx.Response(200, text=INDEX_HTML)
        return httpx.Response(200, json={"error": {"code": -32601, "message": "Method not found"}, "id": 2})

    client = StudentDutyClient(_FakeBase(handler), SETTINGS)
    with pytest.raises(DutyServiceError) as exc_info:
        await client.get_scheduler_data(1, 26)
    assert exc_info.value.kind == "rpc_error"
    assert SECRET_TOKEN not in str(exc_info.value)


async def test_missing_matrix_is_invalid_response():
    base = _FakeBase(_handler([(200, {"result": {"foo": 1}})], [], []))
    with pytest.raises(DutyServiceError) as exc_info:
        await StudentDutyClient(base, SETTINGS).get_scheduler_data(1, 26)
    assert exc_info.value.kind == "invalid_response"


async def test_missing_csrf_in_index_page_raises_csrf_missing():
    base = _FakeBase(lambda r: httpx.Response(200, text="<html>nothing</html>"))
    with pytest.raises(DutyServiceError) as exc_info:
        await StudentDutyClient(base, SETTINGS).get_scheduler_data(1, 26)
    assert exc_info.value.kind == "csrf_missing"


async def test_network_error_is_classified():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(DutyServiceError) as exc_info:
        await StudentDutyClient(_FakeBase(handler), SETTINGS).get_scheduler_data(1, 26)
    assert exc_info.value.kind == "network"


async def test_get_duty_options_calls_method_without_params_and_parses():
    seen = []

    def handler(request):
        if request.url.path == "/WebUntis/index.do":
            return httpx.Response(200, text=INDEX_HTML)
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"result": [{"id": 26, "label": "Entschuldigungspflicht"}]})

    options = await StudentDutyClient(_FakeBase(handler), SETTINGS).get_duty_options()
    assert options == [DutyOption(26, "Entschuldigungspflicht")]
    assert seen[0]["method"] == "getStudentDutyOptions"
    assert seen[0]["params"] == []


async def test_get_students_uses_base_client_call():
    base = _FakeBase(lambda r: httpx.Response(200), students=[{"id": 1, "key": "k"}])
    assert await StudentDutyClient(base, SETTINGS).get_students() == [{"id": 1, "key": "k"}]


async def test_token_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    index_calls, duty_requests = [], []
    base = _FakeBase(_handler([(403, None), (403, None)], index_calls, duty_requests))
    with pytest.raises(DutyServiceError):
        await StudentDutyClient(base, SETTINGS).get_scheduler_data(1, 26)
    assert SECRET_TOKEN not in caplog.text
    assert "SESSION123" not in caplog.text

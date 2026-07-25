import httpx
import pytest
import respx

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError

RPC_URL = "https://test.webuntis.com/WebUntis/jsonrpc.do"


@pytest.fixture(autouse=True)
def _set_webuntis_settings(monkeypatch):
    monkeypatch.setattr(settings, "webuntis_server", "test.webuntis.com")
    monkeypatch.setattr(settings, "webuntis_school", "test")
    monkeypatch.setattr(settings, "webuntis_username", "svc")
    monkeypatch.setattr(settings, "webuntis_password", "pw")


def _auth_route(session_id="sess-1"):
    return respx.post(RPC_URL, params={"school": "test"}, json__method="authenticate").mock(
        return_value=httpx.Response(200, json={"id": "auth", "result": {"sessionId": session_id}, "jsonrpc": "2.0"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_call_authenticates_and_returns_result():
    _auth_route()
    respx.post(RPC_URL, params={"school": "test"}, json__method="getKlassen").mock(
        return_value=httpx.Response(200, json={"id": "getKlassen", "result": [{"id": 1}], "jsonrpc": "2.0"})
    )
    respx.post(RPC_URL, params={"school": "test"}, json__method="logout").mock(
        return_value=httpx.Response(200, json={"id": "logout", "result": None, "jsonrpc": "2.0"})
    )

    async with WebUntisClient(settings) as client:
        result = await client.call("getKlassen", {})

    assert result == [{"id": 1}]


@pytest.mark.asyncio
@respx.mock
async def test_call_reauthenticates_once_on_session_expired():
    _auth_route(session_id="sess-1")
    call_route = respx.post(RPC_URL, params={"school": "test"}, json__method="getKlassen")
    call_route.side_effect = [
        httpx.Response(200, json={"id": "getKlassen", "error": {"code": -8520, "message": "expired"}, "jsonrpc": "2.0"}),
        httpx.Response(200, json={"id": "getKlassen", "result": [{"id": 2}], "jsonrpc": "2.0"}),
    ]
    respx.post(RPC_URL, params={"school": "test"}, json__method="logout").mock(
        return_value=httpx.Response(200, json={"id": "logout", "result": None, "jsonrpc": "2.0"})
    )

    async with WebUntisClient(settings) as client:
        result = await client.call("getKlassen", {})

    assert result == [{"id": 2}]
    assert call_route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_raises_on_login_failure():
    respx.post(RPC_URL, params={"school": "test"}, json__method="authenticate").mock(
        return_value=httpx.Response(200, json={"id": "auth", "error": {"code": -8504, "message": "bad credentials"}, "jsonrpc": "2.0"})
    )

    with pytest.raises(WebUntisError):
        async with WebUntisClient(settings):
            pass


@pytest.mark.asyncio
@respx.mock
async def test_context_manager_calls_logout_on_exit():
    _auth_route()
    logout_route = respx.post(RPC_URL, params={"school": "test"}, json__method="logout").mock(
        return_value=httpx.Response(200, json={"id": "logout", "result": None, "jsonrpc": "2.0"})
    )

    async with WebUntisClient(settings):
        pass

    assert logout_route.call_count == 1

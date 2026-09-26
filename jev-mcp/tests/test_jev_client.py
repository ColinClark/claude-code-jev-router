import httpx
import pytest

from jev_router.jev import JevClient, JevError

SECRET = "apikey_SYNTHETIC_TEST_SECRET"
OPTIONS = {"A": "a", "B": "b"}


def client(handler, monkeypatch, key=SECRET):
    if key:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    else:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return JevClient(env_file="/nonexistent/.env", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def ok(choice="A", confidence=0.9, qtype="choice"):
    return httpx.Response(
        200,
        json={
            "model": "jev",
            "answers": {
                "decision": {
                    "type": qtype,
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": {"A": confidence},
                }
            },
        },
    )


def test_sends_bearer_and_parses(monkeypatch):
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        return ok()

    ans = client(handler, monkeypatch).choice({"s": 1}, "q", OPTIONS)
    assert ans.choice == "A" and ans.confidence == 0.9
    assert seen["auth"] == f"Bearer {SECRET}"


@pytest.mark.parametrize(
    "resp",
    [
        ok(choice="Z"),
        ok(confidence=1.5),
        ok(qtype="noul"),
        httpx.Response(200, json={"answers": {}}),
        httpx.Response(200, text="nope"),
    ],
)
def test_malformed_replies_are_invalid_decision(monkeypatch, resp):
    with pytest.raises(JevError) as exc:
        client(lambda r: resp, monkeypatch).choice({}, "q", OPTIONS)
    assert exc.value.code == "INVALID_DECISION"


def test_auth_failure_not_retried_and_secret_not_leaked(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, text=f"bad key {SECRET}")

    with pytest.raises(JevError) as exc:
        client(handler, monkeypatch).choice({}, "q", OPTIONS)
    assert exc.value.code == "JEV_UNAVAILABLE" and len(calls) == 1
    assert SECRET not in str(exc.value) and SECRET not in repr(exc.value)


def test_one_retry_on_overload_then_success(monkeypatch):
    responses = [httpx.Response(529), ok()]
    assert client(lambda r: responses.pop(0), monkeypatch).choice({}, "q", OPTIONS).choice == "A"


def test_gives_up_after_one_retry(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectTimeout("t")

    with pytest.raises(JevError) as exc:
        client(handler, monkeypatch).choice({}, "q", OPTIONS)
    assert exc.value.code == "JEV_UNAVAILABLE" and len(calls) == 2


def test_missing_credentials(monkeypatch):
    with pytest.raises(JevError) as exc:
        client(lambda r: ok(), monkeypatch, key=None).choice({}, "q", OPTIONS)
    assert exc.value.code == "JEV_UNAVAILABLE"


def test_reads_env_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"# comment\nexport TYPESAFE_API_KEY='{SECRET}'\n")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        return ok()

    JevClient(env_file=str(env), transport=httpx.MockTransport(handler)).choice({}, "q", OPTIONS)
    assert seen["auth"] == f"Bearer {SECRET}"

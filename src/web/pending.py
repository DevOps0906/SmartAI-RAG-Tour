"""접수된 메시지(POST /chat, POST /plan)를 스트림 요청(GET /chat/stream, /planner)에 넘기는 서명 토큰.

서버리스(Vercel)에서는 POST 와 이어지는 GET 을 다른 인스턴스가 받을 수 있어 메모리 dict(PENDING)만으로는
전달되지 않는다. 그래서 같은 내용을 URL 의 p= 토큰으로도 넘긴다. trip 은 검증을 통과한 값이므로
HMAC 으로 서명해 클라이언트가 바꾸지 못하게 하고, thread_id 에 묶어 다른 대화에서 재사용하지 못하게 한다.
"""
import base64
import hashlib
import hmac
import json

from src.config import get_settings

MAX_TOKEN_LEN = 8000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    key = get_settings().web_secret.encode()
    return _b64(hmac.new(key, body.encode(), hashlib.sha256).digest()[:16])


def encode(thread_id: str, text: str, trip: dict | None = None) -> str:
    body = _b64(json.dumps({"tid": thread_id, "text": text, "trip": trip},
                           ensure_ascii=False, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def decode(token: str, thread_id: str) -> tuple[str, dict | None] | None:
    """(text, trip). 서명이 틀리거나 다른 thread 의 토큰이면 None."""
    if not token or len(token) > MAX_TOKEN_LEN or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("tid") != thread_id or not isinstance(data.get("text"), str):
        return None
    trip = data.get("trip")
    return data["text"], trip if isinstance(trip, dict) else None

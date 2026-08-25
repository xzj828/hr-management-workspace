import json
import re
import socket
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from accounts.crypto import decrypt_secret
from accounts.models import UserModelCredential


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelResult:
    data: dict
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def _json_content(value) -> dict:
    if not isinstance(value, str):
        raise ModelGatewayError("model_invalid_response", "模型未返回有效的 JSON 内容")
    content = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ModelGatewayError("model_invalid_response", "模型返回内容不是有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise ModelGatewayError("model_invalid_response", "模型返回的 JSON 顶层必须是对象")
    return parsed


class OpenAICompatibleGateway:
    def __init__(self, credential: UserModelCredential, *, timeout: int = 60):
        self.credential = credential
        self.timeout = timeout

    def _configuration(self):
        api_url = str(self.credential.api_url or "").strip().rstrip("/")
        model = str(self.credential.model or "").strip()
        try:
            api_key = decrypt_secret(self.credential.encrypted_api_key)
        except ValueError as exc:
            raise ModelGatewayError("model_credential_invalid", "已保存的模型密钥无法解密") from exc
        if not api_url or not model or not api_key:
            raise ModelGatewayError("model_not_configured", "请先完整配置 API 地址、模型名称和 API Key")
        return api_url, model, api_key

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        api_url, model, api_key = self._configuration()
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": str(system)},
                {"role": "user", "content": str(user)},
            ],
        }
        request = Request(
            f"{api_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ModelGatewayError("model_auth_failed", "模型服务拒绝了当前凭证") from exc
            if exc.code == 429:
                raise ModelGatewayError("model_rate_limited", "模型服务请求过于频繁，请稍后重试", retryable=True) from exc
            if exc.code >= 500:
                raise ModelGatewayError("model_unavailable", "模型服务暂时不可用", retryable=True) from exc
            raise ModelGatewayError("model_request_rejected", "模型服务拒绝了当前请求") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ModelGatewayError("model_timeout", "模型服务响应超时", retryable=True) from exc
        except (URLError, OSError) as exc:
            raise ModelGatewayError("model_unavailable", "无法连接模型服务", retryable=True) from exc
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ModelGatewayError("model_invalid_response", "模型服务返回了无效响应") from exc

        try:
            content = response_payload["choices"][0]["message"]["content"]
            usage = response_payload.get("usage") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelGatewayError("model_invalid_response", "模型响应缺少必要字段") from exc
        return ModelResult(
            data=_json_content(content),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    def test_connection(self) -> ModelResult:
        return self.complete_json(
            system="你是连接检查程序，只能返回 JSON 对象。",
            user='请只返回 {"ok": true}。',
        )

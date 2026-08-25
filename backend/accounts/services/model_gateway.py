import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection

from django.conf import settings

from accounts.crypto import decrypt_secret
from accounts.models import UserModelCredential, UserModelProfile
from accounts.services.model_endpoint import (
    ModelEndpointError,
    parse_model_endpoint,
    resolve_model_endpoint,
    validate_model_peer,
)


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


def _create_pinned_socket(addresses, port, timeout, source_address=None):
    last_error = None
    for address in sorted(addresses, key=lambda item: (item.version, int(item))):
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        candidate = socket.socket(family, socket.SOCK_STREAM)
        try:
            candidate.settimeout(timeout)
            if source_address:
                bind_address = source_address
                if family == socket.AF_INET6 and len(source_address) == 2:
                    bind_address = (source_address[0], source_address[1], 0, 0)
                candidate.bind(bind_address)
            destination = (str(address), port, 0, 0) if family == socket.AF_INET6 else (str(address), port)
            candidate.connect(destination)
            return candidate
        except OSError as exc:
            last_error = exc
            candidate.close()
    if last_error is not None:
        raise last_error
    raise OSError("no validated model endpoint address")


class OpenAICompatibleGateway:
    def __init__(self, credential: UserModelCredential | UserModelProfile, *, timeout: int = 60):
        self.credential = credential
        self.timeout = timeout

    def _configuration(self):
        api_url = str(self.credential.api_url or "").strip()
        model = str(self.credential.model or "").strip()
        encrypted_api_key = str(self.credential.encrypted_api_key or "").strip()
        if not api_url or not model or not encrypted_api_key:
            raise ModelGatewayError("model_not_configured", "请先完整配置 API 地址、模型名称和 API Key")
        try:
            endpoint = parse_model_endpoint(api_url)
        except ModelEndpointError as exc:
            raise ModelGatewayError(exc.code, str(exc), retryable=exc.retryable) from exc
        return endpoint, model, encrypted_api_key

    def _connect(self, endpoint, resolved_addresses):
        if endpoint.scheme == "https":
            connection = HTTPSConnection(
                endpoint.host,
                endpoint.port,
                timeout=self.timeout,
                context=ssl.create_default_context(),
            )
        else:
            connection = HTTPConnection(endpoint.host, endpoint.port, timeout=self.timeout)
        connection._create_connection = lambda _address, timeout, source_address: _create_pinned_socket(
            resolved_addresses,
            endpoint.port,
            timeout,
            source_address,
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise ModelEndpointError("model_endpoint_blocked", "无法验证模型服务连接对端")
            peer = connection.sock.getpeername()[0]
            validate_model_peer(endpoint, peer, resolved_addresses)
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _response_limit() -> int:
        try:
            configured = int(getattr(settings, "MODEL_API_MAX_RESPONSE_BYTES", 1024 * 1024))
        except (TypeError, ValueError):
            configured = 1024 * 1024
        return max(1, configured)

    def _read_response(self, response):
        status = int(response.status)
        if status in {401, 403}:
            raise ModelGatewayError("model_auth_failed", "模型服务拒绝了当前凭证")
        if status == 429:
            raise ModelGatewayError("model_rate_limited", "模型服务请求过于频繁，请稍后重试", retryable=True)
        if 500 <= status <= 599:
            raise ModelGatewayError("model_unavailable", "模型服务暂时不可用", retryable=True)
        if 300 <= status <= 399:
            raise ModelGatewayError("model_redirect_blocked", "模型服务重定向已被安全策略拒绝")
        if status < 200 or status >= 300:
            raise ModelGatewayError("model_request_rejected", "模型服务拒绝了当前请求")

        response_limit = self._response_limit()
        content_length = response.getheader("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > response_limit:
                raise ModelGatewayError("model_response_too_large", "模型服务响应超过安全大小限制")
        body = response.read(response_limit + 1)
        if len(body) > response_limit:
            raise ModelGatewayError("model_response_too_large", "模型服务响应超过安全大小限制")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ModelGatewayError("model_invalid_response", "模型服务返回了无效响应") from exc

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        started = time.monotonic()
        connection = None
        try:
            endpoint, model, encrypted_api_key = self._configuration()
            try:
                resolved_addresses = resolve_model_endpoint(endpoint)
            except ModelEndpointError as exc:
                raise ModelGatewayError(exc.code, str(exc), retryable=exc.retryable) from exc
            connection = self._connect(endpoint, resolved_addresses)
            try:
                api_key = decrypt_secret(encrypted_api_key)
            except ValueError as exc:
                raise ModelGatewayError("model_credential_invalid", "已保存的模型密钥无法解密") from exc
            if not api_key:
                raise ModelGatewayError("model_not_configured", "请先完整配置 API 地址、模型名称和 API Key")
            payload = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": str(system)},
                    {"role": "user", "content": str(user)},
                ],
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request(
                "POST",
                endpoint.chat_completions_path,
                body=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            response_payload = self._read_response(connection.getresponse())
        except ModelGatewayError:
            raise
        except ModelEndpointError as exc:
            raise ModelGatewayError(exc.code, str(exc), retryable=exc.retryable) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ModelGatewayError("model_timeout", "模型服务响应超时", retryable=True) from exc
        except (HTTPException, OSError) as exc:
            raise ModelGatewayError("model_unavailable", "无法连接模型服务", retryable=True) from exc
        except (UnicodeError, ValueError, TypeError, AttributeError) as exc:
            raise ModelGatewayError("model_invalid_response", "模型服务返回了无效响应") from exc
        finally:
            if connection is not None:
                connection.close()

        try:
            content = response_payload["choices"][0]["message"]["content"]
            usage = response_payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelGatewayError("model_invalid_response", "模型响应缺少必要字段") from exc
        return ModelResult(
            data=_json_content(content),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    def test_connection(self) -> ModelResult:
        return self.complete_json(
            system="你是连接检查程序，只能返回 JSON 对象。",
            user='请只返回 {"ok": true}。',
        )

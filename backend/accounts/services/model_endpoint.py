import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings


class ModelEndpointError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelEndpoint:
    scheme: str
    host: str
    port: int
    base_path: str
    canonical_url: str
    allowlisted: bool

    @property
    def chat_completions_path(self) -> str:
        return f"{self.base_path}/chat/completions" if self.base_path else "/chat/completions"


def _normalise_ip(value):
    address = ipaddress.ip_address(str(value).split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _normalise_host(value: str) -> str:
    host = str(value or "").strip().rstrip(".").lower()
    if not host or "%" in host:
        raise ValueError("invalid host")
    try:
        return _normalise_ip(host).compressed
    except ValueError:
        return host.encode("idna").decode("ascii")


def _parse_allowlist_entry(value):
    entry = str(value or "").strip()
    if not entry or "://" in entry or any(character.isspace() for character in entry):
        return None
    if entry.startswith("["):
        closing = entry.find("]")
        if closing <= 1:
            return None
        host_text = entry[1:closing]
        remainder = entry[closing + 1 :]
        if remainder:
            if not remainder.startswith(":") or not remainder[1:].isdigit():
                return None
            port = int(remainder[1:])
        else:
            port = None
    else:
        try:
            host_text = _normalise_ip(entry).compressed
            port = None
        except ValueError:
            if entry.count(":") == 1 and entry.rsplit(":", 1)[1].isdigit():
                host_text, port_text = entry.rsplit(":", 1)
                port = int(port_text)
            else:
                host_text, port = entry, None
    if port is not None and not 1 <= port <= 65535:
        return None
    try:
        return _normalise_host(host_text), port
    except (UnicodeError, ValueError):
        return None


def _configured_allowlist():
    configured = getattr(settings, "MODEL_API_HOST_ALLOWLIST", ())
    if isinstance(configured, str):
        configured = configured.split(",")
    return tuple(
        parsed
        for parsed in (_parse_allowlist_entry(entry) for entry in configured)
        if parsed is not None
    )


def _is_allowlisted(host: str, port: int) -> bool:
    return any(
        allowed_host == host and (allowed_port is None or allowed_port == port)
        for allowed_host, allowed_port in _configured_allowlist()
    )


def _is_restricted_ip(address) -> bool:
    return bool(
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def parse_model_endpoint(value) -> ModelEndpoint:
    raw_url = str(value or "").strip()
    if not raw_url or len(raw_url) > 500:
        raise ModelEndpointError("model_endpoint_invalid", "API 地址格式无效")
    if "\\" in raw_url or any(ord(character) < 32 or ord(character) == 127 for character in raw_url):
        raise ModelEndpointError("model_endpoint_invalid", "API 地址格式无效")
    try:
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid scheme or authority")
        if parsed.username is not None or parsed.password is not None:
            raise ModelEndpointError("model_endpoint_invalid", "API 地址不能包含用户凭据")
        if parsed.query or parsed.fragment:
            raise ModelEndpointError("model_endpoint_invalid", "API 地址不能包含查询参数或片段")
        if parsed.netloc.endswith(":"):
            raise ValueError("empty port")
        host = _normalise_host(parsed.hostname)
        parsed_port = parsed.port
        port = parsed_port if parsed_port is not None else (443 if scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
    except ModelEndpointError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise ModelEndpointError("model_endpoint_invalid", "API 地址格式无效") from exc

    allowlisted = _is_allowlisted(host, port)
    if scheme != "https" and not allowlisted:
        raise ModelEndpointError(
            "model_endpoint_blocked",
            "API 地址默认必须使用 HTTPS；本机或内网地址需由部署管理员显式允许",
        )
    if host == "localhost" or host.endswith(".localhost"):
        if not allowlisted:
            raise ModelEndpointError("model_endpoint_blocked", "API 地址指向受限网络")
    try:
        literal_ip = _normalise_ip(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and _is_restricted_ip(literal_ip) and not allowlisted:
        raise ModelEndpointError("model_endpoint_blocked", "API 地址指向受限网络")

    explicit_port = parsed_port is not None
    display_host = f"[{host}]" if ":" in host else host
    display_port = f":{port}" if explicit_port else ""
    base_path = parsed.path.rstrip("/")
    canonical_url = f"{scheme}://{display_host}{display_port}{base_path}"
    if len(canonical_url) > 500:
        raise ModelEndpointError("model_endpoint_invalid", "API 地址格式无效")
    return ModelEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        base_path=base_path,
        canonical_url=canonical_url,
        allowlisted=allowlisted,
    )


def resolve_model_endpoint(endpoint: ModelEndpoint):
    try:
        addresses = socket.getaddrinfo(
            endpoint.host,
            endpoint.port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (OSError, UnicodeError) as exc:
        raise ModelEndpointError(
            "model_endpoint_unavailable",
            "无法安全解析模型服务地址",
            retryable=True,
        ) from exc

    resolved = set()
    try:
        for _family, _socktype, _proto, _canonical_name, sockaddr in addresses:
            resolved.add(_normalise_ip(sockaddr[0]))
    except (IndexError, TypeError, ValueError) as exc:
        raise ModelEndpointError(
            "model_endpoint_unavailable",
            "无法安全解析模型服务地址",
            retryable=True,
        ) from exc
    if not resolved:
        raise ModelEndpointError(
            "model_endpoint_unavailable",
            "无法安全解析模型服务地址",
            retryable=True,
        )
    if not endpoint.allowlisted and any(_is_restricted_ip(address) for address in resolved):
        raise ModelEndpointError("model_endpoint_blocked", "模型服务解析到了受限网络地址")
    return frozenset(resolved)


def validate_model_peer(endpoint: ModelEndpoint, peer_value, resolved_addresses) -> None:
    try:
        peer = _normalise_ip(peer_value)
    except ValueError as exc:
        raise ModelEndpointError("model_endpoint_blocked", "无法验证模型服务连接对端") from exc
    if peer not in resolved_addresses:
        raise ModelEndpointError("model_endpoint_blocked", "模型服务连接对端与已验证地址不一致")
    if not endpoint.allowlisted and _is_restricted_ip(peer):
        raise ModelEndpointError("model_endpoint_blocked", "模型服务连接到了受限网络地址")


def validate_model_api_url(value) -> str:
    return parse_model_endpoint(value).canonical_url

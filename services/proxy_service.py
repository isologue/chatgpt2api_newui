"""Global outbound proxy and Cloudflare clearance helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import random
import re
import threading
import time
from typing import Callable, Mapping
from urllib import request as urllib_request
from urllib.parse import quote, urlparse

from curl_cffi.requests import Session

from services.config import config


FlareSolverrRequestMethod = Callable[[str, bytes, dict[str, str], float], bytes]

DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT = 30


def normalize_proxy_url(url: str) -> str:
    """Normalize proxy URLs for curl_cffi.

    SOCKS proxies should use remote-DNS resolution by default, so generic
    ``socks://`` and ``socks5://`` inputs are upgraded to ``socks5h://``.
    HTTP/HTTPS/socks5h inputs are otherwise left untouched except trimming.
    """
    candidate = str(url or "").strip()
    if candidate and "://" not in candidate:
        candidate = _colon_proxy_to_url(candidate)
    lowered = candidate.lower()
    if lowered.startswith("socks://"):
        return "socks5h://" + candidate[len("socks://") :]
    if lowered.startswith("socks5://"):
        return "socks5h://" + candidate[len("socks5://") :]
    return candidate


@dataclass(frozen=True)
class ProxyRuntimeProfile:
    proxy_url: str = ""
    proxy_source: str = "direct"
    egress_key: str = "direct"
    egress_label: str = "direct"
    proxy_group_id: str = ""
    proxy_node_id: str = ""
    proxy_node_name: str = ""
    image_concurrency_limit: int = 0
    image_egress_reserved: bool = False
    image_egress_wait_ms: int = 0
    resource: bool = False
    runtime_enabled: bool = False
    egress_mode: str = "direct"
    skip_ssl_verify: bool = False
    reset_session_status_codes: tuple[int, ...] = field(default_factory=lambda: (403,))
    clearance: dict[str, object] = field(default_factory=dict, repr=False)

    @property
    def clearance_enabled(self) -> bool:
        return (
            self.runtime_enabled
            and bool(self.clearance.get("enabled"))
            and self.clearance_mode in {"manual", "flaresolverr"}
        )

    @property
    def clearance_mode(self) -> str:
        return str(self.clearance.get("mode") or "none").strip().lower()

    @property
    def refresh_interval(self) -> int:
        try:
            return max(0, int(self.clearance.get("refresh_interval") or 0))
        except (OverflowError, TypeError, ValueError):
            return 0

    @property
    def timeout_sec(self) -> int:
        try:
            return max(1, int(self.clearance.get("timeout_sec") or 60))
        except (OverflowError, TypeError, ValueError):
            return 60


@dataclass(frozen=True)
class ClearanceBundle:
    target_host: str
    proxy_url: str = ""
    proxy_source: str = "direct"
    egress_key: str = "direct"
    egress_label: str = "direct"
    cookies: dict[str, str] = field(default_factory=dict, repr=False)
    user_agent: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_valid_for(self, target_host: str, proxy_url: str, *, now: float | None = None) -> bool:
        host = _normalize_host(target_host)
        if self.target_host and host and _normalize_host(self.target_host) != host:
            return False
        if normalize_proxy_url(self.proxy_url) != normalize_proxy_url(proxy_url):
            return False
        if self.expires_at is not None and (time.time() if now is None else now) >= self.expires_at:
            return False
        return bool(self.cookies or self.user_agent)

    def cookie_header(self) -> str:
        return _cookies_to_header(self.cookies)


@dataclass
class ImageEgressCircuitState:
    """生图出口熔断状态，仅保存在当前进程内存中。"""

    failure_times: list[float] = field(default_factory=list)
    opened_until: float = 0.0
    half_open_probe: bool = False


@dataclass(frozen=True)
class ProxyGroupSelection:
    proxy_url: str = ""
    group_id: str = ""
    node_id: str = ""
    node_name: str = ""
    image_concurrency_limit: int = 0
    image_egress_reserved: bool = False
    image_egress_wait_ms: int = 0

    @property
    def egress_key(self) -> str:
        if self.group_id and self.node_id:
            return f"group:{self.group_id}:{self.node_id}"
        return _egress_key_for_proxy(self.proxy_url)

    @property
    def egress_label(self) -> str:
        if self.group_id and self.node_id:
            return f"{self.group_id}/{self.node_name or self.node_id}"
        return _egress_key_for_proxy(self.proxy_url)


@dataclass(frozen=True)
class ResolvedProxyReference:
    proxy_url: str = ""
    source: str = "direct"
    terminal: bool = False
    egress_key: str = "direct"
    egress_label: str = "direct"
    proxy_group_id: str = ""
    proxy_node_id: str = ""
    proxy_node_name: str = ""
    image_concurrency_limit: int = 0
    image_egress_reserved: bool = False
    image_egress_wait_ms: int = 0


class FlareSolverrClearanceProvider:
    def __init__(self, flaresolverr_url: str, request_method: FlareSolverrRequestMethod | None = None) -> None:
        self.flaresolverr_url = str(flaresolverr_url or "").strip().rstrip("/")
        self._request_method = request_method or self._urllib_post

    def get_clearance(self, target_url: str, proxy_url: str = "", timeout_sec: int = 60) -> ClearanceBundle | None:
        if not self.flaresolverr_url:
            return None

        timeout = _coerce_timeout(timeout_sec)
        payload: dict[str, object] = {
            "cmd": "request.get",
            "url": str(target_url or ""),
            "maxTimeout": int(timeout * 1000),
        }
        proxy_url = normalize_proxy_url(proxy_url)
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}

        endpoint = f"{self.flaresolverr_url}/v1"
        try:
            body = json.dumps(payload).encode("utf-8")
            raw_response = self._request_method(
                endpoint,
                body,
                {"Content-Type": "application/json"},
                timeout,
            )
            data = json.loads(raw_response.decode("utf-8") if isinstance(raw_response, bytes) else raw_response)
        except Exception:
            return None

        if not isinstance(data, dict) or str(data.get("status") or "").lower() != "ok":
            return None
        solution = data.get("solution")
        if not isinstance(solution, dict):
            return None

        target_host = _host_from_url(target_url)
        cookies = _filter_flaresolverr_cookies(solution.get("cookies"), target_host)
        user_agent = str(solution.get("userAgent") or "").strip()
        if not cookies and not user_agent:
            return None
        return ClearanceBundle(
            target_host=target_host,
            proxy_url=proxy_url,
            cookies=cookies,
            user_agent=user_agent,
        )

    @staticmethod
    def _urllib_post(endpoint: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
        req = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return response.read()


class ProxySettingsStore:
    def __init__(
        self,
        config_store=None,
        clearance_provider_factory: Callable[[str], FlareSolverrClearanceProvider] | None = None,
    ) -> None:
        self._config = config_store or config
        self._clearance_provider_factory = clearance_provider_factory or FlareSolverrClearanceProvider
        self._clearance_cache: dict[tuple[str, str], ClearanceBundle] = {}
        self._provider_cache: dict[str, FlareSolverrClearanceProvider] = {}
        self._flight_locks: dict[tuple[str, str], threading.Lock] = {}
        self._egress_inflight: dict[str, int] = {}
        self._image_egress_circuits: dict[str, ImageEgressCircuitState] = {}
        self._route_metrics: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()
        self._egress_condition = threading.Condition(self._lock)

    def get_profile(
        self,
        account: dict | None = None,
        proxy: str = "",
        resource: bool = False,
        upstream: bool = False,
        reserve_image_egress: bool = False,
    ) -> ProxyRuntimeProfile:
        runtime = self._get_runtime_settings()
        clearance = dict(runtime.get("clearance") if isinstance(runtime.get("clearance"), dict) else {})
        runtime_enabled = bool(runtime.get("enabled"))
        egress_mode = str(runtime.get("egress_mode") or "direct").strip().lower()

        runtime_reference = ""
        runtime_proxy_source = "runtime"
        force_runtime_route = False
        if upstream and runtime_enabled and egress_mode in {"single_proxy", "split_proxy"}:
            control_proxy = _clean(runtime.get("control_proxy_url")) or _clean(runtime.get("proxy_url"))
            resource_proxy = _clean(runtime.get("resource_proxy_url"))
            if egress_mode == "split_proxy":
                # A/B 模式强制按用途分流：控制请求走 B，资源请求走 A；
                # A 未配置时资源请求明确回落到 B，避免账号个人代理或旧版全局出口接管。
                runtime_reference = resource_proxy if resource and resource_proxy else control_proxy
                force_runtime_route = bool(runtime_reference)
                runtime_proxy_source = "runtime_resource_a" if resource and resource_proxy else (
                    "runtime_control_b" if control_proxy else "runtime_control"
                )
            else:
                # 单代理模式下控制流和图片资源流必须使用同一个主代理，
                # 不读取账号个人代理或曾经保存的 A/B 字段，确保模式语义一致。
                runtime_reference = control_proxy
                force_runtime_route = bool(control_proxy)
                runtime_proxy_source = "runtime_single_proxy"

        selected_proxy = ""
        source = "direct"
        terminal = False
        egress_key = "direct"
        egress_label = "direct"
        proxy_group_id = ""
        proxy_node_id = ""
        proxy_node_name = ""
        image_concurrency_limit = 0
        image_egress_reserved = False
        image_egress_wait_ms = 0

        # 单代理和 A/B 分流都是显式运行时路由：选中后覆盖账号个人代理、
        # 账号组代理和旧版全局出口；切回 direct 才恢复账号级路由规则。
        if force_runtime_route:
            resolved = self._resolve_proxy_reference(
                runtime_reference,
                source=runtime_proxy_source,
                terminal_when_unresolved=True,
                reserve_image_egress=reserve_image_egress and not resource,
            )
            selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
            egress_key = resolved.egress_key
            egress_label = resolved.egress_label
            proxy_group_id = resolved.proxy_group_id
            proxy_node_id = resolved.proxy_node_id
            proxy_node_name = resolved.proxy_node_name
            image_concurrency_limit = resolved.image_concurrency_limit
            image_egress_reserved = resolved.image_egress_reserved
            image_egress_wait_ms = resolved.image_egress_wait_ms

        account_proxy = _clean((account or {}).get("proxy") if isinstance(account, dict) else "")
        if account_proxy and not selected_proxy and not terminal:
            resolved = self._resolve_proxy_reference(
                account_proxy,
                source="account",
                terminal_when_unresolved=True,
                reserve_image_egress=reserve_image_egress,
            )
            selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
            egress_key = resolved.egress_key
            egress_label = resolved.egress_label
            proxy_group_id = resolved.proxy_group_id
            proxy_node_id = resolved.proxy_node_id
            proxy_node_name = resolved.proxy_node_name
            image_concurrency_limit = resolved.image_concurrency_limit
            image_egress_reserved = resolved.image_egress_reserved
            image_egress_wait_ms = resolved.image_egress_wait_ms

        if not selected_proxy and not terminal:
            account_group_proxy = self._account_group_proxy_reference(account)
            if account_group_proxy:
                resolved = self._resolve_proxy_reference(
                    account_group_proxy,
                    source="account_group",
                    terminal_when_unresolved=False,
                    reserve_image_egress=reserve_image_egress,
                )
                selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
                egress_key = resolved.egress_key
                egress_label = resolved.egress_label
                proxy_group_id = resolved.proxy_group_id
                proxy_node_id = resolved.proxy_node_id
                proxy_node_name = resolved.proxy_node_name
                image_concurrency_limit = resolved.image_concurrency_limit
                image_egress_reserved = resolved.image_egress_reserved
                image_egress_wait_ms = resolved.image_egress_wait_ms

        if not selected_proxy and not terminal:
            explicit_proxy = _clean(proxy)
            if explicit_proxy:
                resolved = self._resolve_proxy_reference(
                    explicit_proxy,
                    source="explicit",
                    terminal_when_unresolved=True,
                    reserve_image_egress=reserve_image_egress,
                )
                selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
                egress_key = resolved.egress_key
                egress_label = resolved.egress_label
                proxy_group_id = resolved.proxy_group_id
                proxy_node_id = resolved.proxy_node_id
                proxy_node_name = resolved.proxy_node_name
                image_concurrency_limit = resolved.image_concurrency_limit
                image_egress_reserved = resolved.image_egress_reserved
                image_egress_wait_ms = resolved.image_egress_wait_ms

        # 兼容没有形成强制运行时路由的旧配置；新版 single_proxy/split_proxy
        # 在上方已经按用途选定出口，不会再走到这里。
        if not selected_proxy and not terminal and runtime_reference:
            resolved = self._resolve_proxy_reference(
                runtime_reference,
                source=runtime_proxy_source,
                terminal_when_unresolved=True,
                reserve_image_egress=reserve_image_egress and not resource,
            )
            selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
            egress_key = resolved.egress_key
            egress_label = resolved.egress_label
            proxy_group_id = resolved.proxy_group_id
            proxy_node_id = resolved.proxy_node_id
            proxy_node_name = resolved.proxy_node_name
            image_concurrency_limit = resolved.image_concurrency_limit
            image_egress_reserved = resolved.image_egress_reserved
            image_egress_wait_ms = resolved.image_egress_wait_ms

        # 仅当新运行时没有指定该用途出口时，才兼容旧版全局 proxy。
        if not selected_proxy and not terminal:
            legacy_proxy = _clean(self._config.get_proxy_settings())
            if legacy_proxy:
                resolved = self._resolve_proxy_reference(
                    legacy_proxy,
                    source="default",
                    terminal_when_unresolved=False,
                    reserve_image_egress=reserve_image_egress,
                )
                selected_proxy, source, terminal = resolved.proxy_url, resolved.source, resolved.terminal
                egress_key = resolved.egress_key
                egress_label = resolved.egress_label
                proxy_group_id = resolved.proxy_group_id
                proxy_node_id = resolved.proxy_node_id
                proxy_node_name = resolved.proxy_node_name
                image_concurrency_limit = resolved.image_concurrency_limit
                image_egress_reserved = resolved.image_egress_reserved
                image_egress_wait_ms = resolved.image_egress_wait_ms

        return ProxyRuntimeProfile(
            proxy_url=normalize_proxy_url(selected_proxy),
            proxy_source=source,
            egress_key=egress_key or _egress_key_for_proxy(selected_proxy),
            egress_label=egress_label or source,
            proxy_group_id=proxy_group_id,
            proxy_node_id=proxy_node_id,
            proxy_node_name=proxy_node_name,
            image_concurrency_limit=max(0, int(image_concurrency_limit or 0)),
            image_egress_reserved=bool(image_egress_reserved),
            image_egress_wait_ms=max(0, int(image_egress_wait_ms or 0)),
            resource=bool(resource),
            runtime_enabled=runtime_enabled,
            egress_mode=egress_mode,
            skip_ssl_verify=bool(runtime.get("skip_ssl_verify")),
            reset_session_status_codes=_status_codes_tuple(runtime.get("reset_session_status_codes")),
            clearance=clearance,
        )

    def get_registration_profile(
        self,
        proxy: str = "",
        clearance: Mapping[str, object] | None = None,
    ) -> ProxyRuntimeProfile:
        """Resolve one fixed outbound route for a complete registration task.

        Registration has its own proxy selector. Explicit direct/group/custom
        choices must not be overridden by the image/control runtime route. The
        special ``global`` choice intentionally follows the current global
        control route, but is resolved only once so a proxy-group task keeps the
        same node for both auth requests and Cloudflare clearance.
        """
        reference = _clean(proxy)
        if not reference or reference.lower() == "global":
            profile = self.get_profile(upstream=True)
            return replace(
                profile,
                proxy_source=f"register_{profile.proxy_source}",
                resource=False,
                runtime_enabled=True,
                clearance=dict(clearance or {}),
            )

        resolved = self._resolve_proxy_reference(
            reference,
            source="register",
            terminal_when_unresolved=True,
        )
        runtime = self._get_runtime_settings()
        return ProxyRuntimeProfile(
            proxy_url=resolved.proxy_url,
            proxy_source=resolved.source,
            egress_key=resolved.egress_key,
            egress_label=resolved.egress_label,
            proxy_group_id=resolved.proxy_group_id,
            proxy_node_id=resolved.proxy_node_id,
            proxy_node_name=resolved.proxy_node_name,
            runtime_enabled=True,
            egress_mode="registration",
            skip_ssl_verify=bool(runtime.get("skip_ssl_verify")),
            reset_session_status_codes=_status_codes_tuple(runtime.get("reset_session_status_codes")),
            clearance=dict(clearance or {}),
        )

    def get_fallback_proxy_reference(self, *, resource: bool = False) -> str:
        runtime = self._get_runtime_settings()
        if bool(runtime.get("enabled")):
            egress_mode = str(runtime.get("egress_mode") or "direct").strip().lower()
            if egress_mode == "direct":
                # 新版直连模式不再继承旧版备用出口，确保选择即语义明确。
                return ""
            if resource and egress_mode == "split_proxy":
                reference = _clean(runtime.get("resource_fallback_proxy_url"))
            else:
                # 单代理模式的控制流和资源流共用同一个备用代理；
                # A/B 分流的控制流则使用控制备用出口。
                reference = _clean(runtime.get("control_fallback_proxy_url"))
            if reference:
                return "" if reference.lower() == "global" else reference
            # 运行时路由已启用时，不再让隐藏的旧版 fallback_proxy 接管。
            return ""
        try:
            reference = _clean(self._config.get_proxy_fallback_settings())
        except AttributeError:
            data = getattr(self._config, "data", None)
            reference = _clean(data.get("fallback_proxy")) if isinstance(data, dict) else ""
        return "" if reference.lower() == "global" else reference

    def get_fallback_profile(
        self,
        *,
        resource: bool = False,
        upstream: bool = False,
        reserve_image_egress: bool = False,
    ) -> ProxyRuntimeProfile | None:
        reference = self.get_fallback_proxy_reference(resource=resource)
        if not reference:
            return None
        runtime = self._get_runtime_settings()
        clearance = dict(runtime.get("clearance") if isinstance(runtime.get("clearance"), dict) else {})
        resolved = self._resolve_proxy_reference(
            reference,
            source="resource_fallback" if resource else "control_fallback",
            terminal_when_unresolved=True,
            reserve_image_egress=reserve_image_egress and not resource,
        )
        source = str(resolved.source or ("resource_fallback" if resource else "control_fallback")).strip()
        label = str(resolved.egress_label or source).strip() or source
        return ProxyRuntimeProfile(
            proxy_url=normalize_proxy_url(resolved.proxy_url),
            proxy_source=source,
            egress_key=resolved.egress_key or _egress_key_for_proxy(resolved.proxy_url),
            egress_label=label,
            proxy_group_id=resolved.proxy_group_id,
            proxy_node_id=resolved.proxy_node_id,
            proxy_node_name=resolved.proxy_node_name,
            image_concurrency_limit=max(0, int(resolved.image_concurrency_limit or 0)),
            image_egress_reserved=bool(resolved.image_egress_reserved),
            image_egress_wait_ms=max(0, int(resolved.image_egress_wait_ms or 0)),
            resource=bool(resource),
            runtime_enabled=bool(runtime.get("enabled")),
            egress_mode=str(runtime.get("egress_mode") or "direct").strip().lower(),
            skip_ssl_verify=bool(runtime.get("skip_ssl_verify")),
            reset_session_status_codes=_status_codes_tuple(runtime.get("reset_session_status_codes")),
            clearance=clearance,
        )

    def build_session_kwargs(
        self,
        account: dict | None = None,
        proxy: str = "",
        resource: bool = False,
        upstream: bool = False,
        **session_kwargs,
    ) -> dict[str, object]:
        profile = self.get_profile(account=account, proxy=proxy, resource=resource, upstream=upstream)
        if profile.proxy_url:
            session_kwargs["proxy"] = profile.proxy_url
        if profile.skip_ssl_verify:
            session_kwargs["verify"] = False
        return session_kwargs

    @staticmethod
    def build_session_kwargs_from_profile(
        profile: ProxyRuntimeProfile,
        **session_kwargs,
    ) -> dict[str, object]:
        if profile.proxy_url:
            session_kwargs["proxy"] = profile.proxy_url
        if profile.skip_ssl_verify:
            session_kwargs["verify"] = False
        return session_kwargs

    def build_headers(
        self,
        headers: Mapping[str, object] | None = None,
        target_url: str = "https://chatgpt.com",
        account: dict | None = None,
        proxy: str = "",
        resource: bool = False,
        upstream: bool = True,
        clearance_proxy_url: str = "",
        profile: ProxyRuntimeProfile | None = None,
    ) -> dict[str, object]:
        merged_headers: dict[str, object] = dict(headers or {})
        profile = profile or self.get_profile(account=account, proxy=proxy, resource=resource, upstream=upstream)
        if not profile.clearance_enabled:
            return merged_headers

        target_host = _host_from_url(target_url)
        bundle_proxy_url = normalize_proxy_url(clearance_proxy_url) or profile.proxy_url
        if clearance_proxy_url:
            bundle = self._get_cached_bundle(self._cache_key(bundle_proxy_url, target_host))
        else:
            bundle = self._bundle_for_headers(profile, target_host)
        if bundle is None or not bundle.is_valid_for(target_host, bundle_proxy_url):
            return merged_headers

        if bundle.user_agent and _find_header_key(merged_headers, "user-agent") is None:
            merged_headers["User-Agent"] = bundle.user_agent

        if bundle.cookies:
            cookie_key = _find_header_key(merged_headers, "cookie") or "Cookie"
            existing_cookie = str(merged_headers.get(cookie_key) or "")
            cookie_header = _merge_cookie_header(existing_cookie, bundle.cookies)
            if cookie_header:
                merged_headers[cookie_key] = cookie_header
        return merged_headers

    def refresh_clearance(
        self,
        target_url: str = "https://chatgpt.com",
        account: dict | None = None,
        proxy: str = "",
        resource: bool = False,
        force: bool = False,
        upstream: bool = True,
        profile: ProxyRuntimeProfile | None = None,
    ) -> ClearanceBundle | None:
        primary_profile = profile or self.get_profile(
            account=account,
            proxy=proxy,
            resource=resource,
            upstream=upstream,
        )
        if not primary_profile.clearance_enabled:
            return None

        target_host = _host_from_url(target_url)
        primary_key = self._cache_key(primary_profile.proxy_url, target_host)
        if primary_profile.clearance_mode == "manual":
            bundle = self._build_manual_bundle(primary_profile, target_host)
            if bundle is not None:
                self._set_cached_bundle(primary_key, bundle)
            return bundle
        if primary_profile.clearance_mode != "flaresolverr":
            return None

        stale_bundles: list[ClearanceBundle] = []
        attempt_errors: list[str] = []
        for profile in (primary_profile,):
            key = self._cache_key(profile.proxy_url, target_host)
            cached_before = self._get_cached_bundle(key)
            if cached_before is not None and not force and cached_before.is_valid_for(target_host, profile.proxy_url):
                return cached_before

            lock = self._get_flight_lock(key)
            if not lock.acquire(blocking=False):
                with lock:
                    pass
                cached_after_wait = self._get_cached_bundle(key)
                if cached_after_wait is not None and cached_after_wait.is_valid_for(target_host, profile.proxy_url):
                    return cached_after_wait
                if cached_before is not None:
                    stale_bundles.append(cached_before)
                continue

            try:
                cached_now = self._get_cached_bundle(key)
                if cached_now is not None and not force and cached_now.is_valid_for(target_host, profile.proxy_url):
                    return cached_now

                flaresolverr_url = str(profile.clearance.get("flaresolverr_url") or "").strip()
                provider = self._get_provider(flaresolverr_url)
                try:
                    new_bundle = provider.get_clearance(
                        target_url,
                        proxy_url=profile.proxy_url,
                        timeout_sec=profile.timeout_sec,
                    )
                except Exception as exc:
                    error = _redact_url_credentials(str(exc) or exc.__class__.__name__)
                    attempt_errors.append(f"{profile.egress_label}: {error}")
                    if cached_now is not None:
                        stale_bundles.append(cached_now)
                    elif cached_before is not None:
                        stale_bundles.append(cached_before)
                    continue

                if new_bundle is not None:
                    expires_at = time.time() + profile.refresh_interval if profile.refresh_interval else None
                    new_bundle = replace(
                        new_bundle,
                        target_host=new_bundle.target_host or target_host,
                        proxy_url=profile.proxy_url,
                        proxy_source=profile.proxy_source,
                        egress_key=profile.egress_key,
                        egress_label=profile.egress_label,
                        expires_at=expires_at,
                    )
                    self._set_cached_bundle(key, new_bundle)
                    return new_bundle
                if cached_now is not None:
                    stale_bundles.append(cached_now)
                elif cached_before is not None:
                    stale_bundles.append(cached_before)
            finally:
                lock.release()

        # FlareSolverr 与注册请求必须使用同一个实际出口；刷新失败时只允许
        # 回退到该出口已有的旧缓存，不能切换到生图控制流的备用出口。
        if stale_bundles:
            return stale_bundles[0]
        if attempt_errors:
            raise RuntimeError("clearance refresh failed: " + "; ".join(attempt_errors))
        return None

    def invalidate_clearance(
        self,
        target_url: str = "https://chatgpt.com",
        account: dict | None = None,
        proxy: str = "",
        resource: bool = False,
        upstream: bool = True,
    ) -> None:
        profile = self.get_profile(account=account, proxy=proxy, resource=resource, upstream=upstream)
        target_host = _host_from_url(target_url)
        key = self._cache_key(profile.proxy_url, target_host)
        with self._lock:
            self._clearance_cache.pop(key, None)

    def route_request_started(self, lane: str, profile: ProxyRuntimeProfile) -> float:
        """记录 A/B 出口请求开始，只保存脱敏出口标识。"""
        normalized_lane = "resource" if str(lane).lower() == "resource" else "control"
        started = time.perf_counter()
        with self._lock:
            metric = self._route_metrics.setdefault(normalized_lane, {
                "inflight": 0,
                "total": 0,
                "success": 0,
                "failed": 0,
                "fallback": 0,
                "total_ms": 0,
                "max_ms": 0,
                "last_ms": 0,
                "last_error": "",
                "last_egress_key": "direct",
                "last_egress_label": "direct",
                "updated_at": 0,
            })
            metric["inflight"] = int(metric.get("inflight") or 0) + 1
            metric["last_egress_key"] = str(profile.egress_key or "direct")
            metric["last_egress_label"] = str(profile.egress_label or profile.proxy_source or "direct")
        return started

    def route_request_finished(
        self,
        lane: str,
        profile: ProxyRuntimeProfile,
        started: float,
        *,
        success: bool,
        fallback: bool = False,
        error: object = "",
    ) -> int:
        """完成一次出口请求统计，供代理管理页实时查看 A/B 健康。"""
        normalized_lane = "resource" if str(lane).lower() == "resource" else "control"
        duration_ms = max(0, int((time.perf_counter() - float(started or time.perf_counter())) * 1000))
        with self._lock:
            metric = self._route_metrics.setdefault(normalized_lane, {})
            metric["inflight"] = max(0, int(metric.get("inflight") or 0) - 1)
            metric["total"] = int(metric.get("total") or 0) + 1
            key = "success" if success else "failed"
            metric[key] = int(metric.get(key) or 0) + 1
            if fallback:
                metric["fallback"] = int(metric.get("fallback") or 0) + 1
            metric["total_ms"] = int(metric.get("total_ms") or 0) + duration_ms
            metric["max_ms"] = max(int(metric.get("max_ms") or 0), duration_ms)
            metric["last_ms"] = duration_ms
            metric["last_error"] = "" if success else str(error or "")[:300]
            metric["last_egress_key"] = str(profile.egress_key or "direct")
            metric["last_egress_label"] = str(profile.egress_label or profile.proxy_source or "direct")
            metric["updated_at"] = int(time.time())
        return duration_ms

    def _route_metrics_status(self) -> dict[str, dict[str, object]]:
        with self._lock:
            result: dict[str, dict[str, object]] = {}
            for lane in ("control", "resource"):
                metric = {
                    "inflight": 0,
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "fallback": 0,
                    "total_ms": 0,
                    "max_ms": 0,
                    "last_ms": 0,
                    "last_error": "",
                    "last_egress_key": "direct",
                    "last_egress_label": "direct",
                    "updated_at": 0,
                    **dict(self._route_metrics.get(lane) or {}),
                }
                total = max(0, int(metric.get("total") or 0))
                total_ms = max(0, int(metric.get("total_ms") or 0))
                metric["avg_ms"] = int(total_ms / total) if total else 0
                metric.pop("total_ms", None)
                result[lane] = metric
            return result

    def get_runtime_status(self) -> dict[str, object]:
        control = self.get_profile(upstream=True, resource=False)
        resource = self.get_profile(upstream=True, resource=True)
        with self._lock:
            cached_hosts = [host for _proxy, host in self._clearance_cache]
            cached_count = len(self._clearance_cache)
        return {
            "enabled": control.runtime_enabled,
            "egress_mode": control.egress_mode,
            "proxy_source": control.proxy_source,
            "egress_key": control.egress_key,
            "egress_label": control.egress_label,
            "control_egress_key": control.egress_key,
            "control_egress_label": control.egress_label,
            "resource_egress_key": resource.egress_key,
            "resource_egress_label": resource.egress_label,
            "control_proxy_source": control.proxy_source,
            "resource_proxy_source": resource.proxy_source,
            "image_concurrency_limit": control.image_concurrency_limit,
            "has_proxy": bool(control.proxy_url),
            "has_control_proxy": bool(control.proxy_url),
            "has_resource_proxy": bool(resource.proxy_url),
            "skip_ssl_verify": control.skip_ssl_verify,
            "clearance_enabled": control.clearance_enabled,
            "clearance_mode": control.clearance_mode,
            "has_clearance_bundle": cached_count > 0,
            "cached_clearance_hosts": sorted(set(cached_hosts)),
            "route_metrics": self._route_metrics_status(),
        }

    def should_skip_ssl_verify(self) -> bool:
        return bool(self._get_runtime_settings().get("skip_ssl_verify"))

    def image_egress_circuit_decision(self, profile: ProxyRuntimeProfile) -> dict[str, object]:
        """判断新生图请求是否应绕过当前出口改走备用出口。"""
        enabled = bool(getattr(self._config, "image_egress_circuit_breaker_enabled", True))
        key = self._image_egress_key(profile)
        now = time.monotonic()
        with self._lock:
            if not enabled:
                self._image_egress_circuits.clear()
                return {
                    "enabled": False,
                    "state": "disabled",
                    "egress_key": key,
                    "route_fallback": False,
                    "half_open_probe": False,
                    "remaining_seconds": 0,
                }

            state = self._image_egress_circuits.get(key)
            if state is None:
                return {
                    "enabled": True,
                    "state": "closed",
                    "egress_key": key,
                    "route_fallback": False,
                    "half_open_probe": False,
                    "remaining_seconds": 0,
                }

            self._prune_image_egress_failures(state, now)
            if state.opened_until > now:
                return {
                    "enabled": True,
                    "state": "open",
                    "egress_key": key,
                    "route_fallback": True,
                    "half_open_probe": False,
                    "remaining_seconds": max(1, int(state.opened_until - now + 0.999)),
                }

            if state.opened_until > 0:
                if not state.half_open_probe:
                    state.half_open_probe = True
                    return {
                        "enabled": True,
                        "state": "half_open",
                        "egress_key": key,
                        "route_fallback": False,
                        "half_open_probe": True,
                        "remaining_seconds": 0,
                    }
                return {
                    "enabled": True,
                    "state": "half_open",
                    "egress_key": key,
                    "route_fallback": True,
                    "half_open_probe": False,
                    "remaining_seconds": 0,
                }

            if not state.failure_times:
                self._image_egress_circuits.pop(key, None)
            return {
                "enabled": True,
                "state": "closed",
                "egress_key": key,
                "route_fallback": False,
                "half_open_probe": False,
                "remaining_seconds": 0,
            }

    def record_image_egress_failure(
        self,
        profile: ProxyRuntimeProfile,
        failure_code: str,
        *,
        half_open_probe: bool = False,
    ) -> dict[str, object]:
        """记录主出口故障；达到阈值时开路，半开探测失败时重新开路。"""
        enabled = bool(getattr(self._config, "image_egress_circuit_breaker_enabled", True))
        key = self._image_egress_key(profile)
        if not enabled:
            with self._lock:
                self._image_egress_circuits.clear()
            return {"opened": False, "state": "disabled", "egress_key": key}

        threshold = max(1, int(getattr(self._config, "image_egress_failure_threshold", 3)))
        cooldown = max(1, int(getattr(self._config, "image_egress_cooldown_seconds", 120)))
        now = time.monotonic()
        with self._lock:
            state = self._image_egress_circuits.setdefault(key, ImageEgressCircuitState())
            self._prune_image_egress_failures(state, now)
            state.failure_times.append(now)
            opened = False
            reopened = False
            if half_open_probe:
                state.opened_until = now + cooldown
                state.half_open_probe = False
                opened = True
                reopened = True
            elif state.opened_until <= now and len(state.failure_times) >= threshold:
                state.opened_until = now + cooldown
                state.half_open_probe = False
                opened = True
            return {
                "opened": opened,
                "reopened": reopened,
                "state": "open" if state.opened_until > now else "closed",
                "egress_key": key,
                "failure_code": str(failure_code or ""),
                "failure_count": len(state.failure_times),
                "threshold": threshold,
                "cooldown_seconds": cooldown,
                "remaining_seconds": cooldown if opened else 0,
            }

    def record_image_egress_success(
        self,
        profile: ProxyRuntimeProfile,
        *,
        half_open_probe: bool = False,
    ) -> dict[str, object]:
        """半开探测成功后关闭熔断。"""
        enabled = bool(getattr(self._config, "image_egress_circuit_breaker_enabled", True))
        key = self._image_egress_key(profile)
        with self._lock:
            if not enabled:
                self._image_egress_circuits.clear()
                return {"closed": False, "state": "disabled", "egress_key": key}
            state = self._image_egress_circuits.get(key)
            closed = bool(state is not None and half_open_probe and state.half_open_probe)
            if closed:
                self._image_egress_circuits.pop(key, None)
            return {
                "closed": closed,
                "state": "closed" if closed or state is None else "open",
                "egress_key": key,
            }

    def release_image_egress_probe(self, profile: ProxyRuntimeProfile) -> bool:
        """释放尚未真正请求上游的半开探测名额，让下一请求继续试探。"""
        key = self._image_egress_key(profile)
        with self._lock:
            state = self._image_egress_circuits.get(key)
            if state is None or not state.half_open_probe:
                return False
            state.half_open_probe = False
            state.opened_until = min(state.opened_until, time.monotonic())
            return True

    def get_image_egress_circuit_status(self) -> list[dict[str, object]]:
        """返回当前进程内的生图出口熔断状态，供诊断使用。"""
        now = time.monotonic()
        with self._lock:
            result: list[dict[str, object]] = []
            for key, state in list(self._image_egress_circuits.items()):
                self._prune_image_egress_failures(state, now)
                if state.opened_until <= 0 and not state.failure_times:
                    self._image_egress_circuits.pop(key, None)
                    continue
                result.append({
                    "egress_key": key,
                    "state": (
                        "open"
                        if state.opened_until > now
                        else "half_open"
                        if state.opened_until > 0
                        else "closed"
                    ),
                    "failure_count": len(state.failure_times),
                    "half_open_probe": state.half_open_probe,
                    "remaining_seconds": max(0, int(state.opened_until - now + 0.999)),
                })
            return result

    def _prune_image_egress_failures(self, state: ImageEgressCircuitState, now: float) -> None:
        window = max(1, int(getattr(self._config, "image_egress_failure_window_seconds", 60)))
        cutoff = now - window
        state.failure_times = [timestamp for timestamp in state.failure_times if timestamp >= cutoff]

    @staticmethod
    def _image_egress_key(profile: ProxyRuntimeProfile) -> str:
        return _clean(getattr(profile, "egress_key", "")) or _egress_key_for_proxy(profile.proxy_url)

    def acquire_image_egress(self, profile: ProxyRuntimeProfile) -> int:
        if bool(getattr(profile, "image_egress_reserved", False)):
            return max(0, int(getattr(profile, "image_egress_wait_ms", 0) or 0))
        limit = max(0, int(getattr(profile, "image_concurrency_limit", 0) or 0))
        if limit <= 0:
            return 0
        key = _clean(getattr(profile, "egress_key", "")) or _egress_key_for_proxy(profile.proxy_url)
        started = time.perf_counter()
        with self._egress_condition:
            while int(self._egress_inflight.get(key, 0)) >= limit:
                self._egress_condition.wait(timeout=1.0)
            self._egress_inflight[key] = int(self._egress_inflight.get(key, 0)) + 1
        return int((time.perf_counter() - started) * 1000)

    def release_image_egress(self, profile: ProxyRuntimeProfile) -> None:
        limit = max(0, int(getattr(profile, "image_concurrency_limit", 0) or 0))
        if limit <= 0:
            return
        key = _clean(getattr(profile, "egress_key", "")) or _egress_key_for_proxy(profile.proxy_url)
        with self._egress_condition:
            current = int(self._egress_inflight.get(key, 0))
            if current <= 1:
                self._egress_inflight.pop(key, None)
            else:
                self._egress_inflight[key] = current - 1
            self._egress_condition.notify_all()

    def _get_runtime_settings(self) -> dict[str, object]:
        try:
            runtime = self._config.get_proxy_runtime_settings()
        except AttributeError:
            runtime = {}
        return runtime if isinstance(runtime, dict) else {}

    def _config_dict_list(self, key: str) -> list[dict]:
        data = getattr(self._config, "data", None)
        if not isinstance(data, dict):
            try:
                data = self._config.get()
            except AttributeError:
                data = {}
        raw = data.get(key) if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _account_group_proxy_reference(self, account: dict | None) -> str:
        if not isinstance(account, dict):
            return ""
        group_id = _clean(account.get("group_id"))
        if not group_id:
            return ""
        for group in self._config_dict_list("account_groups"):
            if _clean(group.get("id")) != group_id or group.get("enabled") is False:
                continue
            proxy = _clean(group.get("proxy"))
            if proxy:
                return proxy
            proxy_group_id = _clean(group.get("proxy_group_id"))
            return f"group:{proxy_group_id}" if proxy_group_id else ""
        return ""

    def _resolve_proxy_reference(
        self,
        value: object,
        *,
        source: str,
        terminal_when_unresolved: bool,
        reserve_image_egress: bool = False,
    ) -> ResolvedProxyReference:
        raw = _clean(value)
        lower = raw.lower()
        if not raw or lower == "global":
            return ResolvedProxyReference(source=source)
        if lower == "direct":
            return ResolvedProxyReference(source=f"{source}_direct", terminal=True)
        if lower.startswith("profile:"):
            proxy = self._resolve_proxy_profile(raw.split(":", 1)[1])
            return ResolvedProxyReference(
                proxy_url=proxy,
                source=f"{source}_profile",
                terminal=bool(proxy) or terminal_when_unresolved,
                egress_key=_egress_key_for_proxy(proxy),
                egress_label=f"{source}_profile",
            )
        if lower.startswith("group:"):
            selection = self._resolve_proxy_group(
                raw.split(":", 1)[1],
                reserve_image_egress=reserve_image_egress,
            )
            return ResolvedProxyReference(
                proxy_url=selection.proxy_url,
                source=f"{source}_group",
                terminal=bool(selection.proxy_url) or terminal_when_unresolved,
                egress_key=selection.egress_key,
                egress_label=selection.egress_label,
                proxy_group_id=selection.group_id,
                proxy_node_id=selection.node_id,
                proxy_node_name=selection.node_name,
                image_concurrency_limit=selection.image_concurrency_limit,
                image_egress_reserved=selection.image_egress_reserved,
                image_egress_wait_ms=selection.image_egress_wait_ms,
            )
        return ResolvedProxyReference(
            proxy_url=raw,
            source=source,
            terminal=True,
            egress_key=_egress_key_for_proxy(raw),
            egress_label=source,
        )

    def _resolve_proxy_profile(self, profile_id: object) -> str:
        normalized = _clean(profile_id)
        if not normalized:
            return ""
        for profile in self._config_dict_list("proxy_profiles"):
            if _clean(profile.get("id")) == normalized and profile.get("enabled", True):
                return _clean(profile.get("proxy"))
        return ""

    def _resolve_proxy_group(
        self,
        group_id: object,
        *,
        reserve_image_egress: bool = False,
    ) -> ProxyGroupSelection:
        normalized = _clean(group_id)
        if not normalized:
            return ProxyGroupSelection()
        for group in self._config_dict_list("proxy_groups"):
            if _clean(group.get("id")) != normalized or group.get("enabled") is False:
                continue
            nodes = [
                node for node in group.get("nodes", [])
                if isinstance(node, dict)
                and node.get("enabled", True)
                and _clean(node.get("url"))
            ]
            if not nodes:
                return ProxyGroupSelection()
            started = time.perf_counter()
            indexed_nodes = list(enumerate(nodes))
            with self._egress_condition:
                while True:
                    available_nodes = [
                        (node_index, node)
                        for node_index, node in indexed_nodes
                        if self._proxy_node_has_image_capacity(normalized, node, node_index)
                    ]
                    if available_nodes:
                        selected_index, selected = random.choice(available_nodes)
                        selection = _proxy_group_selection(normalized, selected, selected_index)
                        if reserve_image_egress and selection.image_concurrency_limit > 0:
                            self._egress_inflight[selection.egress_key] = int(
                                self._egress_inflight.get(selection.egress_key, 0)
                            ) + 1
                            selection = replace(
                                selection,
                                image_egress_reserved=True,
                                image_egress_wait_ms=int((time.perf_counter() - started) * 1000),
                            )
                        return selection
                    if not reserve_image_egress:
                        selected_index, selected = min(
                            indexed_nodes,
                            key=lambda item: self._proxy_node_load_score(normalized, item[1], item[0]),
                        )
                        return _proxy_group_selection(normalized, selected, selected_index)
                    self._egress_condition.wait(timeout=1.0)
        return ProxyGroupSelection()

    def _proxy_node_has_image_capacity(self, group_id: str, node: Mapping[str, object], index: int) -> bool:
        limit = _proxy_node_image_concurrency_limit(node)
        if limit <= 0:
            return True
        key = _proxy_group_node_key(group_id, node, index)
        return int(self._egress_inflight.get(key, 0)) < limit

    def _proxy_node_load_score(self, group_id: str, node: Mapping[str, object], index: int) -> tuple[float, int]:
        key = _proxy_group_node_key(group_id, node, index)
        current = int(self._egress_inflight.get(key, 0))
        limit = _proxy_node_image_concurrency_limit(node)
        if limit <= 0:
            return 0.0, current
        return current / max(1, limit), current

    def _bundle_for_headers(self, profile: ProxyRuntimeProfile, target_host: str) -> ClearanceBundle | None:
        key = self._cache_key(profile.proxy_url, target_host)
        if profile.clearance_mode == "manual":
            bundle = self._build_manual_bundle(profile, target_host)
            if bundle is not None:
                self._set_cached_bundle(key, bundle)
            return bundle
        if profile.clearance_mode == "flaresolverr":
            return self._get_cached_bundle(key)
        return None

    def _build_manual_bundle(self, profile: ProxyRuntimeProfile, target_host: str) -> ClearanceBundle | None:
        cookies = _parse_cookie_header(str(profile.clearance.get("cf_cookies") or ""))
        cf_clearance = str(profile.clearance.get("cf_clearance") or "").strip()
        if cf_clearance and "cf_clearance" not in cookies:
            cookies["cf_clearance"] = cf_clearance
        user_agent = str(profile.clearance.get("user_agent") or "").strip()
        if not cookies and not user_agent:
            return None

        now = time.time()
        expires_at = now + profile.refresh_interval if profile.refresh_interval else None
        return ClearanceBundle(
            target_host=target_host,
            proxy_url=profile.proxy_url,
            proxy_source=profile.proxy_source,
            egress_key=profile.egress_key,
            egress_label=profile.egress_label,
            cookies=cookies,
            user_agent=user_agent,
            created_at=now,
            expires_at=expires_at,
        )

    def _get_provider(self, flaresolverr_url: str) -> FlareSolverrClearanceProvider:
        url = str(flaresolverr_url or "").strip().rstrip("/")
        with self._lock:
            provider = self._provider_cache.get(url)
            if provider is None:
                provider = self._clearance_provider_factory(url)
                self._provider_cache[url] = provider
            return provider

    def _get_flight_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            lock = self._flight_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._flight_locks[key] = lock
            return lock

    def _get_cached_bundle(self, key: tuple[str, str]) -> ClearanceBundle | None:
        with self._lock:
            return self._clearance_cache.get(key)

    def _set_cached_bundle(self, key: tuple[str, str], bundle: ClearanceBundle) -> None:
        with self._lock:
            self._clearance_cache[key] = bundle

    @staticmethod
    def _cache_key(proxy_url: str, target_host: str) -> tuple[str, str]:
        return (normalize_proxy_url(proxy_url), _normalize_host(target_host))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _colon_proxy_to_url(url: str) -> str:
    parts = url.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, username, password = parts
        return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
    if len(parts) == 2 and parts[1].isdigit():
        return f"http://{url}"
    return url


def _normalize_host(host: str) -> str:
    return str(host or "").strip().strip(".").lower()


def _host_from_url(url: str) -> str:
    candidate = str(url or "").strip()
    parsed = urlparse(candidate)
    if not parsed.hostname and candidate and "://" not in candidate:
        parsed = urlparse(f"https://{candidate}")
    return _normalize_host(parsed.hostname or "")


def _status_codes_tuple(value: object) -> tuple[int, ...]:
    source = value if isinstance(value, list) else [403]
    codes: list[int] = []
    for item in source:
        if isinstance(item, bool):
            continue
        try:
            code = int(item)
        except (OverflowError, TypeError, ValueError):
            continue
        if 100 <= code <= 599 and code not in codes:
            codes.append(code)
    return tuple(codes or [403])


def _egress_key_for_proxy(proxy_url: object) -> str:
    """生成可追踪但不泄露代理凭据的出口标识。"""
    normalized = normalize_proxy_url(_clean(proxy_url))
    if not normalized:
        return "direct"
    parsed = urlparse(normalized)
    if parsed.hostname:
        scheme = (parsed.scheme or "proxy").lower()
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError:
            port = None
        return f"proxy:{scheme}://{host}:{port}" if port else f"proxy:{scheme}://{host}"
    digest = hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()[:12]
    return f"proxy:opaque:{digest}"


def _proxy_node_id(node: Mapping[str, object], index: int) -> str:
    return _clean(node.get("id")) or _clean(node.get("name")) or f"node-{index + 1}"


def _proxy_group_node_key(group_id: str, node: Mapping[str, object], index: int) -> str:
    return f"group:{group_id}:{_proxy_node_id(node, index)}"


def _proxy_node_image_concurrency_limit(node: Mapping[str, object]) -> int:
    for key in ("image_concurrency_limit", "image_concurrency", "max_image_concurrency"):
        value = node.get(key)
        if value is None or value == "":
            continue
        try:
            return max(0, int(float(value)))
        except (OverflowError, TypeError, ValueError):
            return DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT
    return DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT


def _proxy_group_selection(group_id: str, node: Mapping[str, object], index: int) -> ProxyGroupSelection:
    node_id = _proxy_node_id(node, index)
    return ProxyGroupSelection(
        proxy_url=_clean(node.get("url")),
        group_id=group_id,
        node_id=node_id,
        node_name=_clean(node.get("name")) or node_id,
        image_concurrency_limit=_proxy_node_image_concurrency_limit(node),
    )


def _coerce_timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (OverflowError, TypeError, ValueError):
        timeout = 60.0
    return max(1.0, timeout)


def _is_valid_proxy_url(url: str) -> bool:
    parsed = urlparse(normalize_proxy_url(url))
    return parsed.scheme in {"http", "https", "socks5", "socks5h"} and bool(parsed.netloc)


def _domain_matches(host: str, domain: str) -> bool:
    normalized_host = _normalize_host(host)
    normalized_domain = _normalize_host(domain.lstrip("."))
    if not normalized_domain:
        return True
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def _filter_flaresolverr_cookies(raw_cookies: object, target_host: str) -> dict[str, str]:
    if not isinstance(raw_cookies, list):
        return {}

    filtered_cookies: dict[str, str] = {}
    for item in raw_cookies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "").strip()
        if not domain or _domain_matches(target_host, domain):
            filtered_cookies[name] = value
    return filtered_cookies


def _parse_cookie_header(header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in str(header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies[name.strip()] = value.strip()
    return cookies


def _cookies_to_header(cookies: Mapping[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name)


def _merge_cookie_header(existing_header: str, cookies: Mapping[str, str]) -> str:
    existing = str(existing_header or "").strip()
    existing_names = set(_parse_cookie_header(existing).keys())
    additions = [f"{name}={value}" for name, value in cookies.items() if name and name not in existing_names]
    if existing and additions:
        return existing.rstrip("; ") + "; " + "; ".join(additions)
    if existing:
        return existing
    return "; ".join(additions)


def _find_header_key(headers: Mapping[str, object], name: str) -> str | None:
    target = name.lower()
    for key in headers:
        if str(key).lower() == target:
            return str(key)
    return None


def _redact_url_credentials(text: str) -> str:
    return re.sub(
        r"((?:https?|socks5h?|socks)://)([^\s/@:]+):([^\s/@]+)@",
        r"\1[REDACTED]@",
        str(text or ""),
        flags=re.IGNORECASE,
    )


def test_proxy(url: str = "", *, timeout: float = 15.0) -> dict:
    candidate = normalize_proxy_url(_clean(url))
    proxy_source = "input"
    if not candidate:
        profile = proxy_settings.get_profile(upstream=True)
        candidate = profile.proxy_url
        proxy_source = profile.proxy_source
    result_base = {"proxy_source": proxy_source, "has_proxy": bool(candidate)}
    if not candidate:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": 0,
            "error": "no active proxy configured",
            **result_base,
        }
    if not _is_valid_proxy_url(candidate):
        return {
            "ok": False,
            "status": 0,
            "latency_ms": 0,
            "error": "invalid proxy url",
            **result_base,
        }
    session = Session(impersonate="edge101", verify=not proxy_settings.should_skip_ssl_verify(), proxy=candidate)
    started = time.perf_counter()
    try:
        response = session.get(
            "https://chatgpt.com/api/auth/csrf",
            headers={"user-agent": "Mozilla/5.0 (chatgpt2api proxy test)"},
            timeout=timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": response.status_code < 500,
            "status": int(response.status_code),
            "latency_ms": latency_ms,
            "error": None if response.status_code < 500 else f"HTTP {response.status_code}",
            **result_base,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "status": 0,
            "latency_ms": latency_ms,
            "error": _redact_url_credentials(str(exc) or exc.__class__.__name__),
            **result_base,
        }
    finally:
        session.close()


def test_clearance(
    target_url: str = "https://auth.openai.com",
    proxy: str = "",
    clearance: Mapping[str, object] | None = None,
) -> dict:
    target_url = str(target_url or "https://auth.openai.com").strip() or "https://auth.openai.com"
    started = time.perf_counter()
    profile = proxy_settings.get_registration_profile(proxy, clearance)
    result_base = {
        "egress_key": profile.egress_key,
        "egress_label": profile.egress_label,
        "proxy_source": profile.proxy_source,
        "has_proxy": bool(profile.proxy_url),
    }
    if not profile.clearance_enabled:
        return {
            "ok": False,
            "status": "disabled",
            "latency_ms": 0,
            "has_cookies": False,
            "user_agent": "",
            "error": "clearance is disabled",
            **result_base,
        }
    try:
        bundle = proxy_settings.refresh_clearance(
            target_url=target_url,
            force=True,
            profile=profile,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "has_cookies": False,
            "user_agent": "",
            "error": _redact_url_credentials(str(exc) or exc.__class__.__name__),
            **result_base,
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    if bundle is None:
        return {
            "ok": False,
            "status": "failed",
            "latency_ms": latency_ms,
            "has_cookies": False,
            "user_agent": "",
            "error": "clearance refresh returned no bundle",
            **result_base,
        }
    return {
        "ok": True,
        "status": "ok",
        "latency_ms": latency_ms,
        "has_cookies": bool(bundle.cookies),
        "user_agent": bundle.user_agent or "",
        "error": None,
        **result_base,
    }


proxy_settings = ProxySettingsStore()

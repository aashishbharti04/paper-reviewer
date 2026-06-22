"""Multi-provider LLM client with toggle and automatic fallback.

Providers supported out of the box: Groq, Ollama, OpenRouter.
Adding a new provider = subclass Provider and register it in PROVIDER_CLASSES.

Config is persisted to config.json next to the app. Multiple API keys per
provider are rotated round-robin; on auth/quota error the next key is tried.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests


def _config_path() -> Path:
    """Where to read/write config.json.

    When running as a normal Python script -> next to the project root (handy for dev).
    When frozen by PyInstaller -> %APPDATA%\\PaperReviewer\\config.json so an installed
    .exe in Program Files can still persist user settings.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "PaperReviewer"
        d.mkdir(parents=True, exist_ok=True)
        return d / "config.json"
    return Path(__file__).resolve().parent.parent / "config.json"


CONFIG_PATH = _config_path()


# ---------------- Provider base ----------------


class ProviderError(Exception):
    pass


@dataclass
class Provider:
    name: str
    enabled: bool = False
    model: str = ""

    def call(self, system: str, user: str, *, timeout: int = 60, json_mode: bool = False) -> str:
        raise NotImplementedError

    def test(self) -> tuple[bool, str]:
        """Quick connectivity check. Returns (ok, message)."""
        try:
            out = self.call("You are a test.", "Reply with the single word: ok", timeout=15)
            return True, out[:200]
        except Exception as e:
            return False, str(e)[:300]


# ---------------- Groq ----------------


@dataclass
class GroqProvider(Provider):
    name: str = "groq"
    api_keys: list[str] = field(default_factory=list)
    model: str = "llama-3.3-70b-versatile"
    _key_cycle: Optional[itertools.cycle] = None

    def _next_key(self) -> str:
        if not self.api_keys:
            raise ProviderError("No Groq API keys configured.")
        if self._key_cycle is None:
            self._key_cycle = itertools.cycle(self.api_keys)
        return next(self._key_cycle)

    def call(self, system: str, user: str, *, timeout: int = 60, json_mode: bool = False) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        last_err = None
        for _ in range(max(1, len(self.api_keys))):
            key = self._next_key()
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "seed": 42,
                "max_tokens": 1800,
            }
            # Force the API to return a valid JSON object so review parsing can't fail
            # on chatty models that ignore the "strict JSON" instruction.
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                # Some models/endpoints reject response_format with 400 — retry once plainly.
                if r.status_code == 400 and json_mode:
                    payload.pop("response_format", None)
                    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if r.status_code in (401, 403, 429):
                    last_err = f"Groq key error {r.status_code}: {r.text[:200]}"
                    continue
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
            except requests.RequestException as e:
                last_err = f"Groq network error: {e}"
                continue
        raise ProviderError(last_err or "Groq call failed.")


# ---------------- Ollama (local) ----------------


@dataclass
class OllamaProvider(Provider):
    name: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1"

    def call(self, system: str, user: str, *, timeout: int = 180, json_mode: bool = False) -> str:
        try:
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.0, "seed": 42},
            }
            if json_mode:
                body["format"] = "json"
            r = requests.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                json=body,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]
        except requests.RequestException as e:
            raise ProviderError(f"Ollama error: {e}") from e


# ---------------- OpenRouter ----------------


@dataclass
class OpenRouterProvider(Provider):
    name: str = "openrouter"
    api_keys: list[str] = field(default_factory=list)
    model: str = "meta-llama/llama-3.1-70b-instruct:free"
    _key_cycle: Optional[itertools.cycle] = None

    def _next_key(self) -> str:
        if not self.api_keys:
            raise ProviderError("No OpenRouter API keys configured.")
        if self._key_cycle is None:
            self._key_cycle = itertools.cycle(self.api_keys)
        return next(self._key_cycle)

    def call(self, system: str, user: str, *, timeout: int = 90, json_mode: bool = False) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        last_err = None
        for _ in range(max(1, len(self.api_keys))):
            key = self._next_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost/paper-reviewer",
                "X-Title": "Paper Reviewer",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "seed": 42,
                "max_tokens": 1800,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if r.status_code == 400 and json_mode:
                    payload.pop("response_format", None)
                    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if r.status_code in (401, 403, 429):
                    last_err = f"OpenRouter key error {r.status_code}: {r.text[:200]}"
                    continue
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except requests.RequestException as e:
                last_err = f"OpenRouter network error: {e}"
                continue
        raise ProviderError(last_err or "OpenRouter call failed.")


PROVIDER_CLASSES = {
    "groq": GroqProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}


# ---------------- Manager ----------------


@dataclass
class ProviderManager:
    providers: dict[str, Provider] = field(default_factory=dict)
    order: list[str] = field(default_factory=lambda: ["groq", "ollama", "openrouter"])
    auto_fallback: bool = True

    def call(self, system: str, user: str, *, json_mode: bool = False) -> tuple[str, str]:
        """Try providers in order. Returns (provider_name, response_text)."""
        errors = []
        for name in self.order:
            p = self.providers.get(name)
            if p is None or not p.enabled:
                continue
            try:
                out = p.call(system, user, json_mode=json_mode)
                return name, out
            except Exception as e:
                errors.append(f"{name}: {e}")
                if not self.auto_fallback:
                    break
        raise ProviderError("All providers failed:\n" + "\n".join(errors))

    def working_provider(self) -> Optional[str]:
        for name in self.order:
            p = self.providers.get(name)
            if p and p.enabled:
                ok, _ = p.test()
                if ok:
                    return name
        return None

    # ---- Config persistence ----

    def to_dict(self) -> dict:
        out = {"order": self.order, "auto_fallback": self.auto_fallback, "providers": {}}
        for name, p in self.providers.items():
            d = {"enabled": p.enabled, "model": p.model}
            if isinstance(p, GroqProvider):
                d["api_keys"] = p.api_keys
            elif isinstance(p, OpenRouterProvider):
                d["api_keys"] = p.api_keys
            elif isinstance(p, OllamaProvider):
                d["base_url"] = p.base_url
            out["providers"][name] = d
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderManager":
        mgr = cls(order=d.get("order", ["groq", "ollama", "openrouter"]),
                  auto_fallback=d.get("auto_fallback", True))
        prov_d = d.get("providers", {})
        for name, cfg in prov_d.items():
            klass = PROVIDER_CLASSES.get(name)
            if not klass:
                continue
            kwargs = {"enabled": cfg.get("enabled", False),
                      "model": cfg.get("model", "")}
            if name in ("groq", "openrouter"):
                kwargs["api_keys"] = cfg.get("api_keys", [])
            if name == "ollama":
                kwargs["base_url"] = cfg.get("base_url", "http://localhost:11434")
            if not kwargs["model"]:
                kwargs["model"] = klass().model
            mgr.providers[name] = klass(**kwargs)
        # ensure all default providers exist (even if disabled)
        for name, klass in PROVIDER_CLASSES.items():
            if name not in mgr.providers:
                mgr.providers[name] = klass()
        return mgr

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "ProviderManager":
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        # default: all providers present, none enabled
        return cls.from_dict({})

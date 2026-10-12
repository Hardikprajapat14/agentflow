"""Provider-agnostic client for any OpenAI-compatible chat-completions API (Groq, OpenRouter, Ollama, ...)."""
import json
import logging
import re
import time

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()

    # -- low level -----------------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        if not self.s.llm_api_key and "localhost" not in self.s.llm_base_url and "host.docker" not in self.s.llm_base_url:
            raise LLMError(
                "LLM_API_KEY is not configured. Create a free key at https://console.groq.com/keys "
                "and put it in your .env file."
            )
        url = f"{self.s.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.s.llm_api_key or 'none'}", "Content-Type": "application/json"}
        last = "unknown error"
        for attempt in range(self.s.llm_max_retries):
            try:
                r = httpx.post(url, json=payload, headers=headers, timeout=self.s.llm_timeout)
            except httpx.HTTPError as exc:
                last = f"network error: {exc}"
                time.sleep(min(2 ** attempt * 2, 20))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                try:
                    wait = float(r.headers.get("retry-after", 0)) or 2 ** attempt * 3
                except ValueError:
                    wait = 2 ** attempt * 3
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                logger.warning("LLM transient error (%s); retrying in %.0fs", last, wait)
                time.sleep(min(wait, 30))
                continue
            raise LLMError(f"LLM API error {r.status_code}: {r.text[:500]}", status=r.status_code)
        raise LLMError(f"LLM provider unavailable or rate-limited after retries ({last})", retryable=True)

    def chat(self, messages: list[dict], *, json_mode: bool = False, tools: list[dict] | None = None,
             tool_choice: dict | str | None = None, temperature: float = 0.2, max_tokens: int = 2048) -> dict:
        """Returns the assistant message dict. Falls back to the secondary model if the primary is unavailable."""
        payload: dict = {"model": self.s.llm_model, "messages": messages, "temperature": temperature,
                         "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        try:
            data = self._post(payload)
        except LLMError as exc:
            fb = self.s.llm_fallback_model
            if exc.retryable and fb and fb != self.s.llm_model:
                logger.warning("Primary model unavailable, falling back to %s", fb)
                data = self._post({**payload, "model": fb})
            else:
                raise
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {str(data)[:300]}") from exc

    # -- structured helpers ---------------------------------------------------------
    def json(self, messages: list[dict], *, max_tokens: int = 2048, temperature: float = 0.1) -> dict:
        """Chat in JSON mode and return a parsed object (one repair attempt on bad JSON)."""
        msg = self.chat(messages, json_mode=True, max_tokens=max_tokens, temperature=temperature)
        try:
            return extract_json(msg.get("content") or "")
        except json.JSONDecodeError:
            repair = messages + [
                {"role": "assistant", "content": msg.get("content") or ""},
                {"role": "user", "content": "That was not valid JSON. Reply again with ONLY one valid JSON object."},
            ]
            msg = self.chat(repair, json_mode=True, max_tokens=max_tokens, temperature=0)
            try:
                return extract_json(msg.get("content") or "")
            except json.JSONDecodeError as exc:
                raise LLMError("Model did not return valid JSON") from exc

    def call_tool(self, messages: list[dict], name: str, description: str, parameters: dict) -> dict:
        """Native function calling: force the model to call `name` and return its arguments."""
        tools = [{"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}]
        msg = self.chat(messages, tools=tools, tool_choice={"type": "function", "function": {"name": name}},
                        temperature=0, max_tokens=800)
        calls = msg.get("tool_calls") or []
        if not calls:
            raise LLMError("Model returned no tool call")
        raw = calls[0]["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise LLMError("Tool call arguments were not valid JSON") from exc
        return args if isinstance(args, dict) else {}

"""Guardrail for sub-agent harness and model selection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_DISPATCH_TOOLS = {"sys_session_create", "sys_session_send"}
_MODEL_KEYS = {"model", "model_id", "model_override"}
_AGENT_KEYS = {"agent", "agent_id", "harness"}
_CONTAINER_KEYS = {"args", "config", "executor", "llm", "spec"}
_UNKNOWN_AGENT_KEYS = {"config_path"}


def _canonical_agent(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = value.strip().lower().replace("_", "-")
    aliases = {
        "claude-code": "claude",
        "claude-native": "claude",
        "claude-native-ui": "claude",
        "codex-native": "codex",
        "codex-native-ui": "codex",
        "cursor-agent": "cursor",
        "cursor-native": "cursor",
        "cursor-native-ui": "cursor",
        "opencode-native": "opencode",
        "opencode-native-ui": "opencode",
    }
    return aliases.get(name, name)


def _find_explicit_values(
    value: object,
    keys: set[str],
    *,
    parents: tuple[str, ...] = (),
) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.lower()
            if normalized_key in keys and not isinstance(child, (Mapping, list)):
                found.append((".".join((*parents, normalized_key)), child))
            elif normalized_key in _CONTAINER_KEYS and isinstance(child, Mapping):
                found.extend(
                    _find_explicit_values(
                        child,
                        keys,
                        parents=(*parents, normalized_key),
                    )
                )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(
                _find_explicit_values(child, keys, parents=(*parents, str(index)))
            )
    return found


def same_subagent_model_policy(event: Mapping[str, Any]) -> dict[str, str] | None:
    """Ask before dispatching a sub-agent with a different model or harness.

    An omitted model or harness is allowed through and left to Omnigent's
    normal inheritance/default behavior. A mismatch requires user approval;
    approve it only when the user or an applicable skill explicitly requested
    that different model or harness.
    """
    target = event.get("target")
    if event.get("type") != "tool_call" or target not in _DISPATCH_TOOLS:
        return None

    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    arguments = data.get("arguments")
    if not isinstance(arguments, Mapping):
        return None

    context = event.get("context")
    context = context if isinstance(context, Mapping) else {}
    current_model = context.get("model")
    current_harness = context.get("harness")

    mismatches: list[str] = []
    if any(key in arguments for key in _UNKNOWN_AGENT_KEYS):
        mismatches.append("config_path (custom agent model/harness cannot be verified)")

    for path, value in _find_explicit_values(arguments, _MODEL_KEYS):
        if not isinstance(value, str) or not current_model:
            mismatches.append(f"{path}={value!r} (current model is unknown)")
        elif value.strip().casefold() != str(current_model).strip().casefold():
            mismatches.append(f"{path}={value!r} (current model: {current_model})")

    for path, value in _find_explicit_values(arguments, _AGENT_KEYS):
        if not isinstance(value, str) or not current_harness:
            mismatches.append(f"{path}={value!r} (current harness is unknown)")
        elif _canonical_agent(value) != _canonical_agent(current_harness):
            mismatches.append(f"{path}={value!r} (current harness: {current_harness})")

    if not mismatches:
        return None

    return {
        "result": "ASK",
        "reason": (
            "This sub-agent specifies a different or unverifiable model/harness: "
            + ", ".join(mismatches)
            + ". Approve only if the user or an applicable skill explicitly "
            "requested this exception; otherwise reject and retry using the "
            "current session's model and harness."
        ),
    }


POLICY_REGISTRY = [
    {
        "handler": "omnigent_same_subagent_model.same_subagent_model_policy",
        "kind": "callable",
        "name": "Keep sub-agents on the current model",
        "description": (
            "Asks before a sub-agent dispatch specifies a different or "
            "unverifiable model or harness."
        ),
        "params_schema": {"type": "object", "properties": {}},
    }
]

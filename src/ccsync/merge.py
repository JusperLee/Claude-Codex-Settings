from __future__ import annotations

import copy
import re
from typing import Any


SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "password", "credential")
TOML_HEADER = re.compile(r"^\s*(\[\[?[^]]+\]\]?)\s*(?:#.*)?$")
TOML_ASSIGNMENT = re.compile(r'^\s*([A-Za-z0-9_.-]+|"[^"]+"|\'[^\']+\')\s*=')


def is_secret_key(key: str) -> bool:
    compact = key.strip('"\'').lower().replace("-", "_")
    return any(marker in compact for marker in SECRET_MARKERS)


def _portable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _portable_json(child)
            for key, child in value.items()
            if not is_secret_key(str(key))
        }
    if isinstance(value, list):
        return [_portable_json(child) for child in value]
    return copy.deepcopy(value)


def _json_secrets(value: Any, path: tuple[Any, ...] = ()) -> dict[tuple[Any, ...], Any]:
    secrets: dict[tuple[Any, ...], Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (key,)
            if is_secret_key(str(key)):
                secrets[child_path] = copy.deepcopy(child)
            else:
                secrets.update(_json_secrets(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            secrets.update(_json_secrets(child, path + (index,)))
    return secrets


def _set_json_path(document: Any, path: tuple[Any, ...], value: Any) -> None:
    current = document
    for index, part in enumerate(path[:-1]):
        following = path[index + 1]
        if isinstance(part, int):
            while len(current) <= part:
                current.append({} if isinstance(following, str) else [])
            current = current[part]
        else:
            if part not in current:
                current[part] = {} if isinstance(following, str) else []
            current = current[part]
    last = path[-1]
    if isinstance(last, int):
        while len(current) <= last:
            current.append(None)
        current[last] = copy.deepcopy(value)
    else:
        current[last] = copy.deepcopy(value)


def _overlay_json(document: Any, secrets: dict[tuple[Any, ...], Any]) -> None:
    for path, value in secrets.items():
        _set_json_path(document, path, value)


def merge_json_values(
    local: dict[str, Any], remote: dict[str, Any], *, prefer_remote: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = _portable_json(remote if prefer_remote else local)
    local_result = copy.deepcopy(base)
    remote_result = copy.deepcopy(base)
    local_secrets = _json_secrets(local)
    remote_secrets = _json_secrets(remote)
    _overlay_json(local_result, local_secrets)
    _overlay_json(remote_result, local_secrets)
    _overlay_json(remote_result, remote_secrets)
    return local_result, remote_result


def _toml_blocks(text: str) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    order = [""]
    blocks: dict[str, list[str]] = {"": []}
    headers: dict[str, str] = {"": ""}
    current = ""
    for line in text.splitlines():
        match = TOML_HEADER.match(line)
        if match:
            current = match.group(1)
            if current not in blocks:
                order.append(current)
                blocks[current] = []
                headers[current] = line
        else:
            blocks[current].append(line)
    return order, blocks, headers


def _toml_secret_lines(blocks: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for header, lines in blocks.items():
        for line in lines:
            match = TOML_ASSIGNMENT.match(line)
            if match and is_secret_key(match.group(1)):
                result.setdefault(header, {})[match.group(1)] = line
    return result


def _render_toml(
    base_text: str,
    primary_secrets: dict[str, dict[str, str]],
    fallback_secrets: dict[str, dict[str, str]] | None = None,
) -> str:
    order, blocks, headers = _toml_blocks(base_text)
    fallback_secrets = fallback_secrets or {}
    secret_headers = list(fallback_secrets) + list(primary_secrets)
    for header in secret_headers:
        if header not in blocks:
            order.append(header)
            blocks[header] = []
            headers[header] = header

    output: list[str] = []
    for header in order:
        if header:
            output.append(headers[header])
        selected = dict(fallback_secrets.get(header, {}))
        selected.update(primary_secrets.get(header, {}))
        output.extend(selected.values())
        for line in blocks[header]:
            match = TOML_ASSIGNMENT.match(line)
            if not (match and is_secret_key(match.group(1))):
                output.append(line)
    return "\n".join(output).rstrip() + "\n"


def merge_toml_text(local: str, remote: str, *, prefer_remote: bool) -> tuple[str, str]:
    base = remote if prefer_remote else local
    _, local_blocks, _ = _toml_blocks(local)
    _, remote_blocks, _ = _toml_blocks(remote)
    local_secrets = _toml_secret_lines(local_blocks)
    remote_secrets = _toml_secret_lines(remote_blocks)
    return (
        _render_toml(base, local_secrets),
        _render_toml(base, remote_secrets, local_secrets),
    )

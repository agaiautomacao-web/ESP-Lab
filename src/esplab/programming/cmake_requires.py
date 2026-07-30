#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

Result = Tuple[bool, Any]

KNOWN_KEYS = {
    "SRCS", "SRC_DIRS", "EXCLUDE_SRCS",
    "INCLUDE_DIRS", "PRIV_INCLUDE_DIRS",
    "REQUIRES", "PRIV_REQUIRES",
    "LDFRAGMENTS", "EMBED_FILES", "EMBED_TXTFILES",
    "WHOLE_ARCHIVE", "KCONFIG", "KCONFIG_PROJBUILD",
}

_VALID_NAME = re.compile(r"^[A-Za-z0-9_.+\-]+$")


def _cmake_path(project_dir: str | Path) -> Path:
    return Path(project_dir).expanduser().resolve() / "main" / "CMakeLists.txt"


def _validate_component(name: str) -> str | None:
    n = str(name or "").strip()
    if not n:
        return "nome de componente vazio"
    if "/" in n:
        return "componente interno nao deve conter '/'"
    if not _VALID_NAME.match(n):
        return "nome de componente invalido: '{}'".format(name)
    return None


def _read(project_dir: str | Path) -> Result:
    path = _cmake_path(project_dir)
    if not path.is_file():
        return (False, {
            "code": "cmake_missing",
            "message": "main/CMakeLists.txt nao encontrado",
            "path": str(path),
        })
    try:
        return (True, path.read_text(encoding="utf-8"))
    except Exception as e:
        return (False, {
            "code": "read_error",
            "message": str(e),
            "path": str(path),
        })


def _atomic_write(path: Path, text: str) -> Result:
    path = Path(path).expanduser().resolve()
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(
            prefix="." + path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return (True, str(path))
    except Exception as e:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
        return (False, str(e))


def _find_register(text: str) -> Result:
    start = text.find("idf_component_register")
    if start < 0:
        return (False, {
            "code": "register_missing",
            "message": "idf_component_register(...) nao encontrado",
        })

    open_pos = text.find("(", start)
    if open_pos < 0:
        return (False, {
            "code": "register_invalid",
            "message": "idf_component_register sem '('",
        })

    depth = 0
    in_quote = False
    escaped = False

    for i in range(open_pos, len(text)):
        ch = text[i]

        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
            continue

        if ch == '"':
            in_quote = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return (True, {
                    "start": start,
                    "end": i,
                    "call": text[start:i + 1],
                    "body": text[open_pos + 1:i],
                })

    return (False, {
        "code": "register_invalid",
        "message": "idf_component_register sem ')' final",
    })


def _tokens(body: str) -> List[str]:
    clean = "\n".join(line.split("#", 1)[0] for line in body.splitlines())
    return re.findall(r'"[^"]*"|\S+', clean)


def _values(body: str, key: str) -> List[str]:
    vals: List[str] = []
    active = False

    for tok in _tokens(body):
        tok = tok.strip()
        if not tok:
            continue

        if tok in KNOWN_KEYS:
            if tok == key:
                active = True
                continue
            if active:
                break
            continue

        if active:
            vals.append(tok.strip('"'))

    return [v for v in vals if v]


def list_main_requires(project_dir: str | Path) -> Result:
    ok, text = _read(project_dir)
    if not ok:
        return (False, text)

    ok, reg = _find_register(text)
    if not ok:
        return (False, reg)

    return (True, {
        "path": str(_cmake_path(project_dir)),
        "requires": _values(reg["body"], "REQUIRES"),
        "priv_requires": _values(reg["body"], "PRIV_REQUIRES"),
    })


def _insert_in_call(call: str, component: str) -> str:
    lines = call.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("REQUIRES"):
            if line.rstrip().endswith(")"):
                lines[i] = line.rstrip()[:-1].rstrip() + " " + component + ")"
            else:
                lines[i] = line.rstrip() + " " + component
            return "\n".join(lines)

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if line.strip() == ")":
            lines.insert(i, "                    REQUIRES " + component)
            return "\n".join(lines)

        if line.rstrip().endswith(")"):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = line.rstrip()[:-1].rstrip()
            lines.insert(i + 1, indent + "REQUIRES " + component + ")")
            return "\n".join(lines)

    return call.rstrip() + "\n                    REQUIRES " + component + ")"


def add_main_require(project_dir: str | Path, component_name: str) -> Result:
    err = _validate_component(component_name)
    if err:
        return (False, {
            "code": "invalid_component",
            "component": component_name,
            "message": err,
        })

    component = component_name.strip()

    ok, current = list_main_requires(project_dir)
    if not ok:
        return (False, current)

    if component in current["requires"]:
        return (False, {
            "code": "already_in_requires",
            "component": component,
            "path": current["path"],
            "requires": current["requires"],
            "priv_requires": current["priv_requires"],
            "message": "componente '{}' ja esta em REQUIRES".format(component),
        })

    if component in current["priv_requires"]:
        return (False, {
            "code": "already_in_priv_requires",
            "component": component,
            "path": current["path"],
            "requires": current["requires"],
            "priv_requires": current["priv_requires"],
            "message": "componente '{}' ja esta em PRIV_REQUIRES".format(component),
        })

    ok, text = _read(project_dir)
    if not ok:
        return (False, text)

    ok, reg = _find_register(text)
    if not ok:
        return (False, reg)

    new_call = _insert_in_call(reg["call"], component)
    new_text = text[:reg["start"]] + new_call + text[reg["end"] + 1:]

    path = _cmake_path(project_dir)
    ok, written = _atomic_write(path, new_text)
    if not ok:
        return (False, {
            "code": "write_error",
            "path": str(path),
            "message": written,
        })

    ok, updated = list_main_requires(project_dir)
    if not ok:
        return (False, updated)

    return (True, {
        "code": "added",
        "component": component,
        "path": str(path),
        "requires_before": current["requires"],
        "requires_after": updated["requires"],
        "message": "componente '{}' adicionado em REQUIRES".format(component),
    })


def _remove_from_call(call: str, component: str) -> str:
    lines = call.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("REQUIRES"):
            continue

        indent = line[:len(line) - len(line.lstrip())]
        closes = stripped.endswith(")")
        body = stripped[:-1].rstrip() if closes else stripped

        parts = body.split()
        values = parts[1:] if parts and parts[0] == "REQUIRES" else []
        remaining = [v for v in values if v != component]

        if remaining:
            lines[i] = indent + "REQUIRES " + " ".join(remaining) + (")" if closes else "")
            return "\n".join(lines)

        del lines[i]

        if closes:
            if i - 1 >= 0:
                lines[i - 1] = lines[i - 1].rstrip() + ")"
            else:
                lines.append(")")

        return "\n".join(lines)

    return call


def remove_main_require(project_dir: str | Path, component_name: str) -> Result:
    err = _validate_component(component_name)
    if err:
        return (False, {
            "code": "invalid_component",
            "component": component_name,
            "message": err,
        })

    component = component_name.strip()

    ok, current = list_main_requires(project_dir)
    if not ok:
        return (False, current)

    if component not in current["requires"]:
        return (False, {
            "code": "not_in_requires",
            "component": component,
            "path": current["path"],
            "requires": current["requires"],
            "priv_requires": current["priv_requires"],
            "message": "componente '{}' nao esta em REQUIRES".format(component),
        })

    ok, text = _read(project_dir)
    if not ok:
        return (False, text)

    ok, reg = _find_register(text)
    if not ok:
        return (False, reg)

    new_call = _remove_from_call(reg["call"], component)
    new_text = text[:reg["start"]] + new_call + text[reg["end"] + 1:]

    path = _cmake_path(project_dir)
    ok, written = _atomic_write(path, new_text)
    if not ok:
        return (False, {
            "code": "write_error",
            "path": str(path),
            "message": written,
        })

    ok, updated = list_main_requires(project_dir)
    if not ok:
        return (False, updated)

    return (True, {
        "code": "removed",
        "component": component,
        "path": str(path),
        "requires_before": current["requires"],
        "requires_after": updated["requires"],
        "message": "componente '{}' removido de REQUIRES".format(component),
    })


__all__ = [
    "list_main_requires",
    "add_main_require",
    "remove_main_require",
]

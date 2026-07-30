#!/usr/bin/env python3
"""
Consulta de versoes ESP-IDF via GitHub API (@E3-T3.5).

Offline-first: so consulta a rede quando uma versao esta ausente da
matriz local. Fallback para a versao anterior em falha de rede.
Valida todo dado antes de aceitar. Append-only na matriz.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from ..core import logger as _logger
from . import compat_matrix as _matrix

Result = Tuple[bool, Any]

# API GitHub para releases do ESP-IDF.
_GITHUB_API = (
    "https://api.github.com/repos/espressif/esp-idf/releases"
    "?per_page=100"
)

# Apenas versoes 4.x+ sao suportadas (PROJECT.md 5.7).
_MIN_MAJOR = 4

# Timeout de rede (segundos).
_NET_TIMEOUT = 15

# Versao no formato vX.Y ou vX.Y.Z.
_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")

# Faixa de Python por major.minor do ESP-IDF (conhecida-boa).
_PYTHON_RANGES: Dict[str, str] = {
    "4": ">=3.6",
    "5.0": ">=3.7",
    "5.1": ">=3.7",
    "5.2": ">=3.8",
    "5.3": ">=3.9",
    "5.4": ">=3.10",
    "5.5": ">=3.10",
    "6.0": ">=3.10",
}


def _python_range(tag: str) -> str:
    """Infere a faixa de Python para uma tag (best-effort)."""
    m = _VERSION_RE.match(tag)
    if not m:
        return ">=3.8"
    major, minor = m.group(1), m.group(2)
    key_mm = "{}.{}".format(major, minor)
    return (_PYTHON_RANGES.get(key_mm)
            or _PYTHON_RANGES.get(major)
            or ">=3.8")


def _fetch_releases() -> Result:
    """Busca releases estaveis do ESP-IDF via GitHub API."""
    try:
        req = urllib.request.Request(
            _GITHUB_API,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "esplab/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_NET_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list):
            return (False, "resposta inesperada da API GitHub")
        return (True, data)
    except urllib.error.URLError as e:
        return (False, "falha de rede ao consultar GitHub: {}".format(e))
    except Exception as e:
        return (False, "erro ao buscar releases: {}".format(e))


def fetch_stable_versions() -> Result:
    """
    Retorna lista de versoes estaveis 4.x+ disponiveis no GitHub.
    Cada item: {tag, version_key, python_range}.
    Falha de rede -> (False, motivo).
    """
    ok, releases = _fetch_releases()
    if not ok:
        return (False, releases)

    found: List[Dict[str, str]] = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        if rel.get("prerelease") or rel.get("draft"):
            continue
        m = _VERSION_RE.match(tag)
        if not m:
            continue
        major = int(m.group(1))
        if major < _MIN_MAJOR:
            continue
        minor = int(m.group(2))
        patch = int(m.group(3) or 0)
        # Chave na matriz: "major.minor" (sem patch — uma entrada por linha)
        version_key = "{}.{}".format(major, minor)
        found.append({
            "tag":          tag,
            "version_key":  version_key,
            "python_range": _python_range(tag),
        })

    # Deduplica por version_key, mantendo a mais recente.
    seen: Dict[str, Dict] = {}
    for item in found:
        k = item["version_key"]
        if k not in seen:
            seen[k] = item
    return (True, list(seen.values()))


def update_matrix_from_network(version: Optional[str] = None) -> Result:
    """
    Consulta o GitHub e adiciona versoes ausentes na matriz local.

    version: se informado, busca so essa versao (ex. '5.4').
             se None, busca todas as estaveis 4.x+.

    Retorna (True, {added, skipped}) ou (False, motivo).
    Fallback: em falha de rede, opera com a matriz local (nao propaga erro).
    """
    ok, versions = fetch_stable_versions()
    if not ok:
        _logger.get_logger().warning(
            "consulta de rede falhou (%s); operando com matriz local", versions)
        return (True, {"added": [], "skipped": [],
                       "warning": "rede indisponivel; matriz local em uso"})

    # Filtra por versao especifica se solicitado.
    if version:
        versions = [v for v in versions if v["version_key"] == version]
        if not versions:
            return (False, "versao '{}' nao encontrada no GitHub".format(version))

    added: List[str] = []
    skipped: List[str] = []

    for item in versions:
        vk = item["version_key"]
        # Verifica se ja existe na matriz (append-only).
        ok2, entry = _matrix.get_entry(vk)
        if ok2:
            skipped.append(vk)
            continue
        # Monta entrada minima valida.
        new_entry: Dict[str, Any] = {
            "python":       item["python_range"],
            "status":       "desconhecido",
            "dependencies": {},
        }
        ok3, res3 = _matrix.append_version(vk, new_entry)
        if ok3:
            added.append(vk)
            _logger.get_logger().info(
                "versao '%s' adicionada a matriz", vk)
        else:
            _logger.get_logger().warning(
                "falha ao adicionar '%s' a matriz: %s", vk, res3)

    return (True, {"added": added, "skipped": skipped})


__all__ = [
    "fetch_stable_versions",
    "update_matrix_from_network",
]

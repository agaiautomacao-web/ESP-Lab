#!/usr/bin/env python3
"""
Gerenciador de atualizacoes de dependencias (@E4-T4.7).

Categorias com mecanismos distintos:
  - Dependencias Python (textual, pyserial, etc.): via pip no app-venv.
  - esptool: mesmo fluxo do pip, destacado por ser critico.
  - ESP-IDF: gerenciado por idf_manager (submenu de versoes, nao "atualizar").

Mostra "instalado vs disponivel"; atualizacao seletiva.
Respeita pin de versoes criticas.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import paths as _paths
from ..core import errors as _errors
from ..core import logger as _logger
from ..core import app_env as _appenv

Result = Tuple[bool, Any]

# Pacotes criticos: atualizacao exige confirmacao extra (nunca em lote cego).
CRITICAL_PACKAGES = {"esptool", "textual", "pyserial"}

# Timeout para consultas pip (PyPI pode demorar).
_PIP_TIMEOUT = 90


def _pip_bin() -> Path:
    """Caminho do pip do app-venv."""
    return _appenv.venv_dir() / "bin" / "pip"


def list_outdated() -> Result:
    """
    Lista pacotes do app-venv com atualizacao disponivel (consulta PyPI).
    Retorna (True, lista) onde cada item e {name, installed, available, critical}.
    """
    if not _appenv.exists():
        return (False, "app-venv inexistente")
    pip = _pip_bin()
    res = _errors.guard(
        lambda: subprocess.run(
            [str(pip), "list", "--outdated", "--format", "json"],
            capture_output=True, text=True, timeout=_PIP_TIMEOUT),
        context="consulta de pacotes desatualizados",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        return (False, (proc.stderr or proc.stdout or "").strip())
    try:
        data = json.loads(proc.stdout or "[]")
    except Exception as e:
        return (False, "erro ao parsear saida do pip: {}".format(e))

    outdated = []
    for pkg in data:
        nome = pkg.get("name", "")
        outdated.append({
            "name":      nome,
            "installed": pkg.get("version", "?"),
            "available": pkg.get("latest_version", "?"),
            "critical":  nome.lower() in CRITICAL_PACKAGES,
        })
    return (True, outdated)


def update_package(name: str, version: str = "") -> Result:
    """
    Atualiza um pacote no app-venv.
    version: versao especifica (pin). Vazio = ultima disponivel.
    Mostra antes -> depois no retorno.
    """
    if not name or not name.strip():
        return (False, "nome do pacote vazio")
    if not _appenv.exists():
        return (False, "app-venv inexistente")

    name = name.strip()
    alvo = "{}=={}".format(name, version) if version else name + " --upgrade"
    cmd_alvo = ["{}=={}".format(name, version)] if version \
        else [name, "--upgrade"]

    pip = _pip_bin()
    res = _errors.guard(
        lambda: subprocess.run(
            [str(pip), "install"] + cmd_alvo,
            capture_output=True, text=True, timeout=_PIP_TIMEOUT),
        context="atualizacao de pacote",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        return (False, "falha ao atualizar '{}': {}".format(
            name, (proc.stderr or proc.stdout or "").strip()[:300]))

    _logger.get_logger().info("pacote '%s' atualizado", name)
    return (True, {
        "name":    name,
        "message": "pacote '{}' atualizado com sucesso".format(name),
    })


def get_update_summary() -> Result:
    """
    Resumo geral para a TUI: pacotes Python, esptool, ESP-IDF.
    Retorna (True, dict) com as tres categorias.
    """
    resumo: Dict[str, Any] = {
        "python_packages": [],
        "esptool":         None,
        "esp_idf":         "gerenciado em Software > ESP-IDF (versoes)",
    }

    ok, outdated = list_outdated()
    if ok:
        for pkg in outdated:
            if pkg["name"].lower() == "esptool":
                resumo["esptool"] = pkg
            else:
                resumo["python_packages"].append(pkg)
        return (True, resumo)
    return (False, outdated)


__all__ = [
    "list_outdated", "update_package", "get_update_summary",
    "CRITICAL_PACKAGES",
]

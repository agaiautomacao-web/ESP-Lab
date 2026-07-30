#!/usr/bin/env python3
"""
Fonte única de versão do ESP Lab (@E1-T1.3).

A versão vive num único lugar — o arquivo VERSION na raiz da aplicação — e é
lida em runtime. Nada de número de versão hardcoded em dois lugares.

O caminho do VERSION é derivado da raiz descoberta pelo módulo paths; este
módulo não monta caminho próprio (PROJECT.md §4).

Convenção: identificadores em inglês, strings em português.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from . import paths as _paths

Result = Tuple[bool, object]  # (ok, result_or_error)

# Valor exibido quando a versão não pôde ser lida — visível e inconfundível,
# para nunca mascarar um problema com um número falso plausível.
UNKNOWN = "0.0.0-desconhecida"


def version_file() -> Path:
    """Caminho do arquivo VERSION, na raiz da aplicação."""
    return _paths.get_app_root() / "VERSION"


def read_version() -> Result:
    """
    Lê e valida a versão do arquivo VERSION.

    Sucesso -> (True, "X.Y.Z")
    Falha   -> (False, motivo)  — arquivo ausente, vazio ou formato inválido.

    Valida o formato SemVer básico (três números separados por ponto,
    com sufixo opcional após '-'), pois um VERSION corrompido não deve
    circular pela aplicação como se fosse válido.
    """
    try:
        path = version_file()
    except Exception as e:
        return (False, f"não foi possível resolver a raiz da aplicação: {e}")

    try:
        if not path.is_file():
            return (False, f"arquivo VERSION inexistente: '{path}'")
        raw = path.read_text(encoding="utf-8").strip()
    except Exception as e:
        return (False, f"falha ao ler VERSION: {e}")

    if not raw:
        return (False, "arquivo VERSION está vazio")

    if not _is_semver(raw):
        return (False, f"formato de versão inválido: '{raw}'")

    return (True, raw)


def get_version() -> str:
    """
    Versão pronta para exibição. Nunca lança: em qualquer falha devolve
    UNKNOWN, para o cabeçalho da TUI sempre ter algo seguro para mostrar.
    """
    ok, value = read_version()
    return value if ok else UNKNOWN


def _is_semver(s: str) -> bool:
    """
    Validação SemVer básica: MAJOR.MINOR.PATCH, cada parte numérica,
    com sufixo opcional de pré-lançamento/metadado após '-'.
    """
    core = s.split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3:
        return False
    return all(p.isdigit() for p in parts)


__all__ = ["read_version", "get_version", "version_file", "UNKNOWN"]

#!/usr/bin/env python3
"""
Persistência de sessão do ESP Lab.

A sessão guarda somente o projeto ativo e os últimos projetos usados.
Porta e perfil de hardware são contexto de runtime/projeto, nunca estado
global persistente.

Contrato: (ok, result_or_error); nunca lança.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import storage as _storage
from . import paths as _paths

Result = Tuple[bool, Any]
SESSION_FILENAME = "session.json"
MAX_RECENTES = 5


def _session_path() -> Path:
    return _paths.get_paths().data_home / SESSION_FILENAME


def _default() -> Dict[str, Any]:
    return {"projeto_ativo": None, "recentes": []}


def _normalize(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return _default()
    recentes = data.get("recentes", [])
    if not isinstance(recentes, list):
        recentes = []
    return {
        "projeto_ativo": data.get("projeto_ativo") or None,
        "recentes": [str(item) for item in recentes if item],
    }


def read() -> Result:
    ok, data = _storage.read_json(_session_path())
    return (True, _normalize(data if ok else None))


def set_projeto_ativo(project_path: str | Path) -> Result:
    caminho = str(Path(project_path).expanduser().resolve())

    def _mutar(atual: Dict) -> Dict:
        sessao = _normalize(atual)
        sessao["projeto_ativo"] = caminho
        recentes = [item for item in sessao["recentes"] if item != caminho]
        recentes.insert(0, caminho)
        sessao["recentes"] = recentes[:MAX_RECENTES]
        return sessao

    return _storage.update_json(_session_path(), _mutar, default=_default())


def clear_projeto_ativo() -> Result:
    def _mutar(atual: Dict) -> Dict:
        sessao = _normalize(atual)
        sessao["projeto_ativo"] = None
        return sessao
    return _storage.update_json(_session_path(), _mutar, default=_default())


def get_projeto_ativo() -> Optional[str]:
    _, sessao = read()
    caminho = sessao.get("projeto_ativo")
    if not caminho:
        return None
    if not Path(caminho).is_dir():
        clear_projeto_ativo()
        return None
    return str(caminho)


def get_recentes() -> List[str]:
    _, sessao = read()
    recentes = sessao.get("recentes", [])
    validos = [item for item in recentes if Path(item).is_dir()]
    if validos != recentes:
        def _limpar(atual: Dict) -> Dict:
            normalized = _normalize(atual)
            normalized["recentes"] = validos
            return normalized
        _storage.update_json(_session_path(), _limpar, default=_default())
    return validos


def set_perfil_dispositivo_ativo(mac: str) -> Result:
    """Compatibilidade: o perfil global foi removido do modelo de estado."""
    return (
        False,
        "perfil global de dispositivo foi removido; associe o MAC ao projeto",
    )


def clear_perfil_dispositivo_ativo() -> Result:
    """Compatibilidade: não existe mais estado global para limpar."""
    return (True, "nenhum perfil global persistido")


def get_perfil_dispositivo_ativo() -> Optional[str]:
    """Compatibilidade: sempre devolve None."""
    return None


__all__ = [
    "read", "set_projeto_ativo", "clear_projeto_ativo",
    "get_projeto_ativo", "get_recentes",
    "set_perfil_dispositivo_ativo", "clear_perfil_dispositivo_ativo",
    "get_perfil_dispositivo_ativo",
    "MAX_RECENTES", "SESSION_FILENAME",
]

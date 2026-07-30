#!/usr/bin/env python3
"""
Cache versionado de componentes/bibliotecas do ESP Lab.

Politica central:
  - nunca substituir automaticamente uma biblioteca existente
  - mesma biblioteca + mesma versao: reaproveita entrada existente
  - mesma biblioteca + versao diferente: cria outra entrada lado a lado
  - o ESP-IDF oficial fica limpo; nada externo e copiado para data/esp-idf
  - downloads/importacoes futuras devem ir para data/components/

Esta camada NAO:
  - baixa arquivos
  - copia bibliotecas locais
  - edita idf_component.yml
  - edita CMakeLists.txt
  - roda idf.py
  - compila
  - reconfigura

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import paths as _paths
from ..core import storage as _storage

Result = Tuple[bool, Any]

SCHEMA_VERSION = 1
STORE_DIRNAME = "components"
METADATA_FILENAME = "metadata.json"
SOURCE_DIRNAME = "source"

SUPPORTED_SOURCES = {
    "registry",
    "arduino",
    "git",
    "local",
    "converted",
}

_RE_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.+\-]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    """
    Gera segmento seguro de caminho, preservando leitura humana.

    Exemplos:
      espressif/led_strip -> espressif__led_strip
      ArduinoJson         -> ArduinoJson
      7.4.2               -> 7.4.2
    """
    raw = str(value or "").strip()
    raw = raw.replace("/", "__").replace("\\", "__")
    raw = _RE_SAFE_SEGMENT.sub("_", raw)
    raw = raw.strip("._-")
    return raw or "unnamed"


def _validate_source(source: str) -> str | None:
    s = str(source or "").strip().lower()
    if not s:
        return "origem vazia"
    if s not in SUPPORTED_SOURCES:
        return "origem '{}' invalida; use uma de: {}".format(
            source, ", ".join(sorted(SUPPORTED_SOURCES)))
    return None


def _validate_name(name: str) -> str | None:
    n = str(name or "").strip()
    if not n:
        return "nome vazio"
    return None


def _validate_version(version: str) -> str | None:
    v = str(version or "").strip()
    if not v:
        return "versao vazia"
    if v in {"*", "latest", "ultima", "última"}:
        return (
            "cache versionado exige versao concreta; '{}' nao identifica "
            "uma copia fixa"
        ).format(version)
    return None


def get_store_root(store_root: str | Path | None = None) -> Path:
    """
    Retorna a raiz do cache de componentes.

    Default:
      data/components

    Em testes, aceite store_root para nao tocar no cache real.
    """
    if store_root is not None:
        return Path(store_root).expanduser().resolve()
    return (_paths.get_paths().data_home / STORE_DIRNAME).resolve()


def component_cache_path(
    source: str,
    name: str,
    version: str,
    store_root: str | Path | None = None,
) -> Result:
    """
    Retorna caminho da entrada versionada no cache.
    Nao cria diretorios.
    """
    err = _validate_source(source) or _validate_name(name) or _validate_version(version)
    if err:
        return (False, err)

    root = get_store_root(store_root)
    path = root / source.strip().lower() / _slug(name) / _slug(version)
    return (True, path)


def component_source_path(
    source: str,
    name: str,
    version: str,
    store_root: str | Path | None = None,
) -> Result:
    """
    Retorna a pasta onde o codigo-fonte baixado/importado ficara.
    Nao cria diretorios.
    """
    ok, base = component_cache_path(source, name, version, store_root)
    if not ok:
        return (False, base)
    return (True, base / SOURCE_DIRNAME)


def _metadata_path(base: Path) -> Path:
    return base / METADATA_FILENAME


def _read_metadata(path: Path) -> Result:
    if not path.is_file():
        return (False, "metadata.json inexistente em '{}'".format(path))
    ok, data = _storage.read_json(path)
    if not ok:
        return (False, data)
    if not isinstance(data, dict):
        return (False, "metadata.json corrompido em '{}'".format(path))
    return (True, data)


def register_component(
    source: str,
    name: str,
    version: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    store_root: str | Path | None = None,
) -> Result:
    """
    Registra uma entrada versionada no cache.

    Se a mesma origem/nome/versao ja existir:
      - nao sobrescreve
      - nao atualiza metadata
      - retorna status 'already_exists'

    Se a versao for diferente:
      - cria outra pasta versionada lado a lado
    """
    ok, base = component_cache_path(source, name, version, store_root)
    if not ok:
        return (False, base)

    source_norm = source.strip().lower()
    name_norm = name.strip()
    version_norm = version.strip()

    meta_path = _metadata_path(base)

    if base.exists():
        existing_meta = None
        if meta_path.is_file():
            ok_meta, existing_meta = _read_metadata(meta_path)
            if not ok_meta:
                existing_meta = {"metadata_error": existing_meta}

        return (True, {
            "status": "already_exists",
            "message": (
                "entrada ja existe; nada foi sobrescrito: "
                "{} {} {}"
            ).format(source_norm, name_norm, version_norm),
            "cache_path": str(base),
            "source_path": str(base / SOURCE_DIRNAME),
            "metadata": existing_meta,
        })

    user_meta = dict(metadata or {})
    now = _now()

    final_meta: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": source_norm,
        "name": name_norm,
        "version": version_norm,
        "name_slug": _slug(name_norm),
        "version_slug": _slug(version_norm),
        "created_at": now,
        "updated_at": now,
        "cache_path": str(base),
        "source_path": str(base / SOURCE_DIRNAME),
    }

    # Metadados extras nao podem sobrescrever os campos de controle acima.
    for key, value in user_meta.items():
        if key not in final_meta:
            final_meta[key] = value

    try:
        (base / SOURCE_DIRNAME).mkdir(parents=True, exist_ok=False)
    except Exception as e:
        return (False, "erro ao criar entrada de cache '{}': {}".format(base, e))

    ok_write, res = _storage.atomic_write_json(meta_path, final_meta)
    if not ok_write:
        return (False, "erro ao gravar metadata '{}': {}".format(meta_path, res))

    return (True, {
        "status": "created",
        "message": "entrada criada no cache: {} {} {}".format(
            source_norm, name_norm, version_norm),
        "cache_path": str(base),
        "source_path": str(base / SOURCE_DIRNAME),
        "metadata": final_meta,
    })


def get_component_metadata(
    source: str,
    name: str,
    version: str,
    *,
    store_root: str | Path | None = None,
) -> Result:
    """
    Le metadata de uma entrada versionada especifica.
    """
    ok, base = component_cache_path(source, name, version, store_root)
    if not ok:
        return (False, base)
    return _read_metadata(_metadata_path(base))


def list_versions(
    source: str,
    name: str,
    *,
    store_root: str | Path | None = None,
) -> Result:
    """
    Lista versoes existentes de uma origem/nome.
    """
    err = _validate_source(source) or _validate_name(name)
    if err:
        return (False, err)

    root = get_store_root(store_root)
    lib_dir = root / source.strip().lower() / _slug(name)

    if not lib_dir.is_dir():
        return (True, {
            "source": source.strip().lower(),
            "name": name.strip(),
            "name_slug": _slug(name),
            "count": 0,
            "versions": [],
        })

    versions: List[Dict[str, Any]] = []

    for child in sorted(lib_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue

        meta_path = _metadata_path(child)
        meta = None
        if meta_path.is_file():
            ok_meta, data = _read_metadata(meta_path)
            meta = data if ok_meta else {"metadata_error": data}

        versions.append({
            "version_slug": child.name,
            "cache_path": str(child.resolve()),
            "source_path": str((child / SOURCE_DIRNAME).resolve()),
            "metadata": meta,
        })

    return (True, {
        "source": source.strip().lower(),
        "name": name.strip(),
        "name_slug": _slug(name),
        "count": len(versions),
        "versions": versions,
    })


def list_components(
    *,
    source: str | None = None,
    store_root: str | Path | None = None,
) -> Result:
    """
    Lista componentes registrados no cache.

    Se source for informado, lista apenas aquela origem.
    """
    root = get_store_root(store_root)

    sources: List[str]
    if source is None:
        sources = sorted(SUPPORTED_SOURCES)
    else:
        err = _validate_source(source)
        if err:
            return (False, err)
        sources = [source.strip().lower()]

    items: List[Dict[str, Any]] = []

    for src in sources:
        src_dir = root / src
        if not src_dir.is_dir():
            continue

        for name_dir in sorted(src_dir.iterdir(), key=lambda p: p.name.lower()):
            if not name_dir.is_dir():
                continue

            version_count = 0
            for version_dir in name_dir.iterdir():
                if version_dir.is_dir():
                    version_count += 1

            items.append({
                "source": src,
                "name_slug": name_dir.name,
                "path": str(name_dir.resolve()),
                "version_count": version_count,
            })

    return (True, {
        "store_root": str(root),
        "count": len(items),
        "components": items,
    })


__all__ = [
    "SUPPORTED_SOURCES",
    "get_store_root",
    "component_cache_path",
    "component_source_path",
    "register_component",
    "get_component_metadata",
    "list_versions",
    "list_components",
]

#!/usr/bin/env python3
"""
Matriz de compatibilidade ESP-IDF x dependencias (@E3-T3.1..T3.4).

Schema v2 — modelo de SLOTS, nao mais mapa aberto de versoes soltas.

Carrega a matriz (YAML), valida na fronteira. Cada slot tem um papel:

  fixed     : tag imutavel (PROJECT.md 5.7). "Reparar" sempre reinstala
              este mesmo tag, nunca promove patch. 'eol' distingue duas
              razoes de ser fixa: eol=true = a propria Espressif nao
              lanca mais bugfix nessa linha (congelada para sempre,
              ex. 4.4, 5.1); eol=false = a linha ainda recebe patch a
              montante, mas o ESP Lab optou por nao acompanhar.
  updatable : SEM 'tag' no schema — a release corrente e mutavel e vive
              no registro operacional (idf_registry.json), nao aqui.
              'seed_tag' e usado so na primeira instalacao do slot,
              quando o registro ainda nao tem nenhuma release gravada;
              depois disso o registro manda, seed_tag nunca mais e lido.
              Exatamente 1 slot 'updatable' e obrigatorio no schema —
              nunca zero, nunca mais de um.

Principios (PROJECT.md cap. Software):
  - Offline-first: a matriz embarcada (data/compat_matrix.yml) e a fonte
    local conhecida-boa. Funciona sem rede.
  - A matriz muda muito raramente e por acao explicita (ex. "formatura"
    de um slot atualizavel para fixo, quando uma nova linha e adotada) —
    nunca automaticamente por descoberta de rede.
  - Validacao na fronteira: todo dado passa por validacao de esquema e
    formato antes de ser aceito; malformado e rejeitado, nunca absorvido.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import paths as _paths
from ..core import storage as _storage
from ..core import logger as _logger

Result = Tuple[bool, Any]  # (ok, result_or_error)

SUPPORTED_SCHEMA = 2

VALID_ROLES = ("fixed", "updatable")

# Faixa de versao estilo pip: operadores seguidos de versao, separados por
# virgula. Ex.: ">=3.9", ">=4.0,<5.0", "==4.7.1". Valida so a SINTAXE.
_RANGE_RE = re.compile(
    r"^\s*(?:(?:>=|<=|==|!=|>|<|~=)\s*\d+(?:\.\d+)*\s*)(?:,\s*(?:>=|<=|==|!=|>|<|~=)\s*\d+(?:\.\d+)*\s*)*$"
)

# Chave de slot na matriz: familia major.minor, ex. "4.4", "5.3".
_SLOT_KEY_RE = re.compile(r"^\d+(?:\.\d+)+$")

# Tag real de release ESP-IDF (o que 'git clone --branch' de fato aceita):
# vMAJOR.MINOR.PATCH. Formatos como "v5.4" (sem patch) NAO sao tags validas
# no repositorio oficial — essa e a causa raiz do bug corrigido nesta sessao.
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


# ==========================================================
# LOCALIZACAO
# ==========================================================

def embedded_path() -> Path:
    """Matriz embarcada (conhecida-boa), distribuida com a aplicacao."""
    return _paths.get_app_root() / "src" / "esplab" / "software" / "data" / "compat_matrix.yml"


def user_path() -> Path:
    """
    Matriz do usuario (config_home) — override manual, se algum dia existir.
    NAO e mais o destino de escrita automatica (nao ha mais append_version
    de rede): schema v2 muda so por acao explicita de formatura de slot.
    """
    return _paths.get_paths().compat_matrix


# ==========================================================
# VALIDACAO NA FRONTEIRA
# ==========================================================

def _is_valid_range(value: Any) -> bool:
    return isinstance(value, str) and bool(_RANGE_RE.match(value))


def _is_valid_tag(value: Any) -> bool:
    return isinstance(value, str) and bool(_TAG_RE.match(value))


def validate(matrix: Any) -> Result:
    """
    Valida a estrutura da matriz (schema v2). (True, matrix) ou (False, motivo).
    """
    if not isinstance(matrix, dict):
        return (False, "matriz invalida: raiz nao e um mapa")

    schema = matrix.get("schema_version")
    if not isinstance(schema, int):
        return (False, "schema_version ausente ou nao inteiro")
    if schema != SUPPORTED_SCHEMA:
        return (False, f"schema_version {schema} nao suportado (esperado {SUPPORTED_SCHEMA})")

    slots = matrix.get("slots")
    if not isinstance(slots, dict) or not slots:
        return (False, "bloco 'slots' ausente ou vazio")

    updatable_count = 0

    for key, entry in slots.items():
        if not _SLOT_KEY_RE.match(str(key)):
            return (False, f"chave de slot em formato invalido: '{key}'")
        if not isinstance(entry, dict):
            return (False, f"slot '{key}' nao e um mapa")

        role = entry.get("role")
        if role not in VALID_ROLES:
            return (False, f"slot '{key}': 'role' invalido ou ausente (esperado fixed/updatable)")

        py = entry.get("python")
        if not _is_valid_range(py):
            return (False, f"slot '{key}': faixa de python invalida: '{py}'")

        if role == "fixed":
            tag = entry.get("tag")
            if not _is_valid_tag(tag):
                return (False, f"slot '{key}' (fixed): 'tag' ausente ou invalido: '{tag}'")
            if "seed_tag" in entry:
                return (False, f"slot '{key}' (fixed): nao deve ter 'seed_tag'")
            if not isinstance(entry.get("eol"), bool):
                return (False, f"slot '{key}' (fixed): campo 'eol' ausente ou nao-booleano")
            # familia do tag tem que bater com a chave do slot (evita o
            # descasamento "5.3" vs "v5.4.4" que quebrava o schema v1).
            fam = family_of_tag(tag)
            if fam != str(key):
                return (False,
                        f"slot '{key}': tag '{tag}' pertence a familia '{fam}', nao a '{key}'")

        else:  # updatable
            updatable_count += 1
            if "tag" in entry:
                return (False, f"slot '{key}' (updatable): nao deve ter 'tag' fixo "
                                "(release corrente vive no registro)")
            seed = entry.get("seed_tag")
            if not _is_valid_tag(seed):
                return (False, f"slot '{key}' (updatable): 'seed_tag' ausente ou invalido: '{seed}'")
            fam = family_of_tag(seed)
            if fam != str(key):
                return (False,
                        f"slot '{key}': seed_tag '{seed}' pertence a familia '{fam}', nao a '{key}'")

    if updatable_count != 1:
        return (False, f"schema exige exatamente 1 slot 'updatable'; encontrados {updatable_count}")

    return (True, matrix)


def family_of_tag(tag: str) -> str | None:
    """
    Extrai a familia 'major.minor' de uma tag ESP-IDF (ex. 'v5.4.4' -> '5.4').
    Retorna None se o formato nao for reconhecido. Nunca lanca.
    """
    m = re.match(r"^v?(\d+)\.(\d+)", str(tag or ""))
    return f"{m.group(1)}.{m.group(2)}" if m else None


# ==========================================================
# CARGA (offline-first)
# ==========================================================

def load() -> Result:
    """
    Carrega a matriz. Preferencia: matriz do usuario (se existir e valida);
    senao, a embarcada. Valida antes de devolver. Nunca lanca.
    """
    up = user_path()
    if up.is_file():
        ok, data = _storage.read_yaml(up)
        if ok:
            v_ok, v_res = validate(data)
            if v_ok:
                return (True, data)
            _logger.get_logger().warning(
                "matriz do usuario invalida (%s); usando a embarcada", v_res
            )
        else:
            _logger.get_logger().warning(
                "falha ao ler matriz do usuario (%s); usando a embarcada", data
            )

    # Fallback: embarcada
    ok, data = _storage.read_yaml(embedded_path())
    if not ok:
        return (False, f"matriz embarcada ilegivel: {data}")
    return validate(data)


# ==========================================================
# CONSULTA
# ==========================================================

def get_slot(slot_key: str) -> Result:
    """Retorna a entrada de um slot. (True, dict) ou (False, motivo)."""
    ok, matrix = load()
    if not ok:
        return (False, matrix)
    entry = matrix["slots"].get(slot_key)
    if entry is None:
        return (False, f"slot '{slot_key}' ausente na matriz")
    return (True, entry)


def list_slots() -> Result:
    """Lista as chaves de slot na matriz, ordenadas. (True, [chaves]) ou (False, motivo)."""
    ok, matrix = load()
    if not ok:
        return (False, matrix)
    return (True, sorted(matrix["slots"].keys(), key=lambda v: [int(x) for x in v.split(".")]))


def fixed_slots() -> Result:
    """Chaves dos slots fixos, ordenadas. (True, [chaves]) ou (False, motivo)."""
    ok, matrix = load()
    if not ok:
        return (False, matrix)
    keys = [k for k, v in matrix["slots"].items() if v.get("role") == "fixed"]
    return (True, sorted(keys, key=lambda v: [int(x) for x in v.split(".")]))


def updatable_slot() -> Result:
    """
    Chave do (unico) slot atualizavel. (True, chave) ou (False, motivo).
    validate() ja garante que existe exatamente um — aqui e so leitura.
    """
    ok, matrix = load()
    if not ok:
        return (False, matrix)
    for key, entry in matrix["slots"].items():
        if entry.get("role") == "updatable":
            return (True, key)
    return (False, "nenhum slot 'updatable' na matriz (matriz deveria ter sido rejeitada na validacao)")


__all__ = [
    "load", "validate", "get_slot", "list_slots", "fixed_slots", "updatable_slot",
    "family_of_tag", "embedded_path", "user_path", "SUPPORTED_SCHEMA", "VALID_ROLES",
]

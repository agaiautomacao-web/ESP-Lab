#!/usr/bin/env python3
"""
monitor_prefs.py — preferencias GLOBAIS de leitura do monitor (@E10 P5).

Duas preferencias que sao da tela, nao da placa: carimbo de hora e tamanho
do buffer de exibicao. Por serem globais (nao por porta), vivem separadas
do port_config (que e por porta) — em config/monitor.json, via storage.

O baud e por porta e NAO mora aqui: fica no port_config
(get/set_monitor_baudrate), porque e fato fisico da placa.

Persistencia: JSON atomico em config_home/monitor.json (paths.monitor_config).
Nasce sozinho na primeira gravacao, com defaults. Nunca lanca.
Retorno (ok, result_or_error); strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..core import paths as _paths
from ..core import storage as _storage

Result = Tuple[bool, Any]

# Defaults funcionais (o monitor opera bem sem o usuario configurar nada).
DEFAULT_TIMESTAMP = True
DEFAULT_BUFFER_LINES = 500

# Limites sensatos para o buffer: pequeno demais perde contexto, grande
# demais pesa a tela sem ganho (o log em disco guarda tudo de qualquer jeito).
BUFFER_MIN = 50
BUFFER_MAX = 5000

_DEFAULTS: Dict[str, Any] = {
    "timestamp":    DEFAULT_TIMESTAMP,
    "buffer_lines": DEFAULT_BUFFER_LINES,
}


def _config_path():
    return _paths.get_paths().monitor_config


def get_monitor_prefs() -> Dict[str, Any]:
    """
    Preferencias globais atuais, com defaults preenchidos para chaves
    ausentes. Nunca lanca: arquivo ausente ou corrompido devolve defaults.
    """
    ok, data = _storage.read_json(_config_path())
    if not ok or not isinstance(data, dict):
        return dict(_DEFAULTS)
    out = dict(_DEFAULTS)
    if isinstance(data.get("timestamp"), bool):
        out["timestamp"] = data["timestamp"]
    if isinstance(data.get("buffer_lines"), int):
        out["buffer_lines"] = _clamp_buffer(data["buffer_lines"])
    return out


def _clamp_buffer(n: int) -> int:
    return max(BUFFER_MIN, min(BUFFER_MAX, n))


def set_monitor_pref(key: str, value: Any) -> Result:
    """
    Define uma preferencia global. Valida por chave; valor invalido e
    recusado (nao grava). Cria o arquivo com defaults na primeira escrita.
    """
    if key == "timestamp":
        if not isinstance(value, bool):
            return (False, "timestamp deve ser verdadeiro/falso")
        novo = value
    elif key == "buffer_lines":
        if not isinstance(value, int) or isinstance(value, bool):
            return (False, "tamanho do buffer deve ser um numero inteiro")
        if value < BUFFER_MIN or value > BUFFER_MAX:
            return (False, "buffer fora do intervalo ({}-{})".format(
                BUFFER_MIN, BUFFER_MAX))
        novo = value
    else:
        return (False, "preferencia desconhecida: '{}'".format(key))

    def _mut(cur: Any) -> Any:
        if not isinstance(cur, dict):
            cur = {}
        cur[key] = novo
        return cur

    ok, res = _storage.update_json(_config_path(), _mut, default=dict(_DEFAULTS))
    return (True, {"key": key, "value": novo}) if ok else (False, res)


__all__ = [
    "get_monitor_prefs", "set_monitor_pref",
    "DEFAULT_TIMESTAMP", "DEFAULT_BUFFER_LINES",
    "BUFFER_MIN", "BUFFER_MAX",
]

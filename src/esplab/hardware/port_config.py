#!/usr/bin/env python3
"""
Configuracao persistente de portas seriais (@E6-T6.1 a T6.4).

Salva por porta: nome amigavel, baudrate, estado de uso.
Baudrate e opcoes de deploy sao SEMPRE selecionados de lista —
nunca digitacao livre (valor invalido nao entra).

Persistencia: JSON atomico em config_home/port_configs.json.
Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import paths as _paths
from ..core import storage as _storage

Result = Tuple[bool, Any]

# Baudrates disponiveis (lista fechada — sem digitacao livre).
BAUDRATES: List[int] = [
    9600, 19200, 38400, 57600, 74880,
    115200, 230400, 460800, 921600,
]
DEFAULT_BAUDRATE = 115200

# Opcoes de deploy selecionaveis por lista (@E6-T6.4).
DEPLOY_OPTIONS: Dict[str, List[str]] = {
    "psram":      ["Desativado", "Ativado"],
    "debug_level": ["Nenhum", "Erro", "Aviso", "Info", "Debug", "Verbose"],
    "monitor_output": ["Console interno", "Terminal externo", "Arquivo de log"],
}

CONFIG_FILENAME = "port_configs.json"


def _config_path() -> Path:
    return _paths.get_paths().config_home / CONFIG_FILENAME


def _load() -> Dict[str, Any]:
    """Carrega o arquivo de configuracoes de porta. Retorna {} se ausente."""
    ok, data = _storage.read_json(_config_path())
    if not ok or not isinstance(data, dict):
        return {}
    return data


def _save(data: Dict[str, Any]) -> Result:
    return _storage.atomic_write_json(_config_path(), data)


def get_port_config(device: str) -> Dict[str, Any]:
    """
    Retorna a configuracao de uma porta. Se nao existir, retorna o padrao.
    Nunca lanca.
    """
    data = _load()
    cfg  = data.get(device, {})
    return {
        "device":         device,
        "friendly_name":  cfg.get("friendly_name", ""),
        "baudrate":       cfg.get("baudrate", DEFAULT_BAUDRATE),
        "monitor_baudrate": cfg.get("monitor_baudrate", DEFAULT_BAUDRATE),
        "in_use":         cfg.get("in_use", False),
        "deploy": {
            "psram":          cfg.get("deploy", {}).get("psram", "Desativado"),
            "debug_level":    cfg.get("deploy", {}).get("debug_level", "Nenhum"),
            "monitor_output": cfg.get("deploy", {}).get(
                "monitor_output", "Console interno"),
        },
    }


def set_friendly_name(device: str, name: str) -> Result:
    """
    Define o nome amigavel (apelido) de uma porta (@E6-T6.1).
    name pode ser string vazia (limpa o apelido).
    """
    if not isinstance(name, str):
        return (False, "nome deve ser uma string")
    data = _load()
    data.setdefault(device, {})["friendly_name"] = name.strip()
    ok, res = _save(data)
    return (True, {"device": device, "friendly_name": name.strip()}) if ok \
        else (False, res)


def set_baudrate(device: str, baudrate: int) -> Result:
    """
    Define o baudrate de uma porta (@E6-T6.2).
    Aceita apenas valores da lista BAUDRATES — sem digitacao livre.
    """
    if baudrate not in BAUDRATES:
        return (False, "baudrate invalido: {}; opcoes: {}".format(
            baudrate, BAUDRATES))
    data = _load()
    data.setdefault(device, {})["baudrate"] = baudrate
    ok, res = _save(data)
    return (True, {"device": device, "baudrate": baudrate}) if ok \
        else (False, res)


def get_monitor_baudrate(device: str) -> int:
    """
    Baud do MONITOR de uma porta (distinto do baud de upload do esptool).
    Sao coisas diferentes: o upload negocia alta velocidade (460800+),
    o monitor le o console do firmware (tipicamente 115200). Misturar os
    dois quebraria um ou outro. Nunca lanca; default se ausente.
    """
    data = _load()
    return data.get(device, {}).get("monitor_baudrate", DEFAULT_BAUDRATE)


def set_monitor_baudrate(device: str, baudrate: int) -> Result:
    """
    Define o baud do MONITOR de uma porta (@E10 P5).
    Aceita apenas valores de BAUDRATES — sem digitacao livre. Grava em
    campo proprio (monitor_baudrate), sem tocar o baud de upload.
    """
    if baudrate not in BAUDRATES:
        return (False, "baudrate invalido: {}; opcoes: {}".format(
            baudrate, BAUDRATES))
    data = _load()
    data.setdefault(device, {})["monitor_baudrate"] = baudrate
    ok, res = _save(data)
    return (True, {"device": device, "monitor_baudrate": baudrate}) if ok \
        else (False, res)


def set_in_use(device: str, in_use: bool) -> Result:
    """
    Marca/desmarca porta como em uso (@E6-T6.3).
    Porta em uso e inibida na selecao — sem encerramento automatico.
    """
    data = _load()
    data.setdefault(device, {})["in_use"] = bool(in_use)
    ok, res = _save(data)
    return (True, {"device": device, "in_use": in_use}) if ok \
        else (False, res)


def set_deploy_option(device: str, option: str, value: str) -> Result:
    """
    Define uma opcao de deploy (@E6-T6.4).
    option: chave em DEPLOY_OPTIONS. value: um dos valores permitidos.
    Sem digitacao livre — valor fora da lista e recusado.
    """
    if option not in DEPLOY_OPTIONS:
        return (False, "opcao de deploy invalida: '{}'; disponiveis: {}".format(
            option, list(DEPLOY_OPTIONS.keys())))
    if value not in DEPLOY_OPTIONS[option]:
        return (False, "valor invalido para '{}': '{}'; opcoes: {}".format(
            option, value, DEPLOY_OPTIONS[option]))
    data = _load()
    data.setdefault(device, {}).setdefault("deploy", {})[option] = value
    ok, res = _save(data)
    return (True, {"device": device, "option": option, "value": value}) if ok \
        else (False, res)


def list_available_ports(all_ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filtra lista de portas, marcando as que estao em uso (@E6-T6.3).
    Porta em uso recebe campo 'inhibited': True.
    Nao remove da lista — a TUI decide como exibir.
    """
    data = _load()
    resultado = []
    for port in all_ports:
        dev = port["device"]
        cfg = data.get(dev, {})
        enriquecida = dict(port)
        enriquecida["friendly_name"] = cfg.get("friendly_name", "")
        enriquecida["baudrate"]      = cfg.get("baudrate", DEFAULT_BAUDRATE)
        enriquecida["inhibited"]     = cfg.get("in_use", False)
        resultado.append(enriquecida)
    return resultado


__all__ = [
    "get_port_config", "set_friendly_name", "set_baudrate",
    "get_monitor_baudrate", "set_monitor_baudrate",
    "set_in_use", "set_deploy_option", "list_available_ports",
    "BAUDRATES", "DEFAULT_BAUDRATE", "DEPLOY_OPTIONS",
]

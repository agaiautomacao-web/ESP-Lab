#!/usr/bin/env python3
"""
Deteccao de portas seriais do ESP Lab (@E2-T2.4).

Lista as portas seriais do sistema e marca quais sao candidatas a ESP32 com
base no VID/PID do chip USB-serial. Retorna TODAS as portas (nao esconde as
nao-ESP), apenas sinaliza as provaveis.

"Provavel ESP" e so um indicio pelo VID; a confirmacao real vem ao interrogar
o chip via esptool (peca posterior).

Fronteira de dados: a saida bruta do pyserial NAO vaza; cada porta e
normalizada num dicionario estavel.

Retorno (ok, result_or_error); nunca lanca; se o pyserial faltar, falha com
mensagem clara. Mensagens em portugues.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..core import errors as _errors

Result = Tuple[bool, Any]  # (ok, result_or_error)

# VIDs (Vendor IDs) conhecidos de chips USB-serial comuns em placas ESP32.
# Lista editavel: adicionar outros conforme encontrados na pratica.
KNOWN_ESP_VIDS: Dict[int, str] = {
    0x10C4: "Silicon Labs (CP210x)",
    0x1A86: "QinHeng (CH340/CH9102)",
    0x0403: "FTDI",
    0x303A: "Espressif (USB nativo)",
}

# Prefixos de dispositivos que sao portas seriais INTERNAS do sistema
# (UARTs de placa-mae), raramente relevantes para ESP32. Sao detectadas e
# marcadas, mas a ocultacao fica a cargo da camada de interface.
SYSTEM_INTERNAL_PREFIXES = ("/dev/ttyS",)


def _is_system_internal(device: str) -> bool:
    """True se o device e uma porta serial interna do sistema."""
    return any(device.startswith(p) for p in SYSTEM_INTERNAL_PREFIXES)


def _load_pyserial():
    """Importa pyserial sob demanda; None se ausente."""
    try:
        import serial.tools.list_ports as lp  # type: ignore
        return lp
    except Exception:
        return None


def _normalize(port: Any) -> Dict[str, Any]:
    """
    Converte um objeto ListPortInfo do pyserial num dicionario estavel.
    Campos ausentes viram placeholder honesto, nunca None silencioso.
    """
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    is_probable = vid in KNOWN_ESP_VIDS

    return {
        "device": getattr(port, "device", "") or "Desconhecido",
        "description": getattr(port, "description", "") or "Desconhecido",
        "vid": vid,                      # int ou None
        "pid": pid,                      # int ou None
        "vid_hex": f"0x{vid:04X}" if isinstance(vid, int) else "Desconhecido",
        "pid_hex": f"0x{pid:04X}" if isinstance(pid, int) else "Desconhecido",
        "manufacturer": getattr(port, "manufacturer", None) or "Desconhecido",
        "serial_number": getattr(port, "serial_number", None) or "Desconhecido",
        "probable_esp": is_probable,
        "chip_hint": KNOWN_ESP_VIDS.get(vid, "Desconhecido") if is_probable else "Nenhum",
        "system_internal": _is_system_internal(getattr(port, "device", "") or ""),
    }


def list_ports() -> Result:
    """
    Lista todas as portas seriais do sistema, normalizadas.
    Retorna (True, [dict, ...]) ou (False, motivo).
    As provaveis ESP aparecem primeiro; depois, ordem por device.
    """
    lp = _load_pyserial()
    if lp is None:
        return (False, "pyserial nao esta disponivel no ambiente")

    res = _errors.guard(lambda: list(lp.comports()), context="varredura de portas")
    ok, raw = res
    if not ok:
        return (False, raw)

    ports: List[Dict[str, Any]] = [_normalize(p) for p in raw]
    # provaveis primeiro, depois alfabetica por device
    ports.sort(key=lambda d: (not d["probable_esp"], d["device"]))
    return (True, ports)


def probable_esp_ports() -> Result:
    """Atalho: so as portas marcadas como provaveis ESP."""
    ok, ports = list_ports()
    if not ok:
        return (False, ports)
    return (True, [p for p in ports if p["probable_esp"]])


__all__ = ["list_ports", "probable_esp_ports", "KNOWN_ESP_VIDS", "SYSTEM_INTERNAL_PREFIXES"]

#!/usr/bin/env python3
"""
Interrogacao do chip via esptool (@E5-T5.3).

Dada uma porta, pergunta ao chip quem ele e e devolve os dados normalizados
(familia, revisao, flash, MAC). Alimenta o reconhecimento de placa.

LEITURA NAO-DESTRUTIVA: usa apenas comandos de leitura do esptool. Nenhum
comando de escrita/erase. A coordenacao de porta ocupada e da camada acima.

Retorno (ok, result_or_error); nunca lanca; falhas viram motivo claro.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Dict, Optional, Tuple

from ..core import logger as _logger

Result = Tuple[bool, Any]

DEFAULT_TIMEOUT = 30
PROCESS_TERM_TIMEOUT = 5
UNKNOWN = "Desconhecido"

_RE_CHIP = re.compile(r"Chip is\s+([A-Za-z0-9\-]+)", re.IGNORECASE)
_RE_CHIP_ALT = re.compile(
    r"Detecting chip type\.\.\.\s*([A-Za-z0-9\-]+)", re.IGNORECASE)
_RE_REV = re.compile(r"revision[:\s]+v?([0-9.]+)", re.IGNORECASE)
_RE_FLASH = re.compile(r"flash size[:\s]+([0-9]+\s*[KMG]B)", re.IGNORECASE)
_RE_MAC = re.compile(r"MAC[:\s]+([0-9A-Fa-f:]{17})")
_RE_FEATURES = re.compile(r"Features:\s*(.+)", re.IGNORECASE)
_RE_PSRAM = re.compile(r"PSRAM\s*([0-9]+\s*[KMG]B)", re.IGNORECASE)
_RE_USB = re.compile(r"USB mode:\s*(.+)", re.IGNORECASE)
_RE_CRYSTAL = re.compile(
    r"Crystal frequency:\s*([0-9]+\s*[KMG]?Hz)", re.IGNORECASE)
_RE_CHIP_TYPE = re.compile(r"Chip type:\s*([A-Za-z0-9\-]+)", re.IGNORECASE)
_RE_FLASH_MFR = re.compile(r"Manufacturer:\s*([0-9A-Fa-f]+)", re.IGNORECASE)
_RE_FLASH_DEV = re.compile(r"Device:\s*([0-9A-Fa-f]+)", re.IGNORECASE)


def _build_command(port: str, action: str) -> list:
    """Monta o comando esptool."""
    return ["esptool", "--port", port, action]


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """Encerra esptool e descendentes; retorna so apos termino confirmado."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=PROCESS_TERM_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    proc.wait()


def _run_command(
    cmd: list[str],
    timeout: int,
    cancel_event: Optional[threading.Event],
) -> Result:
    """Executa um comando curto com timeout e cancelamento por grupo."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "interrogacao cancelada pelo usuario")

    proc: Optional[subprocess.Popen] = None
    state = {"cancelled": False, "timed_out": False}
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        def _watch() -> None:
            deadline = time.monotonic() + timeout
            while proc is not None and proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    state["cancelled"] = True
                    _terminate_process_group(proc)
                    return
                if time.monotonic() >= deadline:
                    state["timed_out"] = True
                    _terminate_process_group(proc)
                    return
                time.sleep(0.1)

        watcher = threading.Thread(
            target=_watch,
            daemon=True,
            name="chip-info-watch",
        )
        watcher.start()
        stdout, stderr = proc.communicate()
        watcher.join(timeout=1)

        if state["cancelled"]:
            return (False, "interrogacao cancelada pelo usuario")
        if state["timed_out"]:
            return (False, "esptool excedeu o tempo limite de {}s".format(
                timeout))
        if cancel_event is not None and cancel_event.is_set():
            return (False, "interrogacao cancelada pelo usuario")
        return (True, {
            "returncode": proc.returncode,
            "stdout": stdout or "",
            "stderr": stderr or "",
        })
    except FileNotFoundError as exc:
        return (False, "comando nao encontrado: {}".format(exc.filename))
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc)
        return (False, "execucao do esptool falhou: {}".format(exc))


def _run_esptool(
    port: str,
    action: str,
    timeout: int,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """
    Tenta a sintaxe nova com hifen e depois a antiga com underscore.
    O fallback nao ocorre quando o usuario solicitou cancelamento.
    """
    base = ["esptool"] if shutil.which("esptool") else [
        "python3", "-m", "esptool"]
    action_new = action.replace("_", "-")
    action_old = action.replace("-", "_")
    actions = [action_new] if action_new == action_old else [
        action_new, action_old]

    last_reason = "esptool nao executou"
    for current_action in actions:
        if cancel_event is not None and cancel_event.is_set():
            return (False, "interrogacao cancelada pelo usuario")
        ok, result = _run_command(
            base + ["--port", port, current_action],
            timeout,
            cancel_event,
        )
        if not ok:
            if "cancelad" in str(result).lower():
                return (False, result)
            last_reason = str(result)
            continue
        if result["returncode"] == 0:
            return (True, result["stdout"] + result["stderr"])
        error = (result["stderr"] or result["stdout"]).strip()
        last_reason = "esptool falhou (codigo {}): {}".format(
            result["returncode"], error[:300])
    return (False, last_reason)


def _parse_flash_id(text: str) -> Dict[str, Any]:
    """Extrai familia, revisao, flash, features e PSRAM."""
    chip = (_RE_CHIP.search(text) or _RE_CHIP_ALT.search(text)
            or _RE_CHIP_TYPE.search(text))
    chip_type = _RE_CHIP_TYPE.search(text)
    revision = _RE_REV.search(text)
    flash = _RE_FLASH.search(text)
    features = _RE_FEATURES.search(text)
    psram = _RE_PSRAM.search(text)
    usb = _RE_USB.search(text)
    crystal = _RE_CRYSTAL.search(text)
    manufacturer = _RE_FLASH_MFR.search(text)
    device = _RE_FLASH_DEV.search(text)
    return {
        "chip_family": chip.group(1) if chip else UNKNOWN,
        "chip_type": (
            chip_type.group(1).strip()
            if chip_type else chip.group(1) if chip else UNKNOWN
        ),
        "chip_revision": revision.group(1) if revision else UNKNOWN,
        "flash_size": flash.group(1).replace(" ", "") if flash else UNKNOWN,
        "features": features.group(1).strip() if features else UNKNOWN,
        "psram": psram.group(1).replace(" ", "") if psram else "Nenhum",
        "usb_mode": usb.group(1).strip() if usb else UNKNOWN,
        "crystal": crystal.group(1).replace(" ", "") if crystal else UNKNOWN,
        "flash_manufacturer": (
            manufacturer.group(1).strip() if manufacturer else UNKNOWN),
        "flash_device": device.group(1).strip() if device else UNKNOWN,
    }


def _parse_mac(text: str) -> str:
    match = _RE_MAC.search(text)
    return match.group(1) if match else UNKNOWN


def read_chip(
    port: str,
    timeout: int = DEFAULT_TIMEOUT,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Interroga uma porta e devolve os dados normalizados do chip."""
    if not port or not isinstance(port, str):
        return (False, "porta invalida")
    if cancel_event is not None and cancel_event.is_set():
        return (False, "interrogacao cancelada pelo usuario")

    ok, flash_text = _run_esptool(
        port, "flash_id", timeout, cancel_event=cancel_event)
    if not ok:
        return (False, flash_text)
    info = _parse_flash_id(flash_text)
    info["mac"] = _parse_mac(flash_text)
    info["raw_flash_id"] = flash_text
    info["raw_mac"] = flash_text

    _logger.get_logger().info(
        "chip interrogado em %s: familia=%s flash=%s",
        port, info["chip_family"], info["flash_size"],
    )
    return (True, info)


__all__ = ["read_chip", "DEFAULT_TIMEOUT", "UNKNOWN"]

#!/usr/bin/env python3
"""
Sondagem ativa de placas: esptool chip-id + captura de boot log.

Leitura nao-destrutiva. Nunca escreve no chip; so pergunta e escuta.

Consumido por service.scan_hardware() para dispositivos ja classificados
como serial_esptool ou serial_virtual.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import time
from pathlib import Path

from .command import run_cmd
from .models import Device
from .parse import parse_chip



def probe_esptool(
    disp: Device,
    cancel_event=None,
) -> None:
    """
    Sonda o chip via `esptool chip-id`.

    Atualiza o Device em memória e respeita o evento central de
    cancelamento. Nunca escreve no chip.
    """
    if cancel_event is not None and cancel_event.is_set():
        disp.probe = {"ok": False, "motivo": "cancelado pelo usuário"}
        disp.valido = False
        return
    if not disp.porta or not Path(disp.porta).exists():
        disp.probe = {"ok": False, "motivo": "porta inexistente"}
        disp.valido = False
        return

    res = run_cmd(
        ["esptool", "-p", disp.porta, "chip-id"],
        45,
        cancel_event=cancel_event,
    )
    info = parse_chip(res.texto) if res.texto else {}
    ok = bool(res.ok and info.get("mac"))

    disp.probe = {
        "ok": ok,
        "cmd": res.cmd,
        "rc": res.rc,
        "erro": res.erro,
        "timeout": res.timeout,
        "chip": info,
        "saida": res.texto,
    }
    disp.valido = ok
    if cancel_event is not None and cancel_event.is_set():
        disp.motivo = "sondagem cancelada pelo usuário"
    else:
        disp.motivo = (
            "esptool OK; MAC lido"
            if ok else
            "falha na sondagem esptool; coleta bloqueada"
        )


def capture_boot_log(
    port: str, secs: float = 8.0, tentativas: int = 2,
) -> str:
    """
    Reseta a placa via pulso RTS e captura o boot log completo.

    Detecta marcador real de boot (rst:0x, ets, ESP-ROM:) antes de iniciar
    a contagem de 'secs', para nao perder as primeiras linhas quando o
    reset chega atrasado. Reenvia o pulso se nenhum marcador aparecer em 3s.

    Nunca lanca; falhas viram string comecando com 'ERRO:'.
    """
    marcadores = (b"rst:0x", b"ets ", b"ESP-ROM:")

    try:
        import serial
    except Exception as e:
        return f"ERRO: pyserial indisponivel: {e}\n"

    try:
        s = serial.Serial(port, 115200, timeout=0.3)
    except Exception as e:
        return f"ERRO: nao abriu {port}: {e}\n"

    try:
        dados = b""
        for _ in range(tentativas):
            s.reset_input_buffer()
            s.dtr = False
            s.rts = True
            time.sleep(0.15)
            s.rts = False
            dados = b""
            t0 = time.time()
            marco: float | None = None
            while True:
                agora = time.time()
                if marco is None and agora - t0 > 3.0:
                    break
                if marco is not None and agora - marco > secs:
                    return dados.decode("utf-8", errors="replace")
                dados += s.read(4096)
                if marco is None and any(m in dados for m in marcadores):
                    marco = time.time()
        return dados.decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERRO: {e}\n"
    finally:
        try:
            s.close()
        except Exception:
            pass

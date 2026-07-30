#!/usr/bin/env python3
"""
Fachada publica do subpacote de inspecao.

E a UNICA porta de entrada para consumidores externos (scanner.py,
TUI, futuros modulos). Reachar discovery/probe/analyze/render/etc.
direto de fora do subpacote e antipadrao: usa a fachada.

Contrato: (ok, result_or_error), nunca lanca, strings em portugues.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from typing import Any

from .analyze import analyze_report
from .discovery import discover_all_devices
from .models import Device
from .probe import probe_esptool
from .. import family_profiles as _family_profiles

Result = tuple[bool, Any]



def scan_hardware(cancel_event=None) -> Result:
    """
    Varredura leve e cancelável.

    Descobre todos os dispositivos, mas executa `esptool chip-id` somente em
    seriais classificados como `serial_esptool`. Portas virtuais e gravadores
    são resultados informativos: não recebem sondagem nem perfil.
    """
    if cancel_event is not None and cancel_event.is_set():
        return (False, "varredura cancelada pelo usuário")
    try:
        dispositivos = discover_all_devices()
    except Exception as exc:
        return (False, f"falha na descoberta: {type(exc).__name__}: {exc}")

    for device in dispositivos:
        if cancel_event is not None and cancel_event.is_set():
            return (False, "varredura cancelada pelo usuário")
        if device.classe == "serial_esptool" and device.exibir:
            try:
                probe_esptool(device, cancel_event=cancel_event)
            except Exception as exc:
                device.probe = {
                    "ok": False,
                    "motivo": f"exceção: {exc}",
                }
                device.valido = False

    if cancel_event is not None and cancel_event.is_set():
        return (False, "varredura cancelada pelo usuário")
    return (True, dispositivos)


def derive_state(device: Device) -> str:
    """Deriva o estado sem tratar dispositivo informativo como erro."""
    if device.classe in {"gravador", "serial_virtual"}:
        return "informativo"
    if device.classe != "serial_esptool":
        return "ignorado"
    if not device.probe:
        return "detectado"
    return "validado" if device.probe.get("ok") else "erro"


def build_report(
    device: Device,
    raw_outputs: dict[str, str],
    perfil: dict[str, Any] | None = None,
    perfil_novo: bool = False,
) -> Result:
    """
    Consolida uma sondagem ja feita em relatorio estruturado.

    Nao coleta: espera receber raw_outputs pronto (chaves 'chip',
    'flash', 'seg', 'efuse', 'part', 'boot'). Quem coleta e o
    consumidor (scan_command para CLI, futura funcao para TUI).

    Retorna (True, dict_do_relatorio) ou (False, motivo).
    """
    if not isinstance(raw_outputs, dict):
        return (False, "raw_outputs deve ser dict")
    if not device.probe.get("ok"):
        return (False, "device nao esta em estado validado; "
                       "sondagem falhou ou nao foi feita")
    try:
        relatorio = analyze_report(
            raw_outputs, device, perfil=perfil, perfil_novo=perfil_novo,
        )
    except Exception as e:
        return (False, f"falha na analise: {type(e).__name__}: {e}")
    return (True, relatorio)


def _read_partition_table(port: str) -> str:
    """
    Le e parseia a tabela de particoes em 0x8000 usando arquivo
    temporario (nao grava em disco permanente). Retorna texto ja
    parseado ou mensagem de motivo se falhar.
    """
    import os
    import sys
    import tempfile
    from pathlib import Path

    from .command import run_cmd

    idf = Path(os.environ.get(
        "IDF_PATH", str(Path.home() / "esp" / "esp-idf")))
    gen = idf / "components" / "partition_table" / "gen_esp32part.py"

    with tempfile.TemporaryDirectory() as tmp:
        ptable = Path(tmp) / "ptable.bin"
        run_cmd(
            ["esptool", "-p", port, "read-flash",
             "0x8000", "0xC00", str(ptable)], 90,
        )
        if not ptable.exists():
            return "Falha ao ler flash em 0x8000"
        if not gen.exists():
            return f"Tabela lida, mas gen_esp32part.py nao esta em {gen}"
        res2 = run_cmd([sys.executable, str(gen), str(ptable)], 30)
        out = res2.texto or res2.erro
        uteis = [
            l for l in out.splitlines()
            if l.startswith("#") or ("," in l and "Parsing" not in l)
        ]
        return "\n".join(uteis) if uteis else "Tabela invalida em 0x8000"


def collect_full(device: Device) -> Result:
    """
    Coleta completa de um dispositivo ja sondado com chip-id OK:
    flash-id, seguranca, efuse, particoes e boot log. Monta o relatorio
    estruturado via analyze_report e persiste snapshot bruto por MAC.

    Mais lento que scan_hardware (espefuse pode levar ate ~2min por
    porta). Uso previsto: Hardware > Buscar placas, onde riqueza de
    dado importa mais que velocidade.

    Retorna (True, relatorio) ou (False, motivo).
    """
    from .command import run_cmd
    from .probe import capture_boot_log
    from .snapshot_store import save_snapshot

    if not device.porta or not device.probe.get("ok"):
        return (False, "dispositivo sem sondagem valida (chip-id)")

    port = device.porta
    raw: dict[str, str] = {"chip": device.probe.get("saida", "")}

    for nome, cmd, timeout in (
        ("flash", ["esptool", "-p", port, "flash-id"], 60),
        ("seg",   ["esptool", "-p", port, "get-security-info"], 60),
        ("efuse", ["espefuse", "-p", port, "summary"], 120),
    ):
        res = run_cmd(cmd, timeout)
        raw[nome] = res.texto or res.erro

    raw["part"] = _read_partition_table(port)
    raw["boot"] = capture_boot_log(port)

    try:
        relatorio = analyze_report(raw, device)
    except Exception as e:
        return (False, f"falha na analise: {type(e).__name__}: {e}")

    mac = relatorio["identidade"].get("mac", "")
    if mac and mac != "Desconhecido":
        ok_snap, res_snap = save_snapshot(mac, raw, relatorio)
        if not ok_snap:
            relatorio.setdefault("alertas", []).append(
                f"snapshot nao gravado: {res_snap}")

    return (True, relatorio)


def relatorio_to_chip_info(relatorio: dict[str, Any]) -> dict[str, Any]:
    """
    Converte o relatorio (chaves em portugues, aninhado) para o dict
    plano em ingles que boards_db/chip_divergence ja esperam - sem
    alterar esses modulos.

    Normaliza o sentinela de PSRAM ausente: "NAO detectada" vira
    "Desconhecido", para casar com o conjunto de valores que
    chip_divergence ja ignora na comparacao (evita falso positivo de
    divergencia em toda placa sem PSRAM).
    """
    ident = relatorio.get("identidade", {})
    cpu = relatorio.get("cpu", {})
    flash = relatorio.get("flash", {})
    psram = relatorio.get("psram", {})

    psram_cap = psram.get("capacidade", "Desconhecido")
    if psram_cap.strip().upper() == "NAO DETECTADA":
        psram_cap = "Desconhecido"

    return {
        "chip_type": ident.get("chip", "Desconhecido"),
        "chip_family": ident.get("chip", "Desconhecido"),
        "chip_revision": ident.get("revisao", "Desconhecido"),
        "flash_size": flash.get("fisica", "Desconhecido"),
        "psram": psram_cap,
        "features": cpu.get("features_raw", "Desconhecido"),
        "usb_mode": ident.get("usb", "Desconhecido"),
        "crystal": cpu.get("cristal", "Desconhecido"),
        "flash_manufacturer": flash.get("fabricante", "Desconhecido"),
        "flash_device": flash.get("device_id", "Desconhecido"),
        "mac": ident.get("mac", "Desconhecido"),
    }

def device_to_chip_info(device: Device) -> dict[str, Any]:
    """Converte o resultado leve de chip-id para o contrato do banco."""
    chip = device.probe.get("chip", {}) if device.probe else {}
    family = _family_profiles.normalize_family(
        chip.get("chip_base") or chip.get("modelo") or "Desconhecido"
    )
    return {
        "chip_type": chip.get("modelo") or family,
        "chip_family": family,
        "chip_revision": chip.get("revisao") or "Desconhecido",
        "flash_size": "Desconhecido",
        "psram": "Nenhum",
        "features": chip.get("features_raw") or "Desconhecido",
        "usb_mode": chip.get("usb_mode") or "Desconhecido",
        "crystal": chip.get("cristal") or "Desconhecido",
        "flash_manufacturer": "Desconhecido",
        "flash_device": "Desconhecido",
        "mac": str(chip.get("mac") or "").lower(),
    }


def list_display_ports() -> Result:
    """
    Lista de portas ja tratada, SEM sondar o chip.

    Usa discover_all_devices() (descoberta + classificacao, sem esptool),
    fresco a cada chamada. Devolve so dispositivos com `porta` e
    `exibir=True` — exclui ttyS fantasmas (exibir=False) e gravadores
    (sem porta serial). Nao reseta a placa: o probe (chip-id) pulsa
    DTR/RTS; esta funcao nao sonda.

    Uso previsto: menu do Monitor, que precisa de porta + classe e nao
    deve tocar o chip. Identidade (MAC) e do fluxo de Hardware, nao daqui.

    Retorna (True, list[Device]) ou (False, motivo).
    """
    try:
        dispositivos = discover_all_devices()
    except Exception as exc:
        return (False, f"falha na descoberta: {type(exc).__name__}: {exc}")
    portas = [d for d in dispositivos if d.porta and d.exibir]
    return (True, portas)


__all__ = [
    "list_display_ports", "scan_hardware", "derive_state", "build_report", "collect_full",
    "relatorio_to_chip_info", "device_to_chip_info",
]

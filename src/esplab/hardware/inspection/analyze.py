#!/usr/bin/env python3
"""
Analise consolidada de uma sondagem completa.

Consome:
  - textos brutos coletados (chip, flash, seg, efuse, part, boot)
  - Device com Device.probe preenchido pelo probe.py
  - perfil retornado pelo boards_db (opcional)

Produz o dicionario grande de relatorio, com secoes: identidade, cpu,
conectividade, boot, flash, psram, ram, seguranca, particoes, perfil,
alertas.

Funcao pura de orquestracao: nao le arquivo, nao chama subprocess,
nao toca hardware. Cada campo agregado do scan.py vira campo proprio,
sem strings compostas.

Consumido por service.scan_hardware() e por render.py.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from typing import Any

from .constants import FABRICANTES_FLASH
from .models import Device
from .parse import (
    fallback_ram, parse_chip, parse_particoes,
    parse_ram_regions, pega,
)


def _normalize_mhz(valor_hz: str) -> str:
    """Converte string em Hz para 'NMHz'. Devolve 'Desconhecido' se falhar."""
    try:
        hz = int(valor_hz)
        if hz % 1_000_000 == 0:
            return f"{hz // 1_000_000}MHz"
        return f"{hz / 1_000_000:.1f}MHz"
    except Exception:
        return "Desconhecido"


def _status_seg(texto: str, rotulo: str) -> str:
    """Interpreta linha 'Rotulo: valor' do get-security-info."""
    if not (texto or "").strip():
        return "Desconhecido"
    low = texto.lower()
    if "not supported" in low or "unsupported" in low:
        return "nao disponivel"
    m = re.search(
        rf"{re.escape(rotulo)}\s*:\s*([A-Za-z0-9_./ -]+)", texto, re.I,
    )
    if not m:
        return "Desconhecido"
    v = m.group(1).strip()
    mapa = {"enabled": "Enabled", "disabled": "Disabled",
            "enable": "Enabled", "disable": "Disabled"}
    return mapa.get(v.lower(), v)


def _secao_identidade(
    chip: dict[str, Any], boot: str, disp: Device,
    perfil: dict[str, Any] | None, perfil_novo: bool,
) -> dict[str, Any]:
    """Monta a secao 'identidade' do relatorio."""
    mac = chip.get("mac") or ""
    return {
        "modelo": chip.get("modelo") or "Desconhecido",
        "chip": chip.get("chip_base") or "Desconhecido",
        "revisao": chip.get("revisao") or "Desconhecido",
        "mac": mac or "Desconhecido",
        "perfil_chave": f"mac:{mac}" if mac else "sem perfil",
        "perfil_status": "novo" if perfil_novo else "encontrado",
        "porta_usada": disp.porta,
        "adaptador": disp.nome,
        "vid_pid": f"{disp.vid or '?'}:{disp.pid or '?'}",
        "usb": chip.get("usb_mode") or "Desconhecido",
        "rom": pega(
            r"ESP-ROM:(\S+)", boot,
            pega(r"ets (\w{3} \d{1,2} \d{4} \d{2}:\d{2}:\d{2})", boot),
        ),
    }


def _secao_cpu(
    chip: dict[str, Any], boot: str, alertas: list[str],
) -> dict[str, Any]:
    """Monta a secao 'cpu' do relatorio."""
    features = chip.get("features") or {}
    clock_runtime = _normalize_mhz(
        pega(r"cpu freq:\s*(\d+)\s*Hz", boot, ""),
    )
    if clock_runtime == "Desconhecido":
        alertas.append("clock runtime nao encontrado no boot log")
    return {
        "nucleos": ", ".join(features.get("nucleos") or []) or "Desconhecido",
        "clock_max": features.get("clock_max") or "Desconhecido",
        "clock_runtime": clock_runtime,
        "cristal": chip.get("cristal") or "Desconhecido",
        "features_raw": chip.get("features_raw") or "",
    }


def _secao_boot(boot: str) -> dict[str, Any]:
    """Monta a secao 'boot' do relatorio."""
    return {
        "reset": pega(r"rst:\S+ \(([^)]+)\)", boot),
        "modo": pega(r"boot:\S+ \(([^)]+)\)", boot),
        "spi_speed": pega(r"Boot SPI Speed\s*:\s*(\S+)", boot, ""),
        "spi_mode": pega(r"SPI Mode\s*:\s*(\S+)", boot,
                         pega(r"mode:(\w+),", boot, "")),
        "app": pega(r"Project name:\s*(.+)", boot, ""),
        "app_version": pega(r"App version:\s*(.+)", boot, ""),
        "idf": pega(r"ESP-IDF:\s*(.+)", boot,
                    pega(r"boot: ESP-IDF\s+(.+?)\s+2nd", boot, "")),
    }


def _secao_flash(
    flash: str, boot: str, alertas: list[str],
) -> dict[str, Any]:
    """Monta a secao 'flash' do relatorio."""
    fab = pega(r"Manufacturer:\s*(\w+)", flash, "")
    try:
        fab_nome = FABRICANTES_FLASH.get(int(fab, 16), "desconhecido")
    except Exception:
        fab_nome = "desconhecido"

    f_warn = ""
    if "larger than the size in the binary image header" in boot:
        f_warn = "flash fisica maior que o tamanho configurado no firmware"
        alertas.append(f_warn)

    return {
        "fisica": pega(r"Detected flash size:\s*(\S+)", flash),
        "firmware_header": pega(r"SPI Flash Size\s*:\s*(\S+)", boot,
                                 "Desconhecido"),
        "fabricante": (f"{fab_nome} (0x{fab})" if fab
                        else "Desconhecido"),
        "device_id": "0x" + pega(r"Device:\s*(\w+)", flash, "????"),
        "tipo_efuse": pega(r"Flash type set in eFuse:\s*(.+)", flash, ""),
        "voltagem": pega(r"Flash voltage set by eFuse:\s*(.+)", flash, ""),
        "driver_idf": pega(r"detected chip:\s*(\w+)", boot, ""),
        "alerta": f_warn,
    }


def _secao_psram(
    chip: dict[str, Any], boot: str, efuse: str,
) -> dict[str, Any]:
    """Monta a secao 'psram': runtime tem prioridade, encapsulamento fallback."""
    features = chip.get("features") or {}
    p_cap_ef = pega(r"PSRAM_CAP\s*\(.*?\).*?=\s*(\S+)", efuse, "", re.S)
    p_vendor_ef = pega(r"PSRAM_VENDOR\s*\(.*?\).*?=\s*(\S+)", efuse, "",
                        re.S)
    p_boot = pega(r"Found\s+(\d+\s*MB)\s+PSRAM", boot, "")
    return {
        "capacidade": (p_boot or features.get("psram_embutida")
                        or p_cap_ef or "NAO detectada"),
        "vendor": (features.get("psram_vendor") or p_vendor_ef
                    or "Desconhecido"),
        "runtime": ("inicializada no boot" if p_boot
                     else "nao inicializada/logada pelo firmware atual"),
        "velocidade": pega(r"esp_psram: Speed:\s*(\S+)", boot,
                            "Desconhecido"),
        "fonte": "boot log" if p_boot else "Features/eFuse",
        "efuse": (f"PSRAM_CAP={p_cap_ef or '?'} "
                   f"PSRAM_VENDOR={p_vendor_ef or '?'}"),
    }


def _secao_ram(
    chip: dict[str, Any], boot: str, alertas: list[str],
) -> tuple[list[dict[str, str]], str, bool]:
    """Extrai RAM do boot ou usa fallback por familia."""
    ram = parse_ram_regions(boot)
    if ram:
        return ram, "boot log ao vivo (heap_init)", False
    nome_chip = chip.get("chip_base") or chip.get("modelo") or ""
    ram, fonte, padrao = fallback_ram(nome_chip)
    alertas.append(
        "heap_init ausente; secao RAM preenchida por fallback/placeholder"
    )
    return ram, fonte, padrao


def _secao_seguranca(
    efuse: str, seg: str, alertas: list[str],
) -> dict[str, Any]:
    """Monta a secao 'seguranca' do relatorio."""
    def fuse_disabled(nome: str) -> str:
        v = pega(nome + r".*?=\s*(True|False)", efuse, "?", re.S)
        if v == "True":
            return "DESABILITADO"
        if v == "False":
            return "habilitado"
        return "Desconhecido"

    secure_boot = _status_seg(seg, "Secure Boot")
    flash_enc = _status_seg(seg, "Flash Encryption")
    if secure_boot == "Desconhecido" or flash_enc == "Desconhecido":
        alertas.append(
            "seguranca nao interpretada completamente; "
            "consultar seg.txt/efuse.txt"
        )
    return {
        "secure_boot": secure_boot,
        "flash_encryption": flash_enc,
        "jtag_pad": fuse_disabled("DIS_PAD_JTAG"),
        "jtag_usb": fuse_disabled("DIS_USB_JTAG"),
        "download_mode": fuse_disabled("DIS_DOWNLOAD_MODE"),
        "usb_serial_jtag": fuse_disabled("DIS_USB_SERIAL_JTAG"),
    }


def analyze_report(
    raw_outputs: dict[str, str],
    disp: Device,
    perfil: dict[str, Any] | None = None,
    perfil_novo: bool = False,
) -> dict[str, Any]:
    """
    Consolida uma sondagem completa em dicionario estruturado.

    raw_outputs : dict com chaves 'chip', 'flash', 'seg', 'efuse',
                  'part', 'boot' (strings de saida bruta dos comandos).
    disp        : Device ja sondado (disp.probe preenchido).
    perfil      : dict do boards_db.find_or_create_by_mac, se disponivel.
    perfil_novo : True se o perfil foi criado agora nesta sessao.

    Nunca lanca. Campos faltantes viram 'Desconhecido'; problemas viram
    entradas na lista 'alertas'.
    """
    chip = parse_chip(raw_outputs.get("chip", ""))
    boot = raw_outputs.get("boot", "")
    flash = raw_outputs.get("flash", "")
    efuse = raw_outputs.get("efuse", "")
    seg = raw_outputs.get("seg", "")

    alertas: list[str] = []
    ram, ram_fonte, ram_padrao = _secao_ram(chip, boot, alertas)

    return {
        "identidade": _secao_identidade(
            chip, boot, disp, perfil, perfil_novo),
        "cpu": _secao_cpu(chip, boot, alertas),
        "conectividade": {
            "itens": ", ".join(
                (chip.get("features") or {}).get("conectividade") or []
            ) or "Desconhecido",
        },
        "boot": _secao_boot(boot),
        "flash": _secao_flash(flash, boot, alertas),
        "psram": _secao_psram(chip, boot, efuse),
        "ram": ram,
        "ram_fonte": ram_fonte,
        "ram_padrao": ram_padrao,
        "seguranca": _secao_seguranca(efuse, seg, alertas),
        "particoes": parse_particoes(raw_outputs.get("part", "")),
        "perfil": perfil or {},
        "alertas": alertas,
    }

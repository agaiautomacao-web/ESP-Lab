#!/usr/bin/env python3
"""
Parsers puros de saida do esptool/espefuse/boot log.

Funcao pura sobre strings. Nao le arquivo, nao chama subprocess, nao toca
hardware. Testavel isoladamente com fixtures de texto.

Consumido por analyze.py.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from typing import Any


def pega(rx: str, texto: str, padrao: str = "Desconhecido",
         flags: int = 0) -> str:
    """Busca 1o grupo do regex; devolve padrao se nao casar."""
    m = re.search(rx, texto or "", flags)
    return m.group(1).strip() if m else padrao


def parse_kv_udev(texto: str) -> dict[str, str]:
    """Converte saida 'chave=valor' do udevadm em dict."""
    d: dict[str, str] = {}
    for linha in (texto or "").splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def parse_features(features: str) -> dict[str, Any]:
    """
    Separa a linha 'Features:' do esptool em campos individuais.

    Entrada: "Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz,
              Embedded PSRAM 8MB (AP_3v3)"
    Saida  : dict com conectividade, nucleos, clock_max,
             memoria_embutida, psram_embutida, psram_vendor, extras.
    """
    itens = [x.strip() for x in (features or "").split(",") if x.strip()]
    out: dict[str, Any] = {
        "raw": features or "",
        "conectividade": [], "nucleos": [], "clock_max": "",
        "memoria_embutida": [], "psram_embutida": "",
        "psram_vendor": "", "extras": [],
    }
    for item in itens:
        low = item.lower()
        if (low.startswith(("wi-fi", "wifi", "bt"))
                or "bluetooth" in low):
            out["conectividade"].append(item)
        elif "core" in low:
            out["nucleos"].append(item)
        elif re.search(r"\b\d+\s*mhz\b", low):
            out["clock_max"] = item.replace(" ", "")
        elif "psram" in low or "embedded" in low or "flash" in low:
            mem = item.replace("Embedded ", "").strip()
            out["memoria_embutida"].append(mem)
            m = re.search(r"PSRAM\s+(\d+\s*MB)\s*\(([^)]+)\)",
                          item, re.I)
            if m:
                out["psram_embutida"] = m.group(1).replace(" ", "")
                out["psram_vendor"] = m.group(2).strip()
        else:
            out["extras"].append(item)
    return out


def parse_chip(texto: str) -> dict[str, Any]:
    """Extrai dados do 'esptool chip-id': modelo, MAC, features, etc."""
    chip_linha = pega(r"Chip type:\s+(.+)", texto, "")
    chip_base, revisao = chip_linha, ""
    m = re.match(r"(.+?)\s*\(revision\s+([^)]*)\)", chip_linha)
    if m:
        chip_base, revisao = m.group(1).strip(), m.group(2).strip()
    features_raw = pega(r"Features:\s+(.+)", texto, "")
    return {
        "modelo": chip_linha or "Desconhecido",
        "chip_base": chip_base or "Desconhecido",
        "revisao": revisao or pega(r"revision\s+([^)]*)", chip_linha, ""),
        "features_raw": features_raw,
        "features": parse_features(features_raw),
        "cristal": pega(r"Crystal frequency:\s+(.+)", texto),
        "usb_mode": pega(r"USB mode:\s+(.+)", texto),
        "mac": pega(r"MAC:\s+([0-9a-fA-F:]{17})", texto, "").lower(),
    }


def parse_particoes(texto: str) -> list[dict[str, str]]:
    """Converte tabela de particoes textual em lista de dicts."""
    parts: list[dict[str, str]] = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "," not in linha:
            continue
        campos = [c.strip() for c in linha.split(",")]
        if len(campos) >= 5:
            parts.append({
                "nome": campos[0], "tipo": campos[1],
                "subtipo": campos[2], "offset": campos[3],
                "tamanho": campos[4],
                "flags": campos[5] if len(campos) > 5 else "",
            })
    return parts


def parse_ram_regions(boot_log: str) -> list[dict[str, str]]:
    """Extrai regioes de heap_init do boot log; lista vazia se ausente."""
    achados = re.findall(
        r"heap_init: At \S+ len \S+ \(([^)]+)\):\s*(\S+)",
        boot_log or "",
    )
    return [{"tamanho": tam, "tipo": tipo} for tam, tipo in achados]


def eh_esp32_classico(chip_nome: str) -> bool:
    """True se e ESP32 classico (D0WD, WROOM, WROVER, PICO). Exclui S/C/H/P."""
    n = (chip_nome or "").upper()
    if not n.startswith("ESP32"):
        return False
    return re.search(
        r"ESP32-(S2|S3|C2|C3|C5|C6|C61|H2|H21|P4)\b", n,
    ) is None


def fallback_ram(chip_nome: str) -> tuple[list[dict[str, str]], str, bool]:
    """
    Fallback quando heap_init nao veio no boot log.
    Retorna (regioes, fonte, padrao_usado).
    ESP32 classico -> valores fixos de arquitetura.
    Outros         -> placeholder honesto, nunca deixa a secao vazia.
    """
    if eh_esp32_classico(chip_nome):
        return ([
            {"tipo": "SRAM interna total", "tamanho": "520 KB"},
            {"tipo": "DRAM total",         "tamanho": "320 KB"},
            {"tipo": "IRAM total",         "tamanho": "200 KB"},
            {"tipo": "SRAM RTC",           "tamanho": "16 KB"},
        ], "fallback de arquitetura para ESP32 classico; heap_init ausente",
            True)
    nome = chip_nome or "chip desconhecido"
    return ([
        {"tipo": "RAM",      "tamanho": "nao informada pelo boot log"},
        {"tipo": "Fallback", "tamanho": f"sem cadastro fixo para {nome}"},
    ], "placeholder; heap_init ausente e sem fallback fixo cadastrado",
        True)

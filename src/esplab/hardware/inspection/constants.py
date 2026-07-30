#!/usr/bin/env python3
"""
Constantes do subpacote de inspecao de hardware.

Tabelas puras de VID:PID e afins. Sem dependencia interna, sem I/O.
Consumido por classify.py, discovery.py e parse.py.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re

# Regex reutilizado por render/parse para limpar codigos ANSI de terminal.
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Porta serial virtual permitida para sondagem (fora do padrao ttyUSB/ttyACM).
VIRTUAL_PERMITIDA = "/dev/ttyS4"

# Fabricantes de chip de flash SPI, identificados pelo primeiro byte do JEDEC ID.
FABRICANTES_FLASH: dict[int, str] = {
    0x68: "Boya",
    0xEF: "Winbond",
    0xC8: "GigaDevice",
    0xC2: "Macronix",
    0x20: "XMC",
    0x9D: "ISSI",
}

# Pontes USB-serial compativeis com esptool (falam protocolo de boot ROM).
# Formato: nome -> (vid, set_de_pids_ou_None_para_qualquer_pid_do_vid).
BRIDGES_SERIAL: dict[str, tuple[str, set[str] | None]] = {
    "Espressif nativo": ("303a", {"1001"}),
    "CP210x":           ("10c4", {"ea60"}),
    "CH340":            ("1a86", {"7523"}),
    "CH9102":           ("1a86", {"55d3"}),
    "FTDI":             ("0403", None),
    "PL2303":           ("067b", None),
}

# Gravadores JTAG/SWD/ICSP - nao falam protocolo esptool, so inventariados.
# Formato: nome -> (vid, set_de_pids_ou_None, protocolo).
GRAVADORES: dict[str, tuple[str, set[str] | None, str]] = {
    "ST-Link": (
        "0483",
        {"3748", "374b", "374d", "374e", "374f",
         "3752", "3753", "3754"},
        "jtag/swd",
    ),
    "J-Link":             ("1366", None,               "jtag/swd"),
    "Olimex ARM-USB-OCD": ("15ba", {"0003"},           "jtag"),
    "USBasp":             ("16c0", {"05dc"},           "icsp/avrdude"),
    "USBtinyISP":         ("1781", {"0c9f"},           "icsp/avrdude"),
    "AVRISP mkII":        ("03eb", {"2104"},           "icsp/avrdude"),
    "Black Magic Probe":  ("1d50", {"6017", "6018"},   "jtag/swd"),
}

# Serial USB gravado de fabrica que colide em multiplas unidades - nao serve
# como identificador unico, forca fallback para caminho fisico.
SERIALS_GENERICOS_CONHECIDOS: set[str] = {
    "0001",  # default de fabrica do CP2102 classico (Silicon Labs)
}

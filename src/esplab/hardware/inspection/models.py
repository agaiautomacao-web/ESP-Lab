#!/usr/bin/env python3
"""
Modelos de dados do subpacote de inspecao.

Dataclasses puras, sem logica. Servem como contrato entre modulos:
command.py produz ExecResult; discovery.py produz Device; analyze.py
produz InspectionResult.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import ANSI_RE


@dataclass
class ExecResult:
    """Resultado de execucao de subprocess (esptool, espefuse, etc)."""

    cmd: list[str]
    ok: bool
    rc: int | None
    stdout: str = ""
    stderr: str = ""
    erro: str = ""
    timeout: bool = False

    @property
    def texto(self) -> str:
        """Saida combinada, sem codigos ANSI, sem \\r, com \\n final."""
        raw = (self.stdout or "") + (self.stderr or "")
        limpo = ANSI_RE.sub("", raw).replace("\r", "").strip()
        return limpo + ("\n" if limpo else "")


@dataclass
class Device:
    """Dispositivo detectado na descoberta (serial ou USB bruto)."""

    origem: str          # "pyserial/udev" ou "lsusb/udev"
    classe: str          # "serial_esptool"|"serial_virtual"|"gravador"|"desconhecido"
    valido: bool
    exibir: bool
    motivo: str

    porta: str | None = None
    local_usb: str | None = None

    nome: str | None = None
    protocolo: str | None = None

    vid: str | None = None
    pid: str | None = None
    serial_usb: str | None = None

    fabricante: str | None = None
    produto: str | None = None
    descricao: str | None = None
    interface: str | None = None
    hwid: str | None = None
    id_path: str | None = None
    driver: str | None = None

    pyserial: dict[str, Any] = field(default_factory=dict)
    udev: dict[str, Any] = field(default_factory=dict)
    usb: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)

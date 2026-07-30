#!/usr/bin/env python3
"""
Subpacote de inspecao de hardware do ESP Lab.

Porta de entrada: apenas `service`. Consumidores externos importam
daqui, nao dos modulos internos.

Ex.:
    from esplab.hardware.inspection import service
    ok, dispositivos = service.scan_hardware()

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from . import service
from .models import Device, ExecResult

__all__ = ["service", "Device", "ExecResult"]

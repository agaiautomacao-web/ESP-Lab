#!/usr/bin/env python3
"""
Classificacao de dispositivos por VID:PID.

Funcao pura sobre as tabelas de constants.py. Nao toca hardware, nao le
arquivo, nao chama subprocess. So decide: dado (vid, pid), que tipo de
dispositivo e?

Consumido por discovery.py e service.py.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from .constants import BRIDGES_SERIAL, GRAVADORES, VIRTUAL_PERMITIDA


def _match_serial(vid: str | None, pid: str | None) -> str | None:
    """Retorna o nome do bridge serial se casar, senao None."""
    vid = (vid or "").lower()
    pid = (pid or "").lower()
    for nome, (v, pids) in BRIDGES_SERIAL.items():
        if vid == v and (pids is None or pid in pids):
            return nome
    return None


def _match_programmer(
    vid: str | None, pid: str | None,
) -> tuple[str | None, str | None]:
    """Retorna (nome, protocolo) do gravador se casar, senao (None, None)."""
    vid = (vid or "").lower()
    pid = (pid or "").lower()
    for nome, (v, pids, protocolo) in GRAVADORES.items():
        if vid == v and (pids is None or pid in pids):
            return nome, protocolo
    return None, None


def classify_device(
    vid: str | None,
    pid: str | None,
    porta: str | None = None,
) -> tuple[str, str | None, str | None, bool, str]:
    """
    Classifica um dispositivo pelo VID:PID e (opcionalmente) porta.

    Retorna (classe, nome, protocolo, exibir, motivo) onde:
      classe   : "serial_esptool"|"serial_virtual"|"gravador"|"desconhecido"
      nome     : nome amigavel (CP210x, USBasp, ...) ou None
      protocolo: so para gravadores ("jtag/swd", "icsp/avrdude", ...) ou None
      exibir   : se o painel deve mostrar por padrao
      motivo   : frase curta explicando a classificacao
    """
    nome = _match_serial(vid, pid)
    if nome:
        return (
            "serial_esptool", nome, None, True,
            "serial USB compativel com esptool",
        )

    nome, protocolo = _match_programmer(vid, pid)
    if nome:
        return (
            "gravador", nome, protocolo, True,
            f"gravador reconhecido ({protocolo}); nao fala esptool",
        )

    if porta == VIRTUAL_PERMITIDA:
        return (
            "serial_virtual", "Serial virtual permitida", None, True,
            "porta virtual permitida para sondagem",
        )

    return (
        "desconhecido", None, None, False,
        "fora do escopo do painel",
    )

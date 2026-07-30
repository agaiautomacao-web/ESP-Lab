#!/usr/bin/env python3
"""
Descoberta de dispositivos: portas seriais + USB brutos.

Duas passadas coordenadas:
1. Portas seriais (pyserial + udevadm): tudo em /dev/ttyACM*, /dev/ttyUSB*
   e a porta virtual permitida.
2. Barramento USB (lsusb + udevadm): gravadores JTAG/ICSP que nao criam
   porta serial (USBasp, ST-Link puro, etc). Deduplica contra a primeira.

Consumido por service.scan_hardware().

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

from .command import run_cmd
from .classify import _match_programmer, classify_device
from .constants import VIRTUAL_PERMITIDA
from .models import Device
from .parse import parse_kv_udev


def _propriedades_udev(no: str) -> dict[str, str]:
    """Le propriedades de um node via udevadm; nao lanca."""
    res = run_cmd(["udevadm", "info", "-q", "property", "-n", no], 10)
    if not res.ok:
        return {"_erro": res.erro or res.texto.strip(),
                "_rc": str(res.rc)}
    return parse_kv_udev(res.texto)


def _coletar_portas_brutas() -> list[Any]:
    """
    Coleta portas do pyserial e complementa com glob de /dev/ttyACM*,
    /dev/ttyUSB* e VIRTUAL_PERMITIDA que o pyserial pode nao ter listado.
    Devolve lista de objetos com atributos compativeis com ListPortInfo.
    """
    portas = list(list_ports.comports()) if list_ports is not None else []
    existentes = {getattr(p, "device", "") for p in portas
                  if getattr(p, "device", "")}
    for caminho in sorted(
        glob.glob("/dev/ttyACM*")
        + glob.glob("/dev/ttyUSB*")
        + glob.glob(VIRTUAL_PERMITIDA)
    ):
        if caminho in existentes:
            continue
        class _PortaSintetica:
            device = caminho
            name = Path(caminho).name
            description = "n/a"
            hwid = "n/a"
            vid = None
            pid = None
            manufacturer = None
            product = None
            serial_number = None
            interface = None
            location = None
        portas.append(_PortaSintetica())
    return portas


def _construir_device_serial(p: Any) -> Device | None:
    """Constroi Device a partir de um objeto de porta serial."""
    porta = getattr(p, "device", "") or ""
    if not porta:
        return None

    existe = Path(porta).exists()
    permitido = (porta.startswith(("/dev/ttyACM", "/dev/ttyUSB"))
                 or porta == VIRTUAL_PERMITIDA)
    udev = _propriedades_udev(porta) if existe else {
        "_erro": "porta inexistente"}

    vid = (f"{getattr(p, 'vid', None):04x}"
           if getattr(p, "vid", None) is not None
           else udev.get("ID_VENDOR_ID"))
    pid = (f"{getattr(p, 'pid', None):04x}"
           if getattr(p, "pid", None) is not None
           else udev.get("ID_MODEL_ID"))

    classe, nome, protocolo, exibir_cls, motivo = classify_device(
        vid, pid, porta)
    valido = bool(existe and permitido
                  and classe in {"serial_esptool", "serial_virtual"})
    exibir = bool(existe and permitido and exibir_cls)
    if not existe:
        motivo = "porta informada nao existe"

    pyserial_dict = {
        "device": porta,
        "name": getattr(p, "name", None),
        "description": getattr(p, "description", None),
        "hwid": getattr(p, "hwid", None),
        "vid": vid, "pid": pid,
        "manufacturer": getattr(p, "manufacturer", None),
        "product": getattr(p, "product", None),
        "serial_number": getattr(p, "serial_number", None),
        "interface": getattr(p, "interface", None),
        "location": getattr(p, "location", None),
    }

    return Device(
        origem="pyserial/udev", classe=classe, valido=valido,
        exibir=exibir, motivo=motivo, porta=porta,
        nome=nome, protocolo=protocolo,
        vid=(vid or "").lower() or None,
        pid=(pid or "").lower() or None,
        serial_usb=(getattr(p, "serial_number", None)
                    or udev.get("ID_SERIAL_SHORT")),
        fabricante=(getattr(p, "manufacturer", None)
                    or udev.get("ID_VENDOR_FROM_DATABASE")
                    or udev.get("ID_VENDOR")),
        produto=(getattr(p, "product", None)
                 or udev.get("ID_MODEL_FROM_DATABASE")
                 or udev.get("ID_MODEL")),
        descricao=getattr(p, "description", None),
        interface=getattr(p, "interface", None),
        hwid=getattr(p, "hwid", None),
        id_path=udev.get("ID_PATH"),
        pyserial=pyserial_dict, udev=udev,
    )


def discover_serial_devices() -> list[Device]:
    """
    Varredura de portas seriais. Nunca lanca.
    Se pyserial estiver ausente, ainda cobre pelo glob de /dev.
    """
    portas = _coletar_portas_brutas()
    dispositivos: list[Device] = []
    for p in sorted(portas, key=lambda x: getattr(x, "device", "") or ""):
        d = _construir_device_serial(p)
        if d is not None:
            dispositivos.append(d)
    return dispositivos


def _listar_lsusb() -> list[dict[str, str]]:
    """Parseia saida do lsusb em lista de dicts. Nunca lanca."""
    res = run_cmd(["lsusb"], 10)
    out: list[dict[str, str]] = []
    for linha in res.texto.splitlines():
        m = re.match(
            r"Bus (\d+) Device (\d+): ID (\w{4}):(\w{4})\s*(.*)",
            linha,
        )
        if not m:
            continue
        bus, dev, vid, pid, desc = m.groups()
        out.append({
            "bus": bus, "dev": dev,
            "vid": vid.lower(), "pid": pid.lower(),
            "desc": desc.strip(),
        })
    return out


def discover_usb_programmers(
    ja_detectados: list[Device],
) -> list[Device]:
    """
    Segunda passada: gravadores no barramento USB que nao criaram
    porta serial. Deduplica contra ja_detectados por (vid, pid, serial).
    """
    ids_ja_vistos = {(d.vid, d.pid, d.serial_usb)
                     for d in ja_detectados if d.vid and d.pid}
    dispositivos: list[Device] = []
    for item in _listar_lsusb():
        vid, pid = item["vid"], item["pid"]
        nome, protocolo = _match_programmer(vid, pid)
        if not nome:
            continue
        node = f"/dev/bus/usb/{item['bus']}/{item['dev']}"
        udev = (_propriedades_udev(node) if Path(node).exists()
                else {"_erro": "node inexistente"})
        serial = udev.get("ID_SERIAL_SHORT")
        if (vid, pid, serial) in ids_ja_vistos:
            continue
        dispositivos.append(Device(
            origem="lsusb/udev", classe="gravador",
            valido=True, exibir=True,
            motivo=f"gravador reconhecido ({protocolo}); nao fala esptool",
            local_usb=f"USB {item['bus']}:{item['dev']}",
            nome=nome, protocolo=protocolo,
            vid=vid, pid=pid, serial_usb=serial,
            fabricante=(udev.get("ID_VENDOR_FROM_DATABASE")
                        or udev.get("ID_VENDOR")),
            produto=(udev.get("ID_MODEL_FROM_DATABASE")
                     or udev.get("ID_MODEL") or item.get("desc")),
            descricao=item.get("desc"),
            id_path=udev.get("ID_PATH"),
            udev=udev, usb=item,
        ))
    return dispositivos


def discover_all_devices() -> list[Device]:
    """Executa as duas passadas e devolve a lista consolidada."""
    seriais = discover_serial_devices()
    gravadores = discover_usb_programmers(seriais)
    return seriais + gravadores

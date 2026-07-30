#!/usr/bin/env python3
"""
Renderizacao textual do relatorio consolidado.

Consome o dict produzido por analyze.analyze_report e devolve string
formatada em blocos, pronta para exibicao em terminal ou gravacao em
arquivo. NAO imprime; quem imprime e o consumidor (scan_command ou TUI).

Tambem oferece render_devices para o painel de dispositivos detectados
(saida da fase de descoberta, antes da sondagem completa).

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from typing import Any

from .models import Device

_LARGURA = 60
_LABELS_CLASSE = {
    "serial_esptool": "serial compativel com esptool",
    "serial_virtual": "serial virtual permitida",
    "gravador":       "gravador reconhecido",
    "desconhecido":   "desconhecido",
}


def _titulo(texto: str) -> list[str]:
    """Barra de titulo padrao das secoes."""
    return ["=" * _LARGURA, texto, "=" * _LARGURA]


def render_devices(
    dispositivos: list[Device],
    mostrar_falhas: bool = False,
) -> str:
    """
    Painel de dispositivos detectados na descoberta.

    mostrar_falhas: se True, inclui dispositivos que falharam na sondagem
                    e nao-reconhecidos (util em modo diagnostico).
    """
    L: list[str] = _titulo("DISPOSITIVOS RELEVANTES DETECTADOS")
    exibidos = 0

    for d in dispositivos:
        probe_ok = bool(d.probe.get("ok"))
        eh_serial = d.classe in {"serial_esptool", "serial_virtual"}

        if eh_serial and not probe_ok and not mostrar_falhas:
            continue
        if not d.exibir and not mostrar_falhas:
            continue
        if d.classe == "desconhecido" and not mostrar_falhas:
            continue

        exibidos += 1

        if eh_serial:
            tag = "ESPTOOL" if probe_ok else "FALHA"
            L.append(f"\n[{tag}] {d.porta}")
            L.append(f"     Tipo      : {_LABELS_CLASSE.get(d.classe, d.classe)}")
            L.append(f"     Adaptador : {d.nome or '-'}")
            L.append(f"     VID:PID   : {d.vid or '?'}:{d.pid or '?'}")
            if d.serial_usb:
                L.append(f"     Serial USB: {d.serial_usb}")
            if probe_ok:
                chip = d.probe.get("chip", {})
                L.append(f"     Chip      : {chip.get('modelo', '-')}")
                L.append(f"     MAC       : {chip.get('mac', '-')}")
            else:
                L.append(f"     Motivo    : {d.motivo}")

        elif d.classe == "gravador":
            L.append(f"\n[GRAVADOR] {d.porta or d.local_usb or '-'}")
            L.append(f"           Tipo      : gravador reconhecido")
            L.append(f"           Nome      : {d.nome or '-'}")
            L.append(f"           VID:PID   : {d.vid or '?'}:{d.pid or '?'}")
            L.append(f"           Protocolo : {d.protocolo or '-'}")
            L.append("           esptool   : nao compativel")

        elif mostrar_falhas:
            L.append(f"\n[IGNORADO] {d.porta or d.local_usb or '-'}")
            L.append(f"          Classe : {_LABELS_CLASSE.get(d.classe, d.classe)}")
            L.append(f"          Motivo : {d.motivo}")

    if exibidos == 0:
        L.append("\nNenhum dispositivo valido/relevante para exibir.")

    return "\n".join(L)


def _bloco_identidade(ident: dict[str, Any]) -> list[str]:
    return [
        "\n-- Identidade --",
        f"  Modelo        : {ident['modelo']}",
        f"  Chip          : {ident['chip']}",
        f"  Revisao       : {ident['revisao']}",
        f"  MAC           : {ident['mac']}",
        f"  Perfil        : {ident['perfil_chave']} ({ident['perfil_status']})",
        f"  Porta usada   : {ident['porta_usada']}",
        f"  Adaptador     : {ident['adaptador']} [{ident['vid_pid']}]",
        f"  USB           : {ident['usb']}",
        f"  ROM           : {ident['rom']}",
    ]


def _bloco_cpu(cpu: dict[str, Any]) -> list[str]:
    return [
        "\n-- CPU / Clock --",
        f"  Nucleos       : {cpu['nucleos']}",
        f"  Clock maximo  : {cpu['clock_max']}",
        f"  Clock runtime : {cpu['clock_runtime']}",
        f"  Cristal       : {cpu['cristal']}",
    ]


def _bloco_boot(boot: dict[str, Any]) -> list[str]:
    L = [
        "\n-- Boot / Firmware --",
        f"  Boot mode     : {boot['modo']}",
        f"  Reset         : {boot['reset']}",
        f"  SPI speed     : {boot['spi_speed'] or 'Desconhecido'}",
        f"  SPI mode      : {boot['spi_mode'] or 'Desconhecido'}",
    ]
    if boot["app"]:
        L.append(f"  App           : {boot['app']} v{boot['app_version'] or '?'}")
    if boot["idf"]:
        L.append(f"  ESP-IDF       : {boot['idf']}")
    return L


def _bloco_flash(flash: dict[str, Any]) -> list[str]:
    L = [
        "\n-- Flash --",
        f"  Fisica        : {flash['fisica']}",
        f"  Firmware hdr  : {flash['firmware_header']}",
        f"  Fabricante    : {flash['fabricante']}",
        f"  Device ID     : {flash['device_id']}",
    ]
    if flash["tipo_efuse"]:
        L.append(f"  Tipo eFuse    : {flash['tipo_efuse']}")
    if flash["voltagem"]:
        L.append(f"  Voltagem      : {flash['voltagem']}")
    if flash["driver_idf"]:
        L.append(f"  Driver IDF    : {flash['driver_idf']}")
    if flash["alerta"]:
        L.append(f"  ALERTA        : {flash['alerta']}")
    return L


def _bloco_psram(psram: dict[str, Any]) -> list[str]:
    return [
        "\n-- PSRAM --",
        f"  Capacidade    : {psram['capacidade']}",
        f"  Vendor        : {psram['vendor']}",
        f"  Runtime       : {psram['runtime']}",
        f"  Velocidade    : {psram['velocidade']}",
        f"  Fonte         : {psram['fonte']}",
        f"  eFuse         : {psram['efuse']}",
    ]


def _bloco_ram(
    ram: list[dict[str, str]], fonte: str, padrao: bool,
) -> list[str]:
    L = ["\n-- RAM --"]
    if ram:
        for item in ram:
            L.append(f"  {item['tipo']:<20}: {item['tamanho']}")
    else:
        L.append("  RAM                 : nao informada")
    if fonte:
        L.append(f"  Fonte               : {fonte}")
    if padrao:
        L.append("  Observacao          : fallback/placeholder; "
                 "pode nao representar heap livre em runtime")
    return L


def _bloco_seguranca(seg: dict[str, Any]) -> list[str]:
    return [
        "\n-- Seguranca / Debug --",
        f"  Secure Boot   : {seg['secure_boot']}",
        f"  Flash Encrypt : {seg['flash_encryption']}",
        f"  JTAG pad      : {seg['jtag_pad']}",
        f"  JTAG USB      : {seg['jtag_usb']}",
        f"  Download mode : {seg['download_mode']}",
        f"  USB Ser/JTAG  : {seg['usb_serial_jtag']}",
    ]


def _bloco_particoes(partes: list[dict[str, str]]) -> list[str]:
    L = ["\n-- Particoes --"]
    if partes:
        for p in partes:
            L.append(
                f"  {p['nome']:<12}: {p['offset']:<8} / {p['tamanho']:<8} "
                f"{p['tipo']}/{p['subtipo']}"
            )
    else:
        L.append("  Tabela ausente ou invalida")
    return L


def render_report(relatorio: dict[str, Any], stamp: str = "") -> str:
    """
    Renderiza o relatorio completo do analyze_report em texto formatado.
    stamp: rotulo opcional (timestamp) para o cabecalho.
    """
    L: list[str] = _titulo(f"RESUMO DA PLACA{f' - {stamp}' if stamp else ''}")
    L.extend(_bloco_identidade(relatorio["identidade"]))
    L.extend(_bloco_cpu(relatorio["cpu"]))
    L.append("\n-- Conectividade --")
    L.append(f"  Recursos      : {relatorio['conectividade']['itens']}")
    L.extend(_bloco_boot(relatorio["boot"]))
    L.extend(_bloco_flash(relatorio["flash"]))
    L.extend(_bloco_psram(relatorio["psram"]))
    L.extend(_bloco_ram(
        relatorio["ram"], relatorio.get("ram_fonte", ""),
        relatorio.get("ram_padrao", False),
    ))
    L.extend(_bloco_seguranca(relatorio["seguranca"]))
    L.extend(_bloco_particoes(relatorio["particoes"]))
    if relatorio.get("alertas"):
        L.append("\n-- Alertas --")
        for alerta in relatorio["alertas"]:
            L.append(f"  - {alerta}")
    return "\n".join(L)

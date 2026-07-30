#!/usr/bin/env python3
"""
Varredura completa de hardware no boot (@E5-T5.1).

Orquestra: deteccao de portas -> interrogacao de chips -> busca/criacao
de perfil por MAC -> deteccao de divergencias.

Executado automaticamente no boot (terreno seguro: nada gravando).
Re-varredura manual sob demanda (@E5-T5.2) usa a mesma funcao.

Principios:
  - Leitura nao-destrutiva: nunca escreve no chip.
  - Falha em uma porta nao cancela a varredura das demais.
  - Identificacao por MAC: cada placa fisica tem seu proprio perfil.
  - Dado do chip e travado; cruzamento com banco e informativo.
  - Retorno estruturado: dado cru nao vaza.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from ..core import logger as _logger
from . import ports as _ports
from . import chip_info as _chip
from . import boards_db as _boards

Result = Tuple[bool, Any]


def _scan_port(
    port_info: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    Interroga um unico port e busca/cria o perfil por MAC.
    Nunca lanca; falha vira campo 'error' no resultado.
    """
    device = port_info["device"]
    result: Dict[str, Any] = {
        "device":      device,
        "chip_hint":   port_info.get("chip_hint", ""),
        "description": port_info.get("description", ""),
        "chip":        None,
        "matched_model":   None,
        "profile_created": False,
        "divergencias":    [],
        "dados_ausentes":    [],
        "campos_atualizados": [],
        "campos_fixos_completados": [],
        "campos_fixos_preservados": [],
        "error":           None,
    }

    # Interroga o chip.
    if cancel_event is not None and cancel_event.is_set():
        result["error"] = "varredura cancelada pelo usuario"
        return result
    ok, chip = _chip.read_chip(device, cancel_event=cancel_event)
    if not ok:
        result["error"] = "falha ao interrogar chip: {}".format(chip)
        _logger.get_logger().warning("varredura: %s -> %s", device, result["error"])
        return result

    result["chip"] = chip

    # Busca ou cria o perfil pelo MAC (cada placa fisica = um perfil).
    ok2, res = _boards.find_or_create_by_mac(chip)
    if ok2:
        profile = res["profile"]
        # Nome amigavel do perfil (board_name), com fallback no MAC.
        result["matched_model"]   = profile.get("board_name") or profile.get("mac")
        result["profile_created"] = res["created"]
        # A comparacao veio do banco e ocorreu antes da mesclagem.
        comparison = res.get("comparison") or {}
        result["divergencias"] = list(
            comparison.get("divergencias") or []
        )
        result["dados_ausentes"] = list(
            comparison.get("dados_ausentes") or []
        )
        result["campos_atualizados"] = list(
            res.get("updated_fields") or []
        )
        result["campos_fixos_completados"] = list(
            res.get("enriched_locked_fields") or []
        )
        result["campos_fixos_preservados"] = list(
            res.get("preserved_locked_fields") or []
        )
    else:
        # find_or_create falhou (ex: MAC indisponivel) — segue sem perfil.
        _logger.get_logger().warning(
            "varredura: %s -> perfil nao resolvido: %s", device, res)

    _logger.get_logger().info(
        "varredura: %s -> familia=%s flash=%s psram=%s perfil=%s%s",
        device,
        chip.get("chip_family", "?"),
        chip.get("flash_size", "?"),
        chip.get("psram", "?"),
        result["matched_model"] or "nao identificado",
        " (novo)" if result["profile_created"] else "",
    )
    return result


def scan(
    ports: Optional[List[Dict[str, Any]]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """
    Varredura completa: detecta portas ESP e interroga cada chip.

    ports: lista de portas a varrer (formato de probable_esp_ports()).
           Se None, detecta automaticamente as portas ESP provaveis.

    Retorna (True, lista_de_resultados) onde cada item contem:
      device, chip_hint, description, chip (dict ou None),
      matched_model (str ou None), profile_created (bool),
      divergencias (lista pre-atualizacao), dados_ausentes (lista),
      campos_atualizados/campos_fixos_preservados (listas),
      error (str ou None).
    """
    if cancel_event is not None and cancel_event.is_set():
        return (False, "varredura cancelada pelo usuario")

    if ports is None:
        ok, ports = _ports.probable_esp_ports()
        if not ok:
            return (False, "falha ao detectar portas: {}".format(ports))

    if not ports:
        return (True, [])

    resultados = []
    for port_info in ports:
        if cancel_event is not None and cancel_event.is_set():
            return (False, "varredura cancelada pelo usuario")
        resultado = _scan_port(port_info, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return (False, "varredura cancelada pelo usuario")
        resultados.append(resultado)

    ok_count  = sum(1 for r in resultados if r["chip"] is not None)
    err_count = sum(1 for r in resultados if r["error"] is not None)
    _logger.get_logger().info(
        "varredura concluida: %d porta(s), %d chip(s) lido(s), %d erro(s)",
        len(resultados), ok_count, err_count,
    )
    return (True, resultados)


def scan_summary(results: List[Dict[str, Any]]) -> str:
    """
    Gera resumo legivel da varredura para exibicao na TUI.
    Consome o retorno de scan().
    """
    if not results:
        return "Nenhuma placa ESP detectada."
    linhas = []
    for r in results:
        dev = r["device"]
        if r["error"]:
            linhas.append("{}: erro — {}".format(dev, r["error"]))
            continue
        chip = r["chip"] or {}
        familia = chip.get("chip_family", "Desconhecido")
        flash   = chip.get("flash_size", "?")
        psram   = chip.get("psram", "Nenhum")
        modelo  = r["matched_model"] or "nao identificado no banco"
        novo    = " (novo perfil)" if r.get("profile_created") else ""
        linhas.append("{}: {} | Flash {} | PSRAM {} | perfil: {}{}".format(
            dev, familia, flash, psram, modelo, novo))
        for div in r.get("divergencias", []):
            tipo = "FIXO preservado" if div.get("locked") else "observado"
            linhas.append(
                "  ! divergencia [{}] em {}: chip='{}' perfil='{}'".format(
                    tipo, div["campo"], div["no_chip"], div["no_perfil"]
                )
            )
        completed = r.get("campos_fixos_completados") or []
        if completed:
            linhas.append(
                "  i dados fixos ausentes completados: {}".format(
                    ", ".join(completed)
                )
            )
        missing_chip = [
            item["campo"] for item in r.get("dados_ausentes", [])
            if item.get("lado") == "chip"
        ]
        if missing_chip:
            linhas.append(
                "  i sem leitura viva para comparar: {}".format(
                    ", ".join(missing_chip)
                )
            )
    return "\n".join(linhas)


def rescan(
    confirm: bool = False,
    ports=None,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """
    Re-varredura manual sob demanda (@E5-T5.2).

    Requer confirm=True — operacao pode encerrar processos em andamento
    (monitor ativo na porta). A confirmacao destrutiva e da TUI.

    Retorna (True, resultados) ou (False, motivo).
    """
    if not confirm:
        return (False,
                "re-varredura requer confirmacao explicita (confirm=True); "
                "processos ativos na porta serao interrompidos")
    _logger.get_logger().info("busca de placas iniciada")
    return scan(ports=ports, cancel_event=cancel_event)


__all__ = ["scan", "scan_summary", "rescan"]

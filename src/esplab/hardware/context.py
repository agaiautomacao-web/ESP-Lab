#!/usr/bin/env python3
"""
Resolvedor central do contexto de hardware do ESP Lab.

Encadeia, sem efeitos colaterais:
  projeto -> MAC esperado -> perfil persistido -> MAC vivo -> porta atual.

A porta atual e o mapa de hardware são exclusivamente de runtime. `last_port`
é histórico do projeto e nunca restaura uma seleção automaticamente.

Contrato: (ok, result_or_error); nunca lança; strings em português.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from . import boards_db as _boards
from . import family_profiles as _family_profiles
from ..workspace import project_config as _project_config

Result = Tuple[bool, Any]

FALLBACK_NO_PROJECT = "Nenhum projeto ativo"
FALLBACK_NO_PROFILE = "Nenhum"
FALLBACK_BOARD = "Não identificada"
FALLBACK_MAC = "Não informado"
FALLBACK_TARGET = "Não definido"
FALLBACK_PORT_UNCHECKED = "Não verificada"
FALLBACK_PORT_NOT_FOUND = "Não encontrada"
FALLBACK_LAST_PORT = "Nenhuma"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize_mac(value: Any) -> str:
    return _clean(value).lower()


def resolve(
    project_dir: str | Path | None = None,
    *,
    current_port: str | None = None,
    current_mac: str | None = None,
    hardware_by_port: Mapping[str, Dict[str, Any]] | None = None,
    scan_performed: bool = False,
) -> Result:
    """Resolve contexto, prontidão e identidade sem persistir nem sondar."""
    try:
        cache = dict(hardware_by_port or {})
        errors: list[str] = []
        cfg: Dict[str, Any] = {}
        project_path: Path | None = None

        if project_dir:
            project_path = Path(project_dir).expanduser().resolve()
            ok_cfg, cfg_or_error = _project_config.read(project_path)
            if ok_cfg:
                cfg = cfg_or_error
            else:
                errors.append(str(cfg_or_error))

        expected_mac = _normalize_mac(cfg.get("board_profile_mac"))
        expected_profile: Dict[str, Any] | None = None
        if expected_mac:
            ok_profile, profile_or_error = _boards.get_profile(expected_mac)
            if ok_profile:
                expected_profile = profile_or_error
            else:
                errors.append(str(profile_or_error))

        port = _clean(current_port)
        live_mac = _normalize_mac(current_mac)
        runtime_entry = cache.get(port, {}) if port else {}
        if not isinstance(runtime_entry, dict):
            runtime_entry = {}
        current_chip = runtime_entry.get("chip", {})
        if not isinstance(current_chip, dict):
            current_chip = {}
        if not live_mac:
            live_mac = _normalize_mac(
                runtime_entry.get("mac") or current_chip.get("mac")
            )

        current_profile: Dict[str, Any] | None = None
        if live_mac:
            ok_live, live_or_error = _boards.get_profile(live_mac)
            if ok_live:
                current_profile = live_or_error

        expected_ready = bool(
            expected_profile and expected_profile.get("profile_ready")
        )
        current_ready = bool(
            current_profile and current_profile.get("profile_ready")
        )

        current_validation = None
        if current_profile and current_chip:
            current_validation = _family_profiles.validate_profile_against_chip(
                current_profile, current_chip, require_ready=True
            )

        expected_validation = None
        if expected_profile and current_chip and live_mac:
            expected_validation = _family_profiles.validate_profile_against_chip(
                expected_profile, current_chip, require_ready=True
            )

        project_name = (
            project_path.name if project_path is not None
            else FALLBACK_NO_PROJECT
        )
        board_name = (
            _clean((expected_profile or {}).get("board_name"))
            or _clean(cfg.get("board_name"))
            or FALLBACK_BOARD
        )
        profile_name = (
            _clean((expected_profile or {}).get("board_name"))
            or FALLBACK_NO_PROFILE
        )
        family = _clean((expected_profile or {}).get("chip_family"))
        target = _clean(cfg.get("target")) or FALLBACK_TARGET
        profile_target = _clean((expected_profile or {}).get("target"))
        last_port = _clean(cfg.get("last_port")) or FALLBACK_LAST_PORT
        selectable_found = any(
            isinstance(entry, dict) and entry.get("selectable")
            for entry in cache.values()
        )
        port_status = (
            port if port else
            (
                FALLBACK_PORT_NOT_FOUND
                if scan_performed and not selectable_found
                else FALLBACK_PORT_UNCHECKED
            )
        )

        if not expected_mac or not live_mac:
            match: bool | None = None
        else:
            match = expected_mac == live_mac

        expected_reasons = list(
            (expected_profile or {}).get("profile_readiness_reasons") or []
        )
        current_reasons = list(
            (current_profile or {}).get("profile_readiness_reasons") or []
        )
        expected_match_reasons = list(
            (expected_validation or {}).get("reasons") or []
        )
        current_match_reasons = list(
            (current_validation or {}).get("reasons") or []
        )

        runtime_profile_usable = bool(
            current_profile and current_ready
            and current_validation and current_validation.get("use_allowed")
        )
        ready_for_flash = bool(
            expected_mac and expected_profile and expected_ready
            and port and live_mac and expected_mac == live_mac
            and expected_validation and expected_validation.get("use_allowed")
        )

        return (True, {
            "project_active": project_path is not None,
            "project_dir": str(project_path) if project_path else "",
            "project_name": project_name,
            "config": cfg,
            "expected_mac": expected_mac,
            "expected_mac_display": expected_mac or FALLBACK_MAC,
            "expected_profile": expected_profile,
            "expected_profile_ready": expected_ready,
            "expected_profile_readiness_status": (
                (expected_profile or {}).get("profile_readiness_status")
                or "incomplete"
            ),
            "expected_profile_readiness_reasons": expected_reasons,
            "profile_name": profile_name,
            "board_name": board_name,
            "family": family,
            "project_target": _clean(cfg.get("target")),
            "target_display": target,
            "profile_target": profile_target,
            "last_port": _clean(cfg.get("last_port")),
            "last_port_display": last_port,
            "scan_performed": bool(scan_performed),
            "current_port": port,
            "current_port_display": port_status,
            "current_mac": live_mac,
            "current_mac_display": live_mac or FALLBACK_MAC,
            "current_entry": runtime_entry,
            "current_chip": current_chip,
            "current_profile": current_profile,
            "current_profile_ready": current_ready,
            "current_profile_readiness_status": (
                (current_profile or {}).get("profile_readiness_status")
                or "incomplete"
            ),
            "current_profile_readiness_reasons": current_reasons,
            "current_profile_validation": current_validation,
            "current_profile_match_reasons": current_match_reasons,
            "expected_profile_validation": expected_validation,
            "expected_profile_match_reasons": expected_match_reasons,
            "live_matches_expected": match,
            "association_exists": bool(expected_mac and expected_profile),
            "runtime_profile_usable": runtime_profile_usable,
            "ready_for_flash": ready_for_flash,
            "errors": errors,
        })
    except Exception as exc:
        return (False, f"falha ao resolver contexto de hardware: {exc}")


__all__ = [
    "resolve",
    "FALLBACK_NO_PROJECT", "FALLBACK_NO_PROFILE", "FALLBACK_BOARD",
    "FALLBACK_MAC", "FALLBACK_TARGET", "FALLBACK_PORT_UNCHECKED",
    "FALLBACK_PORT_NOT_FOUND", "FALLBACK_LAST_PORT",
]

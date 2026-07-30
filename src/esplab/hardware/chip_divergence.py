#!/usr/bin/env python3
"""
Deteccao de divergencia chip-vs-perfil (@E5-T5.8).

Compara o dado vivo antes de qualquer atualizacao do perfil. A comparacao e
pura: nao grava no banco e nao altera os dicionarios recebidos.

Regras:
  - valor ausente/desconhecido nao e divergencia;
  - campo fixo conhecido nunca e corrigido silenciosamente;
  - campo observavel/selecionavel pode ser atualizado pela camada do banco,
    mas a diferenca e registrada antes da atualizacao;
  - normalizacao evita falso positivo de grafia (4 MB == 4MB,
    ESP32-S3 == esp32s3, 0xC8 == c8).

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

from . import family_profiles as _family_profiles

Result = Tuple[bool, Any]

_UNKNOWN = {
    "", "unknown", "desconhecido", "desconhecida", "nao informado",
    "não informado", "nao identificada", "não identificada", "n/a",
    "na", "indisponivel", "indisponível", "not detected",
    "nao detectada", "não detectada",
}
_NONE = {"nenhum", "none", "sem", "false", "nao", "não", "0"}


def _text(value: Any) -> str:
    return str(value).strip()


def _basic(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).lower())


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).lower())


def _family(value: Any) -> str:
    return _compact(_family_profiles.normalize_family(value))


def _chip_type(value: Any) -> str:
    text = _basic(value)
    text = re.sub(r"\s*\(revision[^)]*\)\s*$", "", text)
    text = re.sub(r"\s+revision\s+v?[0-9.]+\s*$", "", text)
    return _compact(text)


def _revision(value: Any) -> str:
    text = _basic(value)
    text = re.sub(r"^(revision|rev|versao|versão)\s*[:=-]?\s*", "", text)
    text = re.sub(r"^v", "", text)
    parts = text.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _capacity(value: Any) -> str:
    text = _basic(value)
    if text in _NONE:
        return "none"
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*([kmg])?i?b?", text)
    if match:
        number = match.group(1).replace(",", ".")
        unit = (match.group(2) or "").upper()
        return f"{number}{unit}B" if unit else number
    return _compact(text)


def _frequency(value: Any) -> str:
    return _compact(value)


def _hex(value: Any) -> str:
    text = _compact(value)
    return text[2:] if text.startswith("0x") else text


def _features(value: Any) -> str:
    text = _basic(value)
    tokens = [
        _compact(token)
        for token in re.split(r"[,;/|]+", text)
        if _compact(token)
    ]
    return "|".join(sorted(tokens)) if tokens else _compact(text)


def _psram(value: Any) -> str:
    text = _basic(value)
    if text in _NONE:
        return "none"
    if value is True:
        return "present"
    return _capacity(value)


def _usb(value: Any) -> str:
    return _compact(value)


# chip_key, profile_key, label, locked, normalizer
_FIELD_SPECS: Tuple[
    Tuple[str, str, str, bool, Callable[[Any], str]], ...
] = (
    ("chip_type", "chip_type", "tipo do chip", True, _chip_type),
    ("chip_family", "chip_family", "familia do chip", True, _family),
    ("chip_variant", "chip_variant", "variante do chip", True, _compact),
    ("package_variant", "package_variant", "encapsulamento", True, _compact),
    ("chip_revision", "chip_revision", "revisao do chip", True, _revision),
    ("features", "features", "recursos do chip", True, _features),
    ("crystal", "crystal", "frequencia do cristal", True, _frequency),
    (
        "flash_manufacturer", "flash_manufacturer",
        "fabricante da flash", True, _hex,
    ),
    ("flash_device", "flash_device", "identificador da flash", True, _hex),
    ("flash_size", "flash_size_mb", "tamanho da flash", False, _capacity),
    ("psram", "psram_enabled", "PSRAM", False, _psram),
    ("usb_mode", "usb_mode", "modo USB", False, _usb),
)

_SPEC_BY_PROFILE = {item[1]: item for item in _FIELD_SPECS}
LOCKED_PROFILE_FIELDS = frozenset(
    profile_key for _, profile_key, _, locked, _ in _FIELD_SPECS if locked
)


def _is_missing(value: Any, *, profile_key: str = "") -> bool:
    if value is None:
        return True
    text = _basic(value)
    if text in _UNKNOWN:
        return True
    # "Nenhum" e um valor valido para PSRAM; nos demais campos continua
    # sendo ausencia de informacao.
    if text in _NONE and profile_key != "psram_enabled":
        return True
    return False


def is_missing_profile_value(profile_key: str, value: Any) -> bool:
    """Classifica ausencia de forma especifica por campo do perfil."""
    return _is_missing(value, profile_key=profile_key)


def normalize_profile_value(profile_key: str, value: Any) -> str:
    """Normaliza um valor usando a regra de comparacao do campo."""
    spec = _SPEC_BY_PROFILE.get(profile_key)
    if spec is None:
        return _basic(value)
    return spec[4](value)


def profile_values_equivalent(profile_key: str, left: Any, right: Any) -> bool:
    """Compara dois valores do mesmo campo sem confundir grafia com mudanca."""
    if is_missing_profile_value(profile_key, left):
        return is_missing_profile_value(profile_key, right)
    if is_missing_profile_value(profile_key, right):
        return False
    return normalize_profile_value(profile_key, left) == normalize_profile_value(
        profile_key, right
    )


def check_divergence(
    chip_info: Dict[str, Any],
    board_profile: Dict[str, Any],
) -> Result:
    """
    Compara chip real com o perfil persistido antes da mesclagem.

    resultado = {
        status: ok|aviso,
        divergencias: [...],
        dados_ausentes: [...],
        campos_conferidos: int,
        has_locked_divergence: bool,
        message: str,
    }
    """
    if not isinstance(chip_info, dict):
        return (False, "chip_info invalido (esperado dict)")
    if not isinstance(board_profile, dict):
        return (False, "perfil de placa invalido (esperado dict)")

    divergences: List[Dict[str, Any]] = []
    missing: List[Dict[str, str]] = []
    checked = 0

    for chip_key, profile_key, label, locked, normalizer in _FIELD_SPECS:
        chip_value = chip_info.get(chip_key)
        profile_value = board_profile.get(profile_key)
        chip_missing = _is_missing(chip_value, profile_key=profile_key)
        profile_missing = _is_missing(profile_value, profile_key=profile_key)

        if chip_missing or profile_missing:
            if chip_missing and not profile_missing:
                side = "chip"
            elif profile_missing and not chip_missing:
                side = "perfil"
            else:
                side = "ambos"
            missing.append({
                "campo": label,
                "campo_chip": chip_key,
                "campo_perfil": profile_key,
                "lado": side,
                "no_chip": _text(chip_value),
                "no_perfil": _text(profile_value),
            })
            continue

        checked += 1
        if normalizer(chip_value) == normalizer(profile_value):
            continue

        divergences.append({
            "campo": label,
            "campo_chip": chip_key,
            "campo_perfil": profile_key,
            "no_chip": _text(chip_value),
            "no_perfil": _text(profile_value),
            "locked": locked,
            "tipo": "fixo" if locked else "observado",
            "acao": "preservar_perfil" if locked else "atualizacao_permitida",
        })

    locked_count = sum(1 for item in divergences if item["locked"])
    if not divergences:
        message = "chip confere com os dados comparaveis do perfil"
        if missing:
            message += f"; {len(missing)} campo(s) sem base para comparar"
        return (True, {
            "status": "ok",
            "divergencias": [],
            "dados_ausentes": missing,
            "campos_conferidos": checked,
            "has_locked_divergence": False,
            "message": message,
        })

    parts = []
    for item in divergences:
        parts.append(
            "{} [{}]: chip='{}' perfil='{}'".format(
                item["campo"], item["tipo"], item["no_chip"],
                item["no_perfil"],
            )
        )
    return (True, {
        "status": "aviso",
        "divergencias": divergences,
        "dados_ausentes": missing,
        "campos_conferidos": checked,
        "has_locked_divergence": bool(locked_count),
        "message": "divergencia detectada antes da atualizacao — " + "; ".join(parts),
    })


__all__ = [
    "check_divergence", "LOCKED_PROFILE_FIELDS",
    "is_missing_profile_value", "normalize_profile_value",
    "profile_values_equivalent",
]

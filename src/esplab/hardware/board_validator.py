#!/usr/bin/env python3
"""
Validacao de modelo de placa contra o chip real (@E5-T5.6).

Recebe o nome do modelo e os dados ja interrogados do chip (peca chip_info) e
decide se libera o acesso. A FAMILIA e o validador decisivo: se a familia do
perfil nao bate com a do chip, rejeita e trava o acesso.

Tambem constroi o perfil inicial a partir dos dados do chip, para o caso
"modelo nao encontrado -> cria novo": grava o que o esptool entregou, deixa
o resto nos padroes (a cargo do usuario completar com dados do fabricante).

A peca NAO interroga o chip nem grava no banco — recebe os dados prontos e
delega leitura/gravacao as pecas proprias (modularidade). Retorno
(ok, result_or_error); nunca lanca; mensagens em portugues.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from . import boards_db as _boards
from . import family_profiles as _family_profiles

Result = Tuple[bool, Any]  # (ok, result_or_error)


def _normalize_family(value: Any) -> str:
    """Normalizacao leve para comparar familias (maiusculas, sem hifen/espaco)."""
    if not isinstance(value, str):
        return ""
    return value.upper().replace("-", "").replace("_", "").replace(" ", "").strip()


def build_profile_from_chip(chip_info: Dict[str, Any]) -> Dict[str, Any]:
    """Constrói perfil pela família, sem herdar o default ESP32-S3."""
    return _family_profiles.build_family_profile(chip_info)


def validate(model_name: str, chip: Dict[str, Any]) -> Result:
    """
    Valida o modelo informado contra o chip interrogado.

    Retorna (True, verdict) sempre que conseguiu avaliar; o veredito diz se o
    acesso e liberado. Retorna (False, motivo) so em erro operacional (ex.
    dados de chip ausentes).

    verdict = {
        "valid": bool,            # familia bate?
        "family_match": bool,
        "access_granted": bool,   # libera o acesso a placa?
        "model_found": bool,      # o modelo existe no banco?
        "expected_family": str,   # familia do perfil
        "actual_family": str,     # familia do chip
        "message": str,           # mensagem em portugues para a TUI
        "warnings": list,         # avisos nao-bloqueantes (normalmente vazio)
    }
    """
    if not isinstance(chip, dict) or not chip.get("chip_family"):
        return (False, "dados do chip ausentes ou sem familia")
    if not isinstance(model_name, str) or not model_name.strip():
        return (False, "nome do modelo vazio ou invalido")
    model_name = model_name.strip()

    actual_family = chip["chip_family"]

    # Busca o perfil no banco.
    ok, profile = _boards.get_profile(model_name)
    if not ok:
        # Modelo nao encontrado: sinaliza para o fluxo de cadastrar novo.
        return (True, {
            "valid": False,
            "family_match": False,
            "access_granted": False,
            "model_found": False,
            "expected_family": "Nenhum",
            "actual_family": actual_family,
            "message": f"modelo '{model_name}' nao encontrado; "
                       f"o chip e {actual_family} (cadastrar novo perfil)",
            "warnings": [],
        })

    expected_family = profile.get("chip_family", "Desconhecido")
    match = _normalize_family(expected_family) == _normalize_family(actual_family)

    if match:
        message = f"placa validada: {actual_family} confere com o perfil '{model_name}'"
    else:
        message = (f"incompatibilidade: perfil '{model_name}' e {expected_family}, "
                   f"mas o chip e {actual_family}; acesso bloqueado")

    return (True, {
        "valid": match,
        "family_match": match,
        "access_granted": match,
        "model_found": True,
        "expected_family": expected_family,
        "actual_family": actual_family,
        "message": message,
        "warnings": [],
    })


__all__ = ["validate", "build_profile_from_chip"]

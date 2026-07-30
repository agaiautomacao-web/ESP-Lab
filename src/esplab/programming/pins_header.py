#!/usr/bin/env python3
"""
Gerador do hardware_pins.h do ESP Lab (@E8-T8.5).

Le o pinout_mapping do perfil de placa e gera um header C com um #define por
pino nomeado (label -> gpio), permitindo usar nomes amigaveis no codigo sem
decorar numeros de GPIO. Diferencial central da aplicacao (vinculo codigo<->hw).

Regras (PROJECT.md cap. Programacao):
  - Gerado e SOMENTE-LEITURA: sobrescrito a cada build; aviso no topo.
  - #define <label> <gpio> para pinos com GPIO; pinos de energia (gpio null)
    viram comentario, nao #define.
  - 'description' do pino vira comentario ao lado do #define.
  - Labels invalidos para C: REJEITA com aviso (nao sanitiza em silencio).
  - Labels duplicados: REJEITA com aviso.
  - Pinout vazio: header valido mas vazio, com comentario.
  - Include guards (#ifndef) sempre.

Retorno (ok, result_or_error); nunca lanca; mensagens em portugues.
Escrita atomica via storage; caminho previsivel no projeto.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import storage as _storage

Result = Tuple[bool, Any]  # (ok, result_or_error)

HEADER_FILENAME = "hardware_pins.h"
INCLUDE_GUARD = "HARDWARE_PINS_H"

# Identificador C valido: comeca com letra/underscore, segue com alfanumerico/underscore.
_C_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TOP_NOTICE = """/*
 * hardware_pins.h
 * ARQUIVO GERADO AUTOMATICAMENTE pelo ESP Lab.
 * NAO EDITAR A MAO: este arquivo e sobrescrito a cada build.
 * Origem: mapeamento de pinos do perfil de placa.
 */"""


def header_path(project_dir: Path | str) -> Path:
    """Caminho do header dentro do projeto (<projeto>/main/hardware_pins.h)."""
    return Path(project_dir).expanduser().resolve() / "main" / HEADER_FILENAME


def _is_valid_c_identifier(label: Any) -> bool:
    return isinstance(label, str) and bool(_C_IDENTIFIER_RE.match(label))


def validate_pinout(pinout: List[Dict[str, Any]]) -> Result:
    """
    Valida o pinout para geracao de header. (True, None) ou (False, [erros]).
    Checa: labels validos como identificador C, e ausencia de duplicatas
    (apenas para pinos com GPIO definido, que viram #define).
    """
    if not isinstance(pinout, list):
        return (False, ["pinout_mapping nao e uma lista"])

    errors: List[str] = []
    seen_labels = {}
    for i, pin in enumerate(pinout):
        if not isinstance(pin, dict):
            errors.append(f"pino #{i}: nao e um objeto")
            continue
        gpio = pin.get("gpio", None)
        label = pin.get("label", "")
        # Pinos sem GPIO (energia) nao viram #define; nao exigem label C valido.
        if gpio is None:
            continue
        if not _is_valid_c_identifier(label):
            errors.append(f"pino fisico {pin.get('physical', '?')}: "
                          f"label '{label}' nao e um identificador C valido")
            continue
        if label in seen_labels:
            errors.append(f"label duplicado: '{label}' "
                          f"(pinos fisicos {seen_labels[label]} e {pin.get('physical', '?')})")
        else:
            seen_labels[label] = pin.get("physical", "?")

    return (True, None) if not errors else (False, errors)


def render_header(pinout: List[Dict[str, Any]]) -> Result:
    """
    Renderiza o conteudo do header a partir do pinout. (True, texto) ou
    (False, [erros]) se a validacao falhar.
    """
    ok, err = validate_pinout(pinout)
    if not ok:
        return (False, err)

    lines: List[str] = [_TOP_NOTICE, "", f"#ifndef {INCLUDE_GUARD}", f"#define {INCLUDE_GUARD}", ""]

    define_pins = [p for p in pinout if p.get("gpio") is not None]
    power_pins = [p for p in pinout if p.get("gpio") is None]

    if not define_pins and not power_pins:
        lines.append("/* Nenhum pino mapeado ainda. */")
    else:
        if define_pins:
            lines.append("/* Pinos GPIO nomeados */")
            for p in sorted(define_pins, key=lambda x: x.get("physical", 0)):
                label = p["label"]
                gpio = p["gpio"]
                desc = p.get("description", "").strip()
                comment = f"  // {desc}" if desc else ""
                lines.append(f"#define {label} {gpio}{comment}")
            lines.append("")
        if power_pins:
            lines.append("/* Pinos de energia / sem GPIO (referencia) */")
            for p in sorted(power_pins, key=lambda x: x.get("physical", 0)):
                phys = p.get("physical", "?")
                lab = p.get("label", "?")
                desc = p.get("description", "").strip()
                extra = f" - {desc}" if desc else ""
                lines.append(f"// pino fisico {phys}: {lab}{extra}")
            lines.append("")

    lines.append(f"#endif /* {INCLUDE_GUARD} */")
    return (True, "\n".join(lines) + "\n")


def generate(project_dir: Path | str, pinout: List[Dict[str, Any]]) -> Result:
    """
    Gera e grava o hardware_pins.h no projeto. (True, caminho) ou (False, motivo).
    O diretorio main/ deve existir (criado pelo Workspace ao criar o projeto).
    """
    ok, content_or_err = render_header(pinout)
    if not ok:
        # content_or_err e a lista de erros de validacao
        return (False, "; ".join(content_or_err))

    path = header_path(project_dir)
    ok, res = _storage.atomic_write_text(path, content_or_err)
    return (True, str(path)) if ok else (False, res)


__all__ = ["generate", "render_header", "validate_pinout", "header_path", "HEADER_FILENAME"]

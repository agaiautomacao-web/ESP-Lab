#!/usr/bin/env python3
"""
Inspecao de bibliotecas/componentes para ESP-IDF.

Classifica uma pasta local antes de qualquer instalacao:
  - componente ESP-IDF pronto
  - componente ESP-IDF incompleto
  - biblioteca Arduino
  - codigo C/C++ generico
  - projeto ESP-IDF completo
  - pacote invalido/desconhecido

Este modulo e SOMENTE LEITURA:
  - nao copia arquivos
  - nao cria components/
  - nao edita main/idf_component.yml
  - nao toca dependencies.lock
  - nao toca managed_components/
  - nao roda idf.py
  - nao baixa nada da internet

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

Result = Tuple[bool, Any]

MAX_DEPTH = 4
MAX_FILES = 500
MAX_READ_BYTES = 256 * 1024

IGNORED_DIRS = {
    ".git",
    "build",
    "managed_components",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
}

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".S", ".s"}
HEADER_EXTS = {".h", ".hpp", ".hh", ".hxx"}
TEXT_EXTS = SOURCE_EXTS | HEADER_EXTS | {
    ".ino",
    ".txt",
    ".md",
    ".yml",
    ".yaml",
    ".ini",
}

TYPE_IDF_READY = "idf_component_ready"
TYPE_IDF_INCOMPLETE = "idf_component_incomplete"
TYPE_ARDUINO = "arduino_library"
TYPE_DUAL_FRAMEWORK = "dual_framework_component"
TYPE_CPP_GENERIC = "cpp_generic"
TYPE_MIXED_PROJECT = "mixed_project"
TYPE_INVALID = "invalid_package"
TYPE_UNKNOWN = "unknown"


def _rel(root: Path, path: Optional[Path]) -> Optional[str]:
    """Converte caminho absoluto para relativo ao root, quando possivel."""
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _rel_list(root: Path, items: List[Path]) -> List[str]:
    """Lista de caminhos relativos ao root."""
    return [_rel(root, p) or str(p) for p in items]


def _depth(root: Path, path: Path) -> int:
    """Profundidade relativa ao root."""
    try:
        return len(path.relative_to(root).parts)
    except Exception:
        return MAX_DEPTH + 1


def _read_text_limited(path: Path) -> str:
    """
    Le arquivo texto de forma defensiva.
    Nunca lanca; retorna string vazia em falha.
    """
    try:
        raw = path.read_bytes()[:MAX_READ_BYTES]
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _iter_files(root: Path) -> List[Path]:
    """
    Varre arquivos com limites de profundidade e quantidade.
    Ignora diretorios pesados/gerados.
    """
    files: List[Path] = []

    for current, dirs, names in os.walk(root):
        current_path = Path(current)

        dirs[:] = [
            d for d in dirs
            if d not in IGNORED_DIRS
            and _depth(root, current_path / d) <= MAX_DEPTH
        ]

        if _depth(root, current_path) > MAX_DEPTH:
            dirs[:] = []
            continue

        for name in names:
            p = current_path / name
            if len(files) >= MAX_FILES:
                return files
            if p.is_file():
                files.append(p)

    return files


def _has_text(path: Optional[Path], needle: str) -> bool:
    """Procura texto em arquivo, com leitura limitada."""
    if path is None or not path.is_file():
        return False
    return needle in _read_text_limited(path)


def _find_first(root: Path, filename: str) -> Optional[Path]:
    """Busca arquivo diretamente na raiz."""
    p = root / filename
    return p if p.is_file() else None


def _contains_any(text: str, needles: List[str]) -> bool:
    """True se qualquer marcador aparece no texto."""
    return any(n in text for n in needles)


def _detect_arduino_includes(files: List[Path]) -> List[Path]:
    """Detecta includes fortes de Arduino."""
    found: List[Path] = []
    markers = [
        "#include <Arduino.h>",
        '#include "Arduino.h"',
    ]
    for p in files:
        if p.suffix not in TEXT_EXTS:
            continue
        text = _read_text_limited(p)
        if _contains_any(text, markers):
            found.append(p)
    return found


def _detect_idf_includes(files: List[Path]) -> List[Path]:
    """Detecta includes comuns de ESP-IDF."""
    found: List[Path] = []
    markers = [
        "#include <esp_log.h>",
        '#include "esp_log.h"',
        "#include <freertos/FreeRTOS.h>",
        '#include "freertos/FreeRTOS.h"',
        "#include <driver/gpio.h>",
        '#include "driver/gpio.h"',
    ]
    for p in files:
        if p.suffix not in TEXT_EXTS:
            continue
        text = _read_text_limited(p)
        if _contains_any(text, markers):
            found.append(p)
    return found


def _platformio_is_arduino(path: Optional[Path]) -> bool:
    """Detecta framework Arduino em platformio.ini."""
    if path is None or not path.is_file():
        return False
    text = _read_text_limited(path).lower().replace(" ", "")
    return "framework=arduino" in text


def _find_candidate_components(root: Path) -> List[Dict[str, Any]]:
    """
    Procura componentes internos em repositorios/projetos mistos.
    Somente leitura.
    """
    candidates: List[Dict[str, Any]] = []
    components_dir = root / "components"
    if not components_dir.is_dir():
        return candidates

    for child in sorted(components_dir.iterdir()):
        if not child.is_dir():
            continue
        cmake = child / "CMakeLists.txt"
        ready = _has_text(cmake, "idf_component_register")
        candidates.append({
            "name": child.name,
            "path": str(child.resolve()),
            "ready": ready,
            "cmake": str(cmake.resolve()) if cmake.is_file() else None,
        })

    return candidates


def _collect_facts(root: Path) -> Dict[str, Any]:
    """Coleta fatos objetivos sobre a pasta."""
    all_files = _iter_files(root)

    cmake = _find_first(root, "CMakeLists.txt")
    manifest = _find_first(root, "idf_component.yml")
    library_properties = _find_first(root, "library.properties")
    keywords = _find_first(root, "keywords.txt")
    platformio = _find_first(root, "platformio.ini")

    sources = [
        p for p in all_files
        if p.suffix in SOURCE_EXTS
    ]
    headers = [
        p for p in all_files
        if p.suffix in HEADER_EXTS
    ]
    ino = [
        p for p in all_files
        if p.suffix == ".ino"
    ]

    cmake_text = _read_text_limited(cmake) if cmake else ""

    facts: Dict[str, Any] = {
        "root": root,
        "name": root.name,
        "cmake": cmake,
        "cmake_has_idf_component_register":
            "idf_component_register" in cmake_text,
        "cmake_has_project":
            "project(" in cmake_text,
        "manifest": manifest,
        "library_properties": library_properties,
        "keywords": keywords,
        "platformio": platformio,
        "platformio_framework_arduino":
            _platformio_is_arduino(platformio),
        "has_main_dir": (root / "main").is_dir(),
        "has_components_dir": (root / "components").is_dir(),
        "has_include_dir": (root / "include").is_dir(),
        "has_src_dir": (root / "src").is_dir(),
        "has_sdkconfig":
            (root / "sdkconfig").is_file()
            or (root / "sdkconfig.defaults").is_file(),
        "has_partitions":
            (root / "partitions.csv").is_file()
            or (root / "partition_table.csv").is_file(),
        "sources": sources,
        "headers": headers,
        "ino": ino,
        "arduino_includes": _detect_arduino_includes(
            sources + headers + ino
        ),
        "idf_includes": _detect_idf_includes(
            sources + headers
        ),
        "candidate_components": _find_candidate_components(root),
        "file_count": len(all_files),
        "truncated": len(all_files) >= MAX_FILES,
    }
    return facts


def _score(facts: Dict[str, Any]) -> Dict[str, int]:
    """Calcula pontuacao heuristica."""
    scores = {
        "idf": 0,
        "arduino": 0,
        "project": 0,
        "cpp": 0,
    }

    if facts["cmake_has_idf_component_register"]:
        scores["idf"] += 5
    if facts["manifest"] is not None:
        scores["idf"] += 3
    if facts["has_include_dir"]:
        scores["idf"] += 2
    if facts["has_src_dir"]:
        scores["idf"] += 2
    if facts["idf_includes"]:
        scores["idf"] += 1

    if facts["library_properties"] is not None:
        scores["arduino"] += 5
    if facts["ino"]:
        scores["arduino"] += 4
    if facts["arduino_includes"]:
        scores["arduino"] += 4
    if facts["keywords"] is not None:
        scores["arduino"] += 3
    if facts["platformio_framework_arduino"]:
        scores["arduino"] += 2

    if facts["cmake_has_project"]:
        scores["project"] += 5
    if facts["has_main_dir"]:
        scores["project"] += 4
    if facts["has_sdkconfig"]:
        scores["project"] += 3
    if facts["has_components_dir"]:
        scores["project"] += 3
    if facts["has_partitions"]:
        scores["project"] += 2

    scores["cpp"] += min(len(facts["sources"]), 5)
    scores["cpp"] += min(len(facts["headers"]), 5)

    return scores


def _classify(facts: Dict[str, Any], scores: Dict[str, int]) -> str:
    """
    Classifica a pasta.
    Ordem importa: projeto inteiro antes de componente.
    """
    if scores["project"] >= 7:
        return TYPE_MIXED_PROJECT

    if (
        facts["cmake_has_idf_component_register"]
        and scores["arduino"] >= 5
        and (facts["sources"] or facts["headers"])
    ):
        return TYPE_DUAL_FRAMEWORK

    if scores["arduino"] >= 5:
        return TYPE_ARDUINO

    if facts["cmake_has_idf_component_register"] and (
        facts["sources"] or facts["headers"]
    ):
        return TYPE_IDF_READY

    if facts["manifest"] is not None or facts["cmake"] is not None:
        return TYPE_IDF_INCOMPLETE

    if facts["sources"] or facts["headers"]:
        return TYPE_CPP_GENERIC

    if not facts["sources"] and not facts["headers"]:
        return TYPE_INVALID

    return TYPE_UNKNOWN


def _install_flags(detected_type: str) -> Dict[str, bool]:
    """Define flags de acao permitida por tipo."""
    return {
        "can_install": detected_type == TYPE_IDF_READY,
        "requires_conversion": detected_type in (
            TYPE_IDF_INCOMPLETE,
            TYPE_ARDUINO,
            TYPE_DUAL_FRAMEWORK,
            TYPE_CPP_GENERIC,
        ),
        "requires_selection": detected_type in (
            TYPE_MIXED_PROJECT,
            TYPE_UNKNOWN,
        ),
    }


def _make_reasons_and_warnings(
    detected_type: str,
    facts: Dict[str, Any],
    scores: Dict[str, int],
) -> Tuple[List[str], List[str]]:
    """Gera explicacao legivel do diagnostico."""
    reasons: List[str] = []
    warnings: List[str] = []

    if facts["cmake"] is not None:
        reasons.append("CMakeLists.txt encontrado")
    if facts["cmake_has_idf_component_register"]:
        reasons.append("CMakeLists.txt contem idf_component_register()")
    if facts["cmake_has_project"]:
        reasons.append("CMakeLists.txt de topo contem project()")
    if facts["manifest"] is not None:
        reasons.append("idf_component.yml encontrado")
    if facts["library_properties"] is not None:
        reasons.append("library.properties encontrado")
    if facts["keywords"] is not None:
        reasons.append("keywords.txt encontrado")
    if facts["ino"]:
        reasons.append("arquivo .ino encontrado")
    if facts["arduino_includes"]:
        reasons.append("include Arduino.h detectado")
    if facts["idf_includes"]:
        reasons.append("includes comuns de ESP-IDF detectados")
    if facts["has_main_dir"]:
        reasons.append("diretorio main/ encontrado")
    if facts["has_components_dir"]:
        reasons.append("diretorio components/ encontrado")
    if facts["has_include_dir"]:
        reasons.append("diretorio include/ encontrado")
    if facts["has_src_dir"]:
        reasons.append("diretorio src/ encontrado")
    if facts["sources"]:
        reasons.append("{} arquivo(s) fonte encontrado(s)".format(
            len(facts["sources"])
        ))
    if facts["headers"]:
        reasons.append("{} header(s) encontrado(s)".format(
            len(facts["headers"])
        ))

    if facts["truncated"]:
        warnings.append(
            "varredura limitada a {} arquivos; resultado pode estar incompleto"
            .format(MAX_FILES)
        )

    if detected_type == TYPE_IDF_READY:
        warnings.append(
            "componente parece pronto para importacao local; ainda nao foi "
            "copiado nem registrado"
        )
    elif detected_type == TYPE_IDF_INCOMPLETE:
        warnings.append(
            "sinais de ESP-IDF encontrados, mas a estrutura do componente "
            "parece incompleta"
        )
    elif detected_type == TYPE_ARDUINO:
        warnings.append(
            "biblioteca Arduino detectada; nao e instalavel diretamente em "
            "projeto ESP-IDF puro"
        )
    elif detected_type == TYPE_DUAL_FRAMEWORK:
        warnings.append(
            "componente com sinais de ESP-IDF e Arduino detectado; requer "
            "revisao antes de instalar em projeto ESP-IDF puro"
        )
    elif detected_type == TYPE_CPP_GENERIC:
        warnings.append(
            "codigo C/C++ encontrado, mas sem estrutura de componente ESP-IDF"
        )
    elif detected_type == TYPE_MIXED_PROJECT:
        warnings.append(
            "parece ser um projeto ESP-IDF completo; selecione um componente "
            "interno, se houver"
        )
    elif detected_type == TYPE_INVALID:
        warnings.append(
            "nenhuma estrutura reconhecida de biblioteca/componente foi "
            "encontrada"
        )
    elif detected_type == TYPE_UNKNOWN:
        warnings.append(
            "estrutura nao reconhecida automaticamente; requer revisao manual"
        )

    if not reasons:
        reasons.append("nenhum marcador conhecido encontrado")

    return reasons, warnings


def inspect_library_path(path: str | Path) -> Result:
    """
    Analisa uma pasta local e retorna diagnostico estruturado.

    Esta funcao e somente leitura.
    """
    try:
        root = Path(path).expanduser().resolve()

        if not root.exists():
            return (False, "pasta inexistente: '{}'".format(root))

        if not root.is_dir():
            return (False, "esperado uma pasta, recebido arquivo: '{}'".format(root))

        facts = _collect_facts(root)
        scores = _score(facts)
        detected_type = _classify(facts, scores)
        flags = _install_flags(detected_type)
        reasons, warnings = _make_reasons_and_warnings(
            detected_type,
            facts,
            scores,
        )

        return (True, {
            "path": str(root),
            "name": root.name,
            "type": detected_type,
            "can_install": flags["can_install"],
            "requires_conversion": flags["requires_conversion"],
            "requires_selection": flags["requires_selection"],
            "score": scores,
            "files": {
                "cmake": _rel(root, facts["cmake"]),
                "manifest": _rel(root, facts["manifest"]),
                "library_properties": _rel(root, facts["library_properties"]),
                "keywords": _rel(root, facts["keywords"]),
                "platformio": _rel(root, facts["platformio"]),
                "sources": _rel_list(root, facts["sources"]),
                "headers": _rel_list(root, facts["headers"]),
                "ino": _rel_list(root, facts["ino"]),
                "arduino_includes": _rel_list(root, facts["arduino_includes"]),
                "idf_includes": _rel_list(root, facts["idf_includes"]),
            },
            "candidate_components": facts["candidate_components"],
            "reasons": reasons,
            "warnings": warnings,
        })

    except Exception as e:
        return (False, "erro ao inspecionar biblioteca: {}".format(e))


__all__ = [
    "inspect_library_path",
    "TYPE_IDF_READY",
    "TYPE_IDF_INCOMPLETE",
    "TYPE_ARDUINO",
    "TYPE_DUAL_FRAMEWORK",
    "TYPE_CPP_GENERIC",
    "TYPE_MIXED_PROJECT",
    "TYPE_INVALID",
    "TYPE_UNKNOWN",
]

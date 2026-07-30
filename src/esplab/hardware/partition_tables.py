#!/usr/bin/env python3
"""Gerador de tabelas de particao do ESP Lab (@E6).

Le o catalogo (partition_tables.yml) e gera partitions.csv VALIDO, com offsets
EM BRANCO (gen_esp32part.py alinha — seguro). Tipos APP/OTA + FS (FATFS ou
LittleFS, escolha do usuario). Particoes fixas: nvs, phy_init, [otadata se OTA].

Validacoes: teto de 8 variacoes por tamanho; soma das particoes <= flash.
Retorno (ok, result_or_error); nunca lanca; strings em portugues.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import errors as _errors
from ..core import storage as _storage

Result = Tuple[bool, Any]

CATALOG_REL = "data/partition_tables.yml"
MAX_VARIATIONS = 8

# Particoes fixas (tamanhos padrao ESP-IDF), em bytes.
NVS_SIZE = 0x6000       # 24KB
PHY_SIZE = 0x1000       # 4KB
OTADATA_SIZE = 0x2000   # 8KB
# A tabela de particao ocupa ate 0x10000 (app comeca em 0x10000).
APP_START = 0x10000

_UNIT = {"K": 1024, "M": 1024 * 1024}


def _to_bytes(size: str) -> int:
    """Converte '1500K'/'3M'/'0' em bytes. -1 se invalido."""
    s = str(size).strip().upper()
    if s in ("0", ""):
        return 0
    m = re.match(r"^(\d+)\s*([KM])?$", s)
    if not m:
        return -1
    n = int(m.group(1))
    unit = m.group(2)
    return n * _UNIT[unit] if unit else n


def _flash_bytes(size_label: str) -> int:
    """'16MB' -> bytes."""
    m = re.match(r"^(\d+)MB$", str(size_label).strip())
    return int(m.group(1)) * 1024 * 1024 if m else -1


def catalog_path() -> Path:
    """Caminho do catalogo (junto do modulo)."""
    return Path(__file__).resolve().parent / CATALOG_REL


def load_catalog() -> Result:
    """Le e valida o catalogo YAML. (True, dict) ou (False, motivo)."""
    path = catalog_path()
    if not path.is_file():
        return (False, f"catalogo de particoes ausente: '{path}'")
    ok, data = _storage.read_yaml(path)
    if not ok:
        return (False, data)
    if not isinstance(data, dict) or "tables" not in data:
        return (False, "catalogo invalido: faltam 'tables'")
    return (True, data)


def list_sizes() -> Result:
    """Lista os tamanhos de flash disponiveis no catalogo (ex. ['4MB',...])."""
    ok, data = load_catalog()
    if not ok:
        return (False, data)
    return (True, list(data["tables"].keys()))


def list_variations(size_label: str) -> Result:
    """Lista as variacoes de um tamanho. Valida o teto de 8. (True, [variacoes])."""
    ok, data = load_catalog()
    if not ok:
        return (False, data)
    tables = data["tables"]
    if size_label not in tables:
        return (False, f"tamanho '{size_label}' nao existe no catalogo")
    variations = tables[size_label]
    if not isinstance(variations, list):
        return (False, f"variacoes de '{size_label}' malformadas")
    if len(variations) > MAX_VARIATIONS:
        return (False, f"'{size_label}' tem {len(variations)} variacoes; "
                       f"maximo permitido e {MAX_VARIATIONS} (reagrupar)")
    return (True, variations)


def _fixed_overhead(has_ota: bool) -> int:
    """Bytes consumidos antes do app: tabela ate APP_START + (otadata se OTA).
    nvs e phy ficam entre 0x9000 e 0x10000, ja dentro do APP_START."""
    # APP_START (0x10000) ja cobre bootloader+tabela+nvs+phy. otadata tambem
    # cabe nessa regiao no layout padrao; consideramos APP_START como overhead.
    return APP_START


def check_fits(size_label: str, variation: Dict[str, Any]) -> Result:
    """
    Valida que app(s) + fs + overhead cabem no flash. (True, info) ou (False, motivo).
    info = {flash, app, fs, ota, used, free}
    """
    flash = _flash_bytes(size_label)
    if flash <= 0:
        return (False, f"tamanho de flash invalido: '{size_label}'")
    app = _to_bytes(variation.get("app", "0"))
    fs = _to_bytes(variation.get("fs", "0"))
    ota = bool(variation.get("ota", False))
    if app < 0 or fs < 0:
        return (False, "tamanho de app ou fs invalido na variacao")

    app_total = app * 3 if ota else app  # factory + ota_0 + ota_1
    used = _fixed_overhead(ota) + app_total + fs
    if used > flash:
        return (False, f"a variacao '{variation.get('nome','?')}' nao cabe em "
                       f"{size_label}: usa {used} de {flash} bytes")
    return (True, {"flash": flash, "app": app, "fs": fs, "ota": ota,
                   "used": used, "free": flash - used})


def generate_csv(size_label: str, variation: Dict[str, Any],
                 fs_type: str = "littlefs") -> Result:
    """
    Gera o conteudo do partitions.csv para uma variacao. Offsets EM BRANCO
    (gen_esp32part.py alinha). (True, texto_csv) ou (False, motivo).

    fs_type: 'littlefs' ou 'fat' (so usado se a variacao tiver fs > 0).
    """
    fs_type = (fs_type or "littlefs").strip().lower()
    if fs_type not in ("littlefs", "fat"):
        return (False, "fs_type deve ser 'littlefs' ou 'fat'")

    ok, fit = check_fits(size_label, variation)
    if not ok:
        return (False, fit)

    app = variation.get("app", "0")
    fs = variation.get("fs", "0")
    ota = bool(variation.get("ota", False))
    has_fs = _to_bytes(fs) > 0

    lines: List[str] = []
    lines.append("# ESP Lab - tabela de particao gerada")
    lines.append(f"# Variacao: {variation.get('nome','?')} ({size_label})")
    lines.append("# Name, Type, SubType, Offset, Size, Flags")
    # particoes de dados fixas (offset em branco; tool alinha)
    lines.append("nvs,      data, nvs,     ,        0x6000,")
    lines.append("phy_init, data, phy,     ,        0x1000,")
    if ota:
        lines.append("otadata,  data, ota,     ,        0x2000,")
    # app(s)
    if ota:
        lines.append(f"factory,  app,  factory, ,        {app},")
        lines.append(f"ota_0,    app,  ota_0,   ,        {app},")
        lines.append(f"ota_1,    app,  ota_1,   ,        {app},")
    else:
        lines.append(f"factory,  app,  factory, ,        {app},")
    # filesystem (subtype conforme escolha)
    if has_fs:
        sub = "littlefs" if fs_type == "littlefs" else "fat"
        name = "storage"
        lines.append(f"{name},  data, {sub},  ,        {fs},")

    return (True, "\n".join(lines) + "\n")


def write_csv(project_dir: Path | str, size_label: str,
              variation: Dict[str, Any], fs_type: str = "littlefs") -> Result:
    """Gera e grava partitions.csv na raiz do projeto. (True, caminho)."""
    ok, csv = generate_csv(size_label, variation, fs_type)
    if not ok:
        return (False, csv)
    path = Path(project_dir).expanduser().resolve() / "partitions.csv"
    ok, res = _storage.atomic_write_text(path, csv)
    return (True, str(path)) if ok else (False, res)


__all__ = [
    "load_catalog", "list_sizes", "list_variations", "check_fits",
    "generate_csv", "write_csv", "catalog_path", "MAX_VARIATIONS",
]


def sanity_check(chip_flash: str, size_label: str) -> Result:
    """
    Sanidade Flash x particao (@E6-T6.5): compara flash real do chip com o
    tamanho do ramo de particao escolhido. (True, info) ou (False, motivo).

    chip_flash : flash lido do chip via chip_info (ex. "16MB").
    size_label : ramo escolhido no catalogo (ex. "4MB", "16MB").

    Regras:
      - chip < ramo  -> BLOQUEIA (particao maior que o flash fisico).
      - chip > ramo  -> AVISA (usando menos flash do que disponivel, ok).
      - chip == ramo -> OK.
      - Personalizada -> nao bloqueia, so avisa (responsabilidade do usuario).
    """
    if size_label == "Personalizada":
        return (True, {
            "status": "aviso",
            "message": "particao personalizada: validacao e responsabilidade do usuario",
        })

    # normaliza: chip_info retorna "16MB"; size_label do catalogo e "16MB"
    chip_norm = str(chip_flash).strip().upper().replace(" ", "")
    ramo_norm = str(size_label).strip().upper().replace(" ", "")

    chip_b = _flash_bytes(chip_norm)
    ramo_b = _flash_bytes(ramo_norm)

    if chip_b <= 0:
        return (False, f"flash do chip invalido ou desconhecido: '{chip_flash}'")
    if ramo_b <= 0:
        return (False, f"tamanho do ramo invalido: '{size_label}'")

    if chip_b < ramo_b:
        return (False,
                f"particao '{size_label}' exige mais flash do que o chip tem "
                f"({chip_flash}); gravacao bloqueada")
    if chip_b > ramo_b:
        return (True, {
            "status": "aviso",
            "message": (f"chip tem {chip_flash} mas ramo e '{size_label}'; "
                        f"flash subutilizado (ok, mas considere um ramo maior)"),
        })
    return (True, {"status": "ok", "message": "flash do chip confere com o ramo"})

#!/usr/bin/env python3
"""
Gerenciador do sdkconfig.defaults do projeto (@EC-T3b).

Porta de entrada UNICA para o sdkconfig.defaults na RAIZ do projeto
(nao o sdkconfig gerado pelo idf.py, nem os defaults dos exemplos do
ESP-IDF em /data/...). Este arquivo e a fonte de verdade das opcoes de
build configuraveis: o idf.py le ele e popula o sdkconfig no build
(mecanismo oficial Espressif — o build system nunca toca o .defaults,
so o consome).

Principios (definidos por Antonio):
  - UMA fonte de verdade: grava aqui, o build usa o que estiver ativo.
    Nada de duplicar em project_config.
  - Formato: UI mostra amigavel ("16MB", "QIO 80MHz"); o arquivo recebe
    a chave de chamada compativel (CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y).
  - Lista completa sempre; a checagem "a placa suporta?" e da funcao que
    executa (§6.8), nao daqui.
  - Edit cirurgico: trocar uma opcao preserva as demais linhas do arquivo;
    nunca reescreve tudo. Cria o arquivo se nao existir.

Formato do sdkconfig(.defaults): uma opcao por linha, CHAVE=VALOR.
Opcoes booleanas de escolha (choice) aparecem como CHAVE=y; as demais
alternativas da mesma escolha simplesmente NAO aparecem (ou como
'# CONFIG_X is not set'). Para um choice, garantir que so a alternativa
ativa fique com =y e as irmas sejam removidas.

Contrato: (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import storage as _storage

Result = Tuple[bool, Any]

DEFAULTS_FILENAME = "sdkconfig.defaults"

# ==========================================================
# MAPA amigavel <-> chaves CONFIG_* (choices do sdkconfig).
# Cada opcao de UI mapeia para um GRUPO de chaves irmas (a mesma escolha
# Kconfig), das quais exatamente uma fica ativa (=y). As chaves vem da
# doc oficial Espressif (kconfig-reference) e de sdkconfig real de projeto.
# ==========================================================

# --- Flash: Tamanho -------------------------------------------------------
# choice ESPTOOLPY_FLASHSIZE: uma familia, uma ativa.
_FLASH_SIZE_FAMILY = [
    "CONFIG_ESPTOOLPY_FLASHSIZE_1MB",
    "CONFIG_ESPTOOLPY_FLASHSIZE_2MB",
    "CONFIG_ESPTOOLPY_FLASHSIZE_4MB",
    "CONFIG_ESPTOOLPY_FLASHSIZE_8MB",
    "CONFIG_ESPTOOLPY_FLASHSIZE_16MB",
    "CONFIG_ESPTOOLPY_FLASHSIZE_32MB",
]
# UI (lista definida por Antonio) -> chave ativa desse grupo.
FLASH_SIZE_OPTIONS: List[str] = ["4MB", "8MB", "16MB", "32MB"]
_FLASH_SIZE_TO_KEY = {
    "4MB":  "CONFIG_ESPTOOLPY_FLASHSIZE_4MB",
    "8MB":  "CONFIG_ESPTOOLPY_FLASHSIZE_8MB",
    "16MB": "CONFIG_ESPTOOLPY_FLASHSIZE_16MB",
    "32MB": "CONFIG_ESPTOOLPY_FLASHSIZE_32MB",
}
FLASH_SIZE_DEFAULT = "4MB"  # default FUNCIONAL (nao placeholder)

# --- Flash: Modo (modo + frequencia combinados na UI) --------------------
# "Modo" na UI junta duas escolhas Kconfig: FLASHMODE (quad) e FLASHFREQ.
# OPI e caso especial: octal flash, ativado por OCT_FLASH.
_FLASH_MODE_FAMILY = [
    "CONFIG_ESPTOOLPY_FLASHMODE_QIO",
    "CONFIG_ESPTOOLPY_FLASHMODE_QOUT",
    "CONFIG_ESPTOOLPY_FLASHMODE_DIO",
    "CONFIG_ESPTOOLPY_FLASHMODE_DOUT",
]
_FLASH_FREQ_FAMILY = [
    "CONFIG_ESPTOOLPY_FLASHFREQ_120M",
    "CONFIG_ESPTOOLPY_FLASHFREQ_80M",
    "CONFIG_ESPTOOLPY_FLASHFREQ_40M",
    "CONFIG_ESPTOOLPY_FLASHFREQ_20M",
]
_FLASH_OCT_KEY = "CONFIG_ESPTOOLPY_OCT_FLASH"

# UI (lista definida por Antonio) -> conjunto de chaves a ativar.
FLASH_MODE_OPTIONS: List[str] = ["QIO 80MHz", "QIO 120MHz", "DIO 80MHz", "OPI 80MHz"]
_FLASH_MODE_TO_KEYS: Dict[str, Dict[str, Any]] = {
    "QIO 80MHz":  {"mode": "CONFIG_ESPTOOLPY_FLASHMODE_QIO",
                   "freq": "CONFIG_ESPTOOLPY_FLASHFREQ_80M", "oct": False},
    "QIO 120MHz": {"mode": "CONFIG_ESPTOOLPY_FLASHMODE_QIO",
                   "freq": "CONFIG_ESPTOOLPY_FLASHFREQ_120M", "oct": False},
    "DIO 80MHz":  {"mode": "CONFIG_ESPTOOLPY_FLASHMODE_DIO",
                   "freq": "CONFIG_ESPTOOLPY_FLASHFREQ_80M", "oct": False},
    "OPI 80MHz":  {"mode": "CONFIG_ESPTOOLPY_FLASHMODE_QIO",
                   "freq": "CONFIG_ESPTOOLPY_FLASHFREQ_80M", "oct": True},
}
FLASH_MODE_DEFAULT = "QIO 80MHz"  # default FUNCIONAL


def defaults_path(project_dir: Path | str) -> Path:
    """Caminho do sdkconfig.defaults na raiz do projeto."""
    return Path(project_dir).expanduser().resolve() / DEFAULTS_FILENAME


# ==========================================================
# LEITURA / ESCRITA CIRURGICA DE LINHAS
# ==========================================================

def _read_lines(project_dir: Path | str) -> List[str]:
    """Le as linhas do arquivo. Lista vazia se nao existir."""
    path = defaults_path(project_dir)
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _active_key_in_family(lines: List[str], family: List[str]) -> Optional[str]:
    """Retorna a chave da familia que esta ativa (=y) nas linhas, ou None."""
    ativos = set()
    for ln in lines:
        s = ln.strip()
        for key in family:
            if s == f"{key}=y":
                ativos.add(key)
    # Em choice bem-formado ha no maximo uma; se houver mais, retorna a 1a
    # na ordem da familia (deterministico).
    for key in family:
        if key in ativos:
            return key
    return None


def _set_choice(lines: List[str], family: List[str],
                ativa: str) -> List[str]:
    """
    Ativa 'ativa' (=y) e desativa as irmas da mesma familia, preservando
    todas as outras linhas do arquivo. Idempotente. 'ativa' deve pertencer
    a family.
    """
    irmas = set(family)
    saida = []
    ja_inserida = False
    for ln in lines:
        s = ln.strip()
        # Remove qualquer linha (ativa ou '# ... is not set') das irmas.
        pertence = False
        for key in irmas:
            if s == f"{key}=y" or s == f"# {key} is not set":
                pertence = True
                break
        if pertence:
            # Substitui a primeira ocorrencia relevante pela ativa; descarta
            # as demais.
            if not ja_inserida:
                saida.append(f"{ativa}=y")
                ja_inserida = True
            continue
        saida.append(ln)
    if not ja_inserida:
        saida.append(f"{ativa}=y")
    return saida


def _set_bool(lines: List[str], key: str, value: bool) -> List[str]:
    """Ativa (=y) ou desativa (remove/comenta) uma chave booleana avulsa."""
    saida = []
    tratada = False
    for ln in lines:
        s = ln.strip()
        if s == f"{key}=y" or s == f"# {key} is not set":
            if not tratada:
                saida.append(f"{key}=y" if value else f"# {key} is not set")
                tratada = True
            continue
        saida.append(ln)
    if not tratada:
        saida.append(f"{key}=y" if value else f"# {key} is not set")
    return saida


def _write_lines(project_dir: Path | str, lines: List[str]) -> Result:
    """Grava as linhas de volta, atomicamente."""
    texto = "\n".join(lines)
    if not texto.endswith("\n"):
        texto += "\n"
    return _storage.atomic_write_text(defaults_path(project_dir), texto)


# ==========================================================
# FLASH SIZE
# ==========================================================

def get_flash_size(project_dir: Path | str) -> str:
    """Tamanho ativo (amigavel). Default FUNCIONAL se ausente/desconhecido."""
    lines = _read_lines(project_dir)
    key = _active_key_in_family(lines, _FLASH_SIZE_FAMILY)
    if key:
        for amigavel, k in _FLASH_SIZE_TO_KEY.items():
            if k == key:
                return amigavel
        # ativo, mas fora da lista de UI (ex.: 1MB/2MB) — mostra a chave crua
        m = re.search(r"FLASHSIZE_(\w+)$", key)
        if m:
            return m.group(1)
    return FLASH_SIZE_DEFAULT


def set_flash_size(project_dir: Path | str, amigavel: str) -> Result:
    """Grava o tamanho (recebe amigavel, ex '16MB'). Cria arquivo se preciso."""
    if amigavel not in _FLASH_SIZE_TO_KEY:
        return (False, f"tamanho invalido: '{amigavel}'; opcoes: "
                       f"{FLASH_SIZE_OPTIONS}")
    lines = _read_lines(project_dir)
    lines = _set_choice(lines, _FLASH_SIZE_FAMILY, _FLASH_SIZE_TO_KEY[amigavel])
    ok, res = _write_lines(project_dir, lines)
    return (True, amigavel) if ok else (False, res)


# ==========================================================
# FLASH MODE (modo + freq combinados; OPI = octal)
# ==========================================================

def get_flash_mode(project_dir: Path | str) -> str:
    """Modo ativo (amigavel, ex 'QIO 80MHz'). Default FUNCIONAL se ausente."""
    lines = _read_lines(project_dir)
    mode_key = _active_key_in_family(lines, _FLASH_MODE_FAMILY)
    freq_key = _active_key_in_family(lines, _FLASH_FREQ_FAMILY)
    oct_on = any(ln.strip() == f"{_FLASH_OCT_KEY}=y" for ln in lines)
    # Tenta casar com uma opcao de UI conhecida.
    for amigavel, spec in _FLASH_MODE_TO_KEYS.items():
        if (spec["mode"] == mode_key and spec["freq"] == freq_key
                and bool(spec["oct"]) == oct_on):
            return amigavel
    return FLASH_MODE_DEFAULT


def set_flash_mode(project_dir: Path | str, amigavel: str) -> Result:
    """Grava o modo (recebe amigavel, ex 'QIO 80MHz'). Ativa modo+freq(+oct)."""
    spec = _FLASH_MODE_TO_KEYS.get(amigavel)
    if spec is None:
        return (False, f"modo invalido: '{amigavel}'; opcoes: {FLASH_MODE_OPTIONS}")
    lines = _read_lines(project_dir)
    lines = _set_choice(lines, _FLASH_MODE_FAMILY, spec["mode"])
    lines = _set_choice(lines, _FLASH_FREQ_FAMILY, spec["freq"])
    lines = _set_bool(lines, _FLASH_OCT_KEY, bool(spec["oct"]))
    ok, res = _write_lines(project_dir, lines)
    return (True, amigavel) if ok else (False, res)


# ==========================================================
# PSRAM (Adendo 5: Desabilitada / QSPI / OPI — so "Modo").
# Chaves (doc oficial Espressif, S3):
#   Desabilitada -> CONFIG_SPIRAM ausente/not set
#   QSPI         -> CONFIG_SPIRAM=y + CONFIG_SPIRAM_MODE_QUAD=y
#   OPI          -> CONFIG_SPIRAM=y + CONFIG_SPIRAM_MODE_OCT=y
# Nao ha "tamanho" de PSRAM no sdkconfig (auto-detectado pelo IDF).
# ==========================================================

_SPIRAM_KEY = "CONFIG_SPIRAM"
_SPIRAM_MODE_FAMILY = [
    "CONFIG_SPIRAM_MODE_QUAD",
    "CONFIG_SPIRAM_MODE_OCT",
]

PSRAM_MODE_OPTIONS = ["Desabilitada", "QSPI", "OPI"]
PSRAM_MODE_DEFAULT = "Desabilitada"  # default FUNCIONAL (sem PSRAM e valido)

_PSRAM_TO_KEYS = {
    "QSPI": "CONFIG_SPIRAM_MODE_QUAD",
    "OPI":  "CONFIG_SPIRAM_MODE_OCT",
}


def get_psram_mode(project_dir: Path | str) -> str:
    """Modo PSRAM ativo (amigavel). Default FUNCIONAL (Desabilitada) se ausente."""
    lines = _read_lines(project_dir)
    spiram_on = any(ln.strip() == f"{_SPIRAM_KEY}=y" for ln in lines)
    if not spiram_on:
        return "Desabilitada"
    mode_key = _active_key_in_family(lines, _SPIRAM_MODE_FAMILY)
    for amigavel, k in _PSRAM_TO_KEYS.items():
        if k == mode_key:
            return amigavel
    # SPIRAM ligado mas modo indefinido: assume QSPI (quad e o padrao IDF).
    return "QSPI"


def set_psram_mode(project_dir: Path | str, amigavel: str) -> Result:
    """Grava o modo PSRAM. Desabilitada desliga SPIRAM; QSPI/OPI ligam + modo."""
    if amigavel not in PSRAM_MODE_OPTIONS:
        return (False, f"modo PSRAM invalido: '{amigavel}'; opcoes: "
                       f"{PSRAM_MODE_OPTIONS}")
    lines = _read_lines(project_dir)
    if amigavel == "Desabilitada":
        # Desliga SPIRAM e remove as chaves de modo (nao fazem sentido sem PSRAM).
        lines = _set_bool(lines, _SPIRAM_KEY, False)
        # Remove as linhas de modo (ativas ou 'is not set') sem deixar orfas.
        irmas = set(_SPIRAM_MODE_FAMILY)
        lines = [ln for ln in lines
                 if ln.strip() not in
                 {f"{k}=y" for k in irmas} | {f"# {k} is not set" for k in irmas}]
    else:
        lines = _set_bool(lines, _SPIRAM_KEY, True)
        lines = _set_choice(lines, _SPIRAM_MODE_FAMILY, _PSRAM_TO_KEYS[amigavel])
    ok, res = _write_lines(project_dir, lines)
    return (True, amigavel) if ok else (False, res)


# ==========================================================
# PARTICAO: chave + arquivo real (partitions.csv), nao so uma chave.
# Chaves confirmadas em exemplos oficiais/issues Espressif:
#   CONFIG_PARTITION_TABLE_CUSTOM=y
#   CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
#   CONFIG_PARTITION_TABLE_FILENAME="partitions.csv"
# "Ativo" e lido do comentario que partition_tables.generate_csv() ja
# grava no arquivo ("# Variacao: NOME (TAMANHO)") — sem inventar outro
# lugar de estado. Dependencia: a lista de esquemas vem do Flash>Tamanho
# ja configurado (get_flash_size), nao e independente.
# ==========================================================

_PARTITION_TYPE_FAMILY = [
    "CONFIG_PARTITION_TABLE_SINGLE_APP",
    "CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE",
    "CONFIG_PARTITION_TABLE_TWO_OTA",
    "CONFIG_PARTITION_TABLE_CUSTOM",
]
_PARTITION_CUSTOM_FILENAME_KEY = "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME"
_PARTITION_FILENAME_KEY = "CONFIG_PARTITION_TABLE_FILENAME"
PARTITION_CSV_NAME = "partitions.csv"

# Default FUNCIONAL (nunca fallback vazio) quando o catalogo nao tem
# variacao pro tamanho: esquema fixo conhecido-bom, cabe em qualquer
# flash >= 2MB.
PARTITION_FALLBACK_VARIATION = {
    "nome": "default (single app, sem OTA)",
    "app": "1500K", "fs": "0", "ota": False,
}


def _set_string(lines: List[str], key: str, value: str) -> List[str]:
    """Seta uma chave de valor string (KEY="valor"), unica ocorrencia,
    preservando as demais linhas."""
    saida = []
    tratada = False
    alvo = f'{key}="{value}"'
    for ln in lines:
        s = ln.strip()
        if s.startswith(f"{key}="):
            if not tratada:
                saida.append(alvo)
                tratada = True
            continue
        saida.append(ln)
    if not tratada:
        saida.append(alvo)
    return saida


def get_partition_scheme_info(project_dir: Path | str):
    """
    Retorna (nome, tamanho) do esquema ativo, parseados do comentario do
    partitions.csv ("# Variacao: NOME (TAMANHO)"). (None, None) se
    ausente/nao-parseavel.

    Existe separado de get_partition_scheme_name porque o catalogo real
    de Antonio repete nomes de variacao entre tamanhos diferentes (ex.:
    "Padrao" existe em 4MB, 8MB, 16MB e 32MB) — comparar so pelo nome
    marcaria falso-positivo no submenu de tamanho errado (@EC-T3b-Particao,
    4 subitens fixos). Quem consome deve comparar nome E tamanho.
    """
    root = Path(project_dir).expanduser().resolve()
    csv_path = root / PARTITION_CSV_NAME
    if csv_path.is_file():
        try:
            for ln in csv_path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^#\s*Variacao:\s*(.+)\s\((\w+)\)\s*$", ln)
                if m:
                    return m.group(1).strip(), m.group(2).strip()
        except Exception:
            pass
    return None, None


def get_partition_scheme_name(project_dir: Path | str) -> str:
    """
    Nome do esquema ativo (qualquer tamanho). Default FUNCIONAL se
    ausente/nao-parseavel — nunca vazio. Uso simples de exibicao geral;
    para marcar ► num submenu de tamanho fixo, use get_partition_scheme_info
    e compare nome E tamanho.
    """
    nome, _tamanho = get_partition_scheme_info(project_dir)
    return nome or PARTITION_FALLBACK_VARIATION["nome"]


def set_partition_scheme(project_dir: Path | str, size_label: str,
                         variation: Dict[str, Any],
                         fs_type: str = "littlefs") -> Result:
    """
    Gera partitions.csv (partition_tables.write_csv — ja valida check_fits)
    e ativa CUSTOM no sdkconfig.defaults apontando pra ele. Import tardio
    de hardware.partition_tables (evita import circular, so usado aqui).
    """
    from ..hardware import partition_tables as _pt
    ok, res = _pt.write_csv(project_dir, size_label, variation, fs_type)
    if not ok:
        return (False, res)

    lines = _read_lines(project_dir)
    lines = _set_choice(lines, _PARTITION_TYPE_FAMILY,
                        "CONFIG_PARTITION_TABLE_CUSTOM")
    lines = _set_string(lines, _PARTITION_CUSTOM_FILENAME_KEY, PARTITION_CSV_NAME)
    lines = _set_string(lines, _PARTITION_FILENAME_KEY, PARTITION_CSV_NAME)
    ok2, res2 = _write_lines(project_dir, lines)
    return (True, variation.get("nome", "?")) if ok2 else (False, res2)


# ==========================================================
# DEPURACAO (nivel de log). Choice simples, como Flash size.
# Chaves confirmadas na doc oficial Espressif (log.html) e no enum
# esp_log_level_t (esp_log_level.h): NONE/ERROR/WARN/INFO/DEBUG/VERBOSE.
# Mesmas 6 opcoes ja usadas em hardware/port_config.DEPLOY_OPTIONS
# ["debug_level"] — nao importado daqui de proposito (evita 2a dependencia
# programming->hardware; lista estatica de 6 strings nao justifica o
# acoplamento).
# ==========================================================

_LOG_LEVEL_FAMILY = [
    "CONFIG_LOG_DEFAULT_LEVEL_NONE",
    "CONFIG_LOG_DEFAULT_LEVEL_ERROR",
    "CONFIG_LOG_DEFAULT_LEVEL_WARN",
    "CONFIG_LOG_DEFAULT_LEVEL_INFO",
    "CONFIG_LOG_DEFAULT_LEVEL_DEBUG",
    "CONFIG_LOG_DEFAULT_LEVEL_VERBOSE",
]
LOG_LEVEL_OPTIONS = ["Nenhum", "Erro", "Aviso", "Info", "Debug", "Verbose"]
LOG_LEVEL_DEFAULT = "Info"  # default FUNCIONAL: default de fabrica do ESP-IDF
_LOG_LEVEL_TO_KEY = dict(zip(LOG_LEVEL_OPTIONS, _LOG_LEVEL_FAMILY))


def get_log_level(project_dir: Path | str) -> str:
    """Nivel de log ativo (amigavel). Default FUNCIONAL (Info) se ausente."""
    lines = _read_lines(project_dir)
    key = _active_key_in_family(lines, _LOG_LEVEL_FAMILY)
    if key:
        for amigavel, k in _LOG_LEVEL_TO_KEY.items():
            if k == key:
                return amigavel
    return LOG_LEVEL_DEFAULT


def set_log_level(project_dir: Path | str, amigavel: str) -> Result:
    """Grava o nivel de log (recebe amigavel, ex 'Debug')."""
    if amigavel not in _LOG_LEVEL_TO_KEY:
        return (False, f"nivel invalido: '{amigavel}'; opcoes: {LOG_LEVEL_OPTIONS}")
    lines = _read_lines(project_dir)
    lines = _set_choice(lines, _LOG_LEVEL_FAMILY, _LOG_LEVEL_TO_KEY[amigavel])
    ok, res = _write_lines(project_dir, lines)
    return (True, amigavel) if ok else (False, res)


# ==========================================================
# CPU (frequencia). Choice + chave companheira INTEIRA (nao string, nao
# booleana -- tipo novo no modulo). Chaves confirmadas em sdkconfig real
# (issue Espressif/sysprogs) e doc oficial (esp32s3: 80/160/240MHz):
#   CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_80/_160/_240=y  (choice)
#   CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ=<numero>         (precisa bater com a
#   escolha do choice -- o proprio IDF grava as duas juntas no sdkconfig
#   real, entao o sdkconfig.defaults tambem precisa das duas).
# ==========================================================

_CPU_FREQ_FAMILY = [
    "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_80",
    "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_160",
    "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240",
]
_CPU_FREQ_VALUE_KEY = "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ"

CPU_FREQ_OPTIONS = ["80MHz", "160MHz", "240MHz"]
CPU_FREQ_DEFAULT = "240MHz"  # default FUNCIONAL (maximo, tipico em dev boards)
_CPU_FREQ_TO_KEY = {
    "80MHz":  "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_80",
    "160MHz": "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_160",
    "240MHz": "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240",
}


def _set_int(lines: List[str], key: str, value) -> List[str]:
    """Seta uma chave de valor inteiro (KEY=N, sem aspas), unica ocorrencia,
    preservando as demais linhas."""
    saida = []
    tratada = False
    alvo = f"{key}={value}"
    for ln in lines:
        s = ln.strip()
        if s.startswith(f"{key}="):
            if not tratada:
                saida.append(alvo)
                tratada = True
            continue
        saida.append(ln)
    if not tratada:
        saida.append(alvo)
    return saida


def get_cpu_freq(project_dir: Path | str) -> str:
    """Frequencia de CPU ativa (amigavel). Default FUNCIONAL se ausente."""
    lines = _read_lines(project_dir)
    key = _active_key_in_family(lines, _CPU_FREQ_FAMILY)
    if key:
        for amigavel, k in _CPU_FREQ_TO_KEY.items():
            if k == key:
                return amigavel
    return CPU_FREQ_DEFAULT


def set_cpu_freq(project_dir: Path | str, amigavel: str) -> Result:
    """Grava a frequencia (recebe amigavel, ex '240MHz'). Ativa o choice
    E a chave companheira inteira, sincronizadas."""
    if amigavel not in _CPU_FREQ_TO_KEY:
        return (False, f"frequencia invalida: '{amigavel}'; opcoes: {CPU_FREQ_OPTIONS}")
    lines = _read_lines(project_dir)
    lines = _set_choice(lines, _CPU_FREQ_FAMILY, _CPU_FREQ_TO_KEY[amigavel])
    numero = amigavel.replace("MHz", "").strip()
    lines = _set_int(lines, _CPU_FREQ_VALUE_KEY, numero)
    ok, res = _write_lines(project_dir, lines)
    return (True, amigavel) if ok else (False, res)


__all__ = [
    "defaults_path",
    "get_flash_size", "set_flash_size",
    "get_flash_mode", "set_flash_mode",
    "FLASH_SIZE_OPTIONS", "FLASH_SIZE_DEFAULT",
    "FLASH_MODE_OPTIONS", "FLASH_MODE_DEFAULT",
    "get_psram_mode", "set_psram_mode",
    "PSRAM_MODE_OPTIONS", "PSRAM_MODE_DEFAULT",
    "get_partition_scheme_name", "get_partition_scheme_info", "set_partition_scheme",
    "get_log_level", "set_log_level",
    "LOG_LEVEL_OPTIONS", "LOG_LEVEL_DEFAULT",
    "get_cpu_freq", "set_cpu_freq",
    "CPU_FREQ_OPTIONS", "CPU_FREQ_DEFAULT",
    "PARTITION_CSV_NAME", "PARTITION_FALLBACK_VARIATION",
    "DEFAULTS_FILENAME",
]

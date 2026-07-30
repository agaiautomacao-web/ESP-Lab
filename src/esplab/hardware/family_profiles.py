#!/usr/bin/env python3
"""Perfis-base oficiais por família/chip.

Família do SoC, placa física e perfil por MAC são camadas distintas.
Um layout de placa de referência nunca prova o modelo do hardware conectado.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List

PROFILE_SCHEMA_VERSION = 4

PROFILE_READINESS_READY = "ready"
PROFILE_READINESS_INCOMPLETE = "incomplete"
PROFILE_READINESS_STATUSES = {
    PROFILE_READINESS_READY,
    PROFILE_READINESS_INCOMPLETE,
}

LAYOUT_REVIEW_PENDING = "pending"
LAYOUT_REVIEW_CONFIRMED = "confirmed"
LAYOUT_REVIEW_NOT_DEFINED = "not_defined"
LAYOUT_REVIEW_STATUSES = {
    LAYOUT_REVIEW_PENDING,
    LAYOUT_REVIEW_CONFIRMED,
    LAYOUT_REVIEW_NOT_DEFINED,
}
LAYOUT_CONTENT_FIELDS = frozenset({
    "total_pins", "pinout_mapping", "usb_port_count", "usb_ports",
})
UNKNOWN = "Desconhecido"
NONE_VAL = "Nenhum"



def normalize_family(value: Any) -> str:
    """
    Normaliza família sem confundir variante/modelo com target.

    Exemplos:
      ESP32-D0WD-V3 -> ESP32
      ESP32-S3      -> ESP32-S3
      ESP32-P4      -> ESP32-P4
    """
    raw = str(value or "").strip().upper().replace("_", "-").replace(" ", "")
    aliases = {
        "ESP32S2": "ESP32-S2", "ESP32S3": "ESP32-S3",
        "ESP32C2": "ESP32-C2", "ESP32C3": "ESP32-C3",
        "ESP32C5": "ESP32-C5", "ESP32C6": "ESP32-C6",
        "ESP32C61": "ESP32-C61", "ESP32H2": "ESP32-H2",
        "ESP32P4": "ESP32-P4",
    }
    raw = aliases.get(raw, raw)
    if not raw:
        return UNKNOWN
    for family in (
        "ESP32-C61", "ESP32-S2", "ESP32-S3", "ESP32-C2",
        "ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-H2",
        "ESP32-P4",
    ):
        if raw == family or raw.startswith(family):
            return family
    if raw == "ESP32" or raw.startswith("ESP32-"):
        return "ESP32"
    return raw


def target_for_family(value: Any) -> str:
    family = normalize_family(value)
    return "" if family == UNKNOWN else family.lower().replace("-", "")


def _pin(gpio, label, category="gpio", functions=None, note=""):
    return {
        "gpio": gpio, "label": label, "category": category,
        "functions": list(functions or []), "note": note,
    }


def _two_rows(left, right):
    if len(left) != len(right):
        raise ValueError("layout precisa ter duas fileiras simétricas")
    total = len(left) * 2
    result = []
    for number, pin in enumerate(left, 1):
        item = deepcopy(pin)
        item.update({"physical": number, "side": "left"})
        result.append(item)
    for index, pin in enumerate(right):
        item = deepcopy(pin)
        item.update({"physical": total - index, "side": "right"})
        result.append(item)
    return result


def _s3_functions(gpio):
    if gpio is None:
        return []
    result = {"A"}
    if 1 <= gpio <= 20:
        result.add("B")
    if 1 <= gpio <= 14:
        result.add("C")
    if gpio in (43, 44):
        result.add("E")
    if gpio in (19, 20):
        result.add("F")
    if gpio in (0, 3, 45, 46):
        result.add("G")
    if 35 <= gpio <= 37:
        result.add("H")
    return sorted(result)


def _esp32_functions(gpio):
    if gpio is None:
        return []
    result = {"A"}
    if gpio in {0,2,4,12,13,14,15,25,26,27,32,33,34,35,36,39}:
        result.add("B")
    if gpio in {0,2,4,12,13,14,15,27,32,33}:
        result.add("C")
    if gpio in (1, 3):
        result.add("E")
    if gpio in (0, 2, 5, 12, 15):
        result.add("G")
    return sorted(result)


def _s3_devkitc_v11():
    # ESP32-S3-DevKitC-1 v1.1: tabelas oficiais J1/J3.
    L = [
        _pin(None,"3V3","power"), _pin(None,"3V3","power"),
        _pin(None,"RST","control"),
        *[_pin(g,f"GPIO{g}","gpio",_s3_functions(g)) for g in (4,5,6,7,15,16,17,18,8)],
        _pin(3,"GPIO3","strapping",_s3_functions(3)),
        _pin(46,"GPIO46","strapping",_s3_functions(46)),
        *[_pin(g,f"GPIO{g}","gpio",_s3_functions(g)) for g in (9,10,11,12,13,14)],
        _pin(None,"5V0","power"), _pin(None,"GND","power"),
    ]
    R = [
        _pin(None,"GND","power"),
        _pin(43,"GPIO43/TX","uart",_s3_functions(43)),
        _pin(44,"GPIO44/RX","uart",_s3_functions(44)),
        *[_pin(g,f"GPIO{g}","gpio",_s3_functions(g)) for g in (1,2,42,41,40,39,38)],
        *[_pin(g,f"GPIO{g}","octal",_s3_functions(g)) for g in (37,36,35)],
        _pin(0,"GPIO0","strapping",_s3_functions(0)),
        _pin(45,"GPIO45","strapping",_s3_functions(45)),
        *[_pin(g,f"GPIO{g}","gpio",_s3_functions(g)) for g in (48,47,21)],
        _pin(20,"GPIO20/D+","usb",_s3_functions(20)),
        _pin(19,"GPIO19/D-","usb",_s3_functions(19)),
        _pin(None,"GND","power"), _pin(None,"GND","power"),
    ]
    return {
        "reference_board_name": "ESP32-S3-DevKitC-1 v1.1",
        "total_pins": 44,
        "pinout_mapping": _two_rows(L, R),
        "usb_port_count": 2,
        "usb_ports": [
            {"nome":"USB-to-UART","type":"usb_uart","gpios":[43,44]},
            {"nome":"USB nativo","type":"usb_otg_jtag","gpios":[19,20]},
        ],
        "layout_source_document": "ESP32-S3-DevKitC-1 v1.1 User Guide",
        "layout_source_revision": "v1.1",
        "layout_source_url": (
            "https://docs.espressif.com/projects/esp-dev-kits/en/latest/"
            "esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html"
        ),
        "layout_notes": [
            "GPIO35 a GPIO37 podem estar ocupados por flash/PSRAM octal.",
            "Layout de referência Espressif; confirmar o modelo físico.",
        ],
    }


def _esp32_devkitc_v4():
    # ESP32-DevKitC V4: tabelas oficiais J2/J3.
    flash_note = "Usado internamente pela memória SPI nesta referência."
    L = [
        _pin(None,"3V3","power"), _pin(None,"EN","control"),
        *[_pin(g,f"GPIO{g}","input",_esp32_functions(g)) for g in (36,39,34,35)],
        *[_pin(g,f"GPIO{g}","gpio",_esp32_functions(g)) for g in (32,33,25,26,27,14)],
        _pin(12,"GPIO12","strapping",_esp32_functions(12)),
        _pin(None,"GND","power"), _pin(13,"GPIO13","gpio",_esp32_functions(13)),
        *[_pin(g,f"GPIO{g}*","internal_flash",_esp32_functions(g),flash_note) for g in (9,10,11)],
        _pin(None,"5V0","power"),
    ]
    R = [
        _pin(None,"GND","power"),
        *[_pin(g,f"GPIO{g}","gpio",_esp32_functions(g)) for g in (23,22)],
        _pin(1,"GPIO1/TX","uart",_esp32_functions(1)),
        _pin(3,"GPIO3/RX","uart",_esp32_functions(3)),
        _pin(21,"GPIO21","gpio",_esp32_functions(21)), _pin(None,"GND","power"),
        *[_pin(g,f"GPIO{g}","gpio",_esp32_functions(g)) for g in (19,18)],
        _pin(5,"GPIO5","strapping",_esp32_functions(5)),
        *[_pin(g,f"GPIO{g}","gpio",_esp32_functions(g)) for g in (17,16,4)],
        *[_pin(g,f"GPIO{g}","strapping",_esp32_functions(g)) for g in (0,2,15)],
        *[_pin(g,f"GPIO{g}*","internal_flash",_esp32_functions(g),flash_note) for g in (8,7,6)],
    ]
    return {
        "reference_board_name": "ESP32-DevKitC V4",
        "total_pins": 38,
        "pinout_mapping": _two_rows(L, R),
        "usb_port_count": 1,
        "usb_ports": [{"nome":"USB-to-UART","type":"usb_uart","gpios":[1,3]}],
        "layout_source_document": "ESP32-DevKitC V4 User Guide",
        "layout_source_revision": "latest",
        "layout_source_url": (
            "https://docs.espressif.com/projects/esp-dev-kits/en/latest/"
            "esp32/esp32-devkitc/user_guide.html"
        ),
        "layout_notes": [
            "GPIO6 a GPIO11 são usados internamente pela memória SPI.",
            "Layout de referência Espressif; confirmar o modelo físico.",
        ],
    }


# gpio_count é quantidade de GPIOs físicos do SoC, não pinos de header.
FAMILY_CATALOG = {
    "ESP32":    (34, "esp32",   _esp32_devkitc_v4),
    "ESP32-S2": (43, "esp32s2", None),
    "ESP32-S3": (45, "esp32s3", _s3_devkitc_v11),
    "ESP32-C2": (21, "esp32c2", None),
    "ESP32-C3": (22, "esp32c3", None),
    "ESP32-C5": (29, "esp32c5", None),
    "ESP32-C6": (31, "esp32c6", None),
    "ESP32-C61":(30, "esp32c61",None),
    "ESP32-H2": (28, "esp32h2", None),
    "ESP32-P4": (55, "esp32p4", None),
}


def get_family_metadata(value):
    family = normalize_family(value)
    entry = FAMILY_CATALOG.get(family)
    if not entry:
        return {"family":family, "target":target_for_family(family),
                "gpio_count":None, "known":False, "source_url":""}
    gpio_count, target, _ = entry
    return {
        "family": family, "target": target, "gpio_count": gpio_count,
        "known": True,
        "source_document": "ESP-IDF GPIO API Reference",
        "source_revision": "stable",
        "source_url": (
            "https://docs.espressif.com/projects/esp-idf/en/stable/"
            f"{target}/api-reference/peripherals/gpio.html"
        ),
    }


def _value(data, *keys, default=UNKNOWN):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def get_reference_layout(value):
    """Retorna referência opcional; nunca é aplicada automaticamente."""
    family = normalize_family(value)
    factory = FAMILY_CATALOG.get(family, (None, None, None))[2]
    if not callable(factory):
        return (
            False,
            f"nenhum layout físico oficial foi embarcado para {family}",
        )
    return (True, deepcopy(factory()))


def has_layout_content(profile):
    """Informa se o perfil contém alguma geometria ou conector físico."""
    if not isinstance(profile, dict):
        return False
    total = profile.get("total_pins", 0)
    pinout = profile.get("pinout_mapping")
    ports = profile.get("usb_ports")
    count = profile.get("usb_port_count", 0)
    return bool(
        (isinstance(total, int) and not isinstance(total, bool) and total > 0)
        or (isinstance(pinout, list) and pinout)
        or (isinstance(ports, list) and ports)
        or (isinstance(count, int) and not isinstance(count, bool) and count > 0)
    )

def build_neutral_default():
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "mac": "default",
        "board_name": "Perfil reservado (não usado para novos cadastros)",
        "profile_confirmed": False,
        "profile_ready": False,
        "profile_readiness_status": PROFILE_READINESS_INCOMPLETE,
        "profile_readiness_reasons": ["registro reservado"],
        "chip_type": UNKNOWN,
        "chip_family": UNKNOWN,
        "chip_variant": UNKNOWN,
        "package_variant": UNKNOWN,
        "target": "",
        "chip_revision": UNKNOWN,
        "flash_size_mb": UNKNOWN,
        "psram_enabled": UNKNOWN,
        "features": UNKNOWN,
        "usb_mode": UNKNOWN,
        "crystal": UNKNOWN,
        "flash_manufacturer": UNKNOWN,
        "flash_device": UNKNOWN,
        "partition_table": NONE_VAL,
        "chip_gpio_count": None,
        "total_pins": 0,
        "pinout_mapping": [],
        "usb_port_count": 0,
        "usb_ports": [],
        "source_type": "reserved_default",
        "source_family": "",
        "source_document": "",
        "source_revision": "",
        "source_url": "",
        "reference_board_name": "",
        "layout_source_type": "none",
        "layout_source_document": "",
        "layout_source_revision": "",
        "layout_source_url": "",
        "layout_notes": [],
        "layout_review_status": LAYOUT_REVIEW_NOT_DEFINED,
        "layout_review_required": False,
        "layout_review_reasons": [],
        "layout_reviewed_at": "",
        "layout_reviewed_by": "",
        "layout_review_note": "",
    }


def build_family_profile(chip_info=None):
    """
    Cria o perfil físico por MAC somente com dados verificáveis do SoC.

    O esptool identifica o chip, mas não identifica o modelo da placa nem a
    quantidade de posições dos headers do fabricante. Por isso, novos perfis
    sempre nascem sem geometria física. Um layout oficial de referência pode
    ser aplicado depois, por ação explícita, quando o usuário souber que a
    placa corresponde exatamente àquele modelo Espressif.
    """
    data = dict(chip_info or {})
    family = normalize_family(_value(data, "chip_family", "family", "chip_type"))
    meta = get_family_metadata(family)
    profile = {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "mac": str(data.get("mac") or ""),
        "board_name": f"Nova placa ({family})",
        "profile_confirmed": False,
        "profile_ready": False,
        "profile_readiness_status": PROFILE_READINESS_INCOMPLETE,
        "profile_readiness_reasons": [],
        "chip_type": _value(data, "chip_type", default=family),
        "chip_family": family,
        "chip_variant": _value(data, "chip_variant", "variant"),
        "package_variant": _value(data, "package_variant", "package"),
        "target": meta.get("target") or "",
        "chip_revision": _value(data, "chip_revision", "revision"),
        "flash_size_mb": _value(data, "flash_size", "flash_size_mb"),
        "psram_enabled": _value(
            data, "psram", "psram_enabled", default=NONE_VAL
        ),
        "features": _value(data, "features"),
        "usb_mode": _value(data, "usb_mode"),
        "crystal": _value(data, "crystal"),
        "flash_manufacturer": _value(data, "flash_manufacturer"),
        "flash_device": _value(data, "flash_device"),
        "partition_table": NONE_VAL,
        "chip_gpio_count": meta.get("gpio_count"),
        "total_pins": 0,
        "pinout_mapping": [],
        "usb_port_count": 0,
        "usb_ports": [],
        "source_type": "espressif_family_reference",
        "source_family": family,
        "source_document": meta.get("source_document") or "",
        "source_revision": meta.get("source_revision") or "",
        "source_url": meta.get("source_url") or "",
        "reference_board_name": "",
        "layout_source_type": "undefined",
        "layout_source_document": "",
        "layout_source_revision": "",
        "layout_source_url": "",
        "layout_notes": [],
        "layout_review_status": LAYOUT_REVIEW_NOT_DEFINED,
        "layout_review_required": False,
        "layout_review_reasons": [],
        "layout_reviewed_at": "",
        "layout_reviewed_by": "",
        "layout_review_note": (
            "Layout físico ainda não informado pelo usuário."
        ),
    }
    return normalize_profile(profile)


def audit_profile(profile):
    """Retorna somente inconsistências estruturais; nunca altera o perfil."""
    reasons = []
    family = normalize_family(profile.get("chip_family"))
    pinout = profile.get("pinout_mapping")
    if not isinstance(pinout, list):
        return ["pinout_mapping não é uma lista"]

    total = profile.get("total_pins", 0)
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        reasons.append("total_pins inválido")
        total = 0
    elif total and total % 2:
        reasons.append("total_pins ímpar")

    physical = [
        pin.get("physical") for pin in pinout if isinstance(pin, dict)
    ]
    if len(physical) != len(pinout):
        reasons.append("pinout_mapping contém item inválido")
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in physical
    ):
        reasons.append("há posição física inválida")
    valid = [
        value for value in physical
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    if len(set(valid)) != len(valid):
        reasons.append("há números físicos duplicados")
    if total and any(value < 1 or value > total for value in valid):
        reasons.append("há número físico fora do intervalo")
    if not total and pinout:
        reasons.append("há pinagem cadastrada com total_pins igual a zero")

    ports = profile.get("usb_ports", [])
    count = profile.get(
        "usb_port_count", len(ports) if isinstance(ports, list) else 0
    )
    if not isinstance(ports, list):
        reasons.append("usb_ports não é uma lista")
        ports = []
    if not isinstance(count, int) or isinstance(count, bool):
        reasons.append("usb_port_count inválido")
    else:
        if count != len(ports):
            reasons.append("usb_port_count diverge de usb_ports")
        if count < 0 or count > 2:
            reasons.append("renderizador suporta de 0 a 2 portas USB")
        if not total and count:
            reasons.append("há porta USB cadastrada sem layout físico")

    gpios = {
        pin.get("gpio") for pin in pinout if isinstance(pin, dict)
    }
    if family not in ("ESP32-S3", UNKNOWN) and {46, 47, 48}.issubset(gpios):
        reasons.append(
            "possível herança indevida do antigo layout ESP32-S3"
        )
    return list(dict.fromkeys(reasons))


def _valid_physical_mac(value: Any) -> bool:
    """Aceita somente MAC físico canônico de 6 octetos."""
    text = str(value or "").strip().lower()
    return bool(re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", text))


def evaluate_profile_readiness(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deriva a prontidão operacional do perfil sem persistir nada.

    Pinagem física é opcional: `not_defined` com geometria vazia é um estado
    pronto e deliberado. `pending`, inconsistência estrutural, identidade
    inválida ou família/target desconhecidos deixam o perfil incompleto.
    """
    if not isinstance(profile, dict):
        return {
            "profile_ready": False,
            "profile_readiness_status": PROFILE_READINESS_INCOMPLETE,
            "profile_readiness_reasons": ["perfil inválido"],
        }

    reasons: List[str] = []
    mac = str(profile.get("mac") or "").strip().lower()
    if mac == "default" or not _valid_physical_mac(mac):
        reasons.append("MAC físico ausente ou inválido")

    family = normalize_family(
        profile.get("chip_family") or profile.get("chip_type")
    )
    metadata = get_family_metadata(family)
    if not metadata.get("known"):
        reasons.append("família do chip não reconhecida pelo catálogo")

    chip_type = str(profile.get("chip_type") or "").strip()
    if chip_type in ("", UNKNOWN, NONE_VAL):
        reasons.append("tipo do chip não identificado")

    target = str(profile.get("target") or "").strip().lower()
    expected_target = str(metadata.get("target") or "").strip().lower()
    if not target:
        reasons.append("target da família não definido")
    elif expected_target and target != expected_target:
        reasons.append(
            f"target '{target}' diverge da família {family} ({expected_target})"
        )

    gpio_count = profile.get("chip_gpio_count")
    if metadata.get("known") and (
        not isinstance(gpio_count, int)
        or isinstance(gpio_count, bool)
        or gpio_count <= 0
    ):
        reasons.append("quantidade oficial de GPIOs do SoC não definida")

    structural = audit_profile(profile)
    reasons.extend(structural)

    status = str(profile.get("layout_review_status") or "").strip()
    if status == LAYOUT_REVIEW_PENDING or profile.get("layout_review_required"):
        pending = profile.get("layout_review_reasons") or []
        if pending:
            reasons.extend(str(item) for item in pending if str(item).strip())
        else:
            reasons.append("revisão do layout pendente")
    elif status == LAYOUT_REVIEW_CONFIRMED:
        if not has_layout_content(profile):
            reasons.append("layout confirmado está vazio")
    elif status == LAYOUT_REVIEW_NOT_DEFINED:
        if has_layout_content(profile):
            reasons.append("estado sem layout diverge da geometria cadastrada")
    else:
        reasons.append("estado de revisão do layout inválido")

    reasons = list(dict.fromkeys(reasons))
    ready = not reasons
    return {
        "profile_ready": ready,
        "profile_readiness_status": (
            PROFILE_READINESS_READY if ready
            else PROFILE_READINESS_INCOMPLETE
        ),
        "profile_readiness_reasons": reasons,
    }


def validate_profile_against_chip(
    profile: Dict[str, Any],
    chip_info: Dict[str, Any],
    *,
    require_ready: bool = True,
) -> Dict[str, Any]:
    """Compara identidade viva com o perfil antes de qualquer uso físico."""
    readiness = evaluate_profile_readiness(profile)
    reasons: List[str] = []
    if require_ready and not readiness["profile_ready"]:
        reasons.extend(readiness["profile_readiness_reasons"])

    expected_mac = str(profile.get("mac") or "").strip().lower()
    live_mac = str(chip_info.get("mac") or "").strip().lower()
    if not _valid_physical_mac(live_mac):
        reasons.append("MAC vivo ausente ou inválido")
    elif expected_mac != live_mac:
        reasons.append(
            f"MAC vivo {live_mac} diverge do perfil {expected_mac or 'ausente'}"
        )

    expected_family = normalize_family(
        profile.get("chip_family") or profile.get("chip_type")
    )
    live_family = normalize_family(
        chip_info.get("chip_family") or chip_info.get("chip_type")
    )
    if live_family == UNKNOWN:
        reasons.append("família viva não identificada")
    elif expected_family != live_family:
        reasons.append(
            f"família viva {live_family} diverge do perfil {expected_family}"
        )

    reasons = list(dict.fromkeys(reasons))
    return {
        "matches": not reasons,
        "use_allowed": not reasons,
        "reasons": reasons,
        "expected_mac": expected_mac,
        "live_mac": live_mac,
        "expected_family": expected_family,
        "live_family": live_family,
        **readiness,
    }

def normalize_profile(profile):
    """
    Normaliza schema e deriva o estado de revisão sem confirmação silenciosa.

    Perfis antigos, sem `layout_review_status`, entram como `pending`.
    Um perfil só deixa de exigir revisão por ação explícita do usuário:
    confirmação do layout ou decisão de mantê-lo não definido.
    """
    result = (
        deepcopy(profile) if isinstance(profile, dict)
        else build_neutral_default()
    )
    family = normalize_family(
        result.get("chip_family") or result.get("chip_type")
    )
    meta = get_family_metadata(family)
    defaults = {
        "profile_confirmed": False,
        "profile_ready": False,
        "profile_readiness_status": PROFILE_READINESS_INCOMPLETE,
        "profile_readiness_reasons": [],
        "chip_family": family,
        "chip_type": family,
        "chip_variant": UNKNOWN,
        "package_variant": UNKNOWN,
        "target": meta.get("target") or "",
        "chip_gpio_count": meta.get("gpio_count"),
        "total_pins": 0,
        "pinout_mapping": [],
        "usb_ports": [],
        "source_type": "legacy",
        "source_family": family,
        "source_document": "",
        "source_revision": "",
        "source_url": "",
        "reference_board_name": "",
        "layout_source_type": "legacy",
        "layout_source_document": "",
        "layout_source_revision": "",
        "layout_source_url": "",
        "layout_notes": [],
        "layout_reviewed_at": "",
        "layout_reviewed_by": "",
        "layout_review_note": "",
    }
    for key, value in defaults.items():
        result.setdefault(key, deepcopy(value))
    result["profile_schema_version"] = PROFILE_SCHEMA_VERSION

    if "usb_port_count" not in result:
        ports = result.get("usb_ports")
        result["usb_port_count"] = (
            len(ports) if isinstance(ports, list) else 0
        )

    status = str(result.get("layout_review_status") or "").strip()
    if status not in LAYOUT_REVIEW_STATUSES:
        status = LAYOUT_REVIEW_PENDING

    structural = audit_profile(result)
    has_layout = has_layout_content(result)
    reasons = list(structural)

    if status == LAYOUT_REVIEW_CONFIRMED:
        if structural or not has_layout:
            status = LAYOUT_REVIEW_PENDING
            if not has_layout:
                reasons.append(
                    "layout confirmado anteriormente, mas agora está vazio"
                )
        else:
            reasons = []

    elif status == LAYOUT_REVIEW_NOT_DEFINED:
        if has_layout:
            status = LAYOUT_REVIEW_PENDING
            reasons.append(
                "estado 'sem layout' diverge dos dados físicos cadastrados"
            )
        else:
            reasons = []

    if status == LAYOUT_REVIEW_PENDING and not reasons:
        source_type = str(result.get("layout_source_type") or "legacy")
        if not has_layout:
            reasons.append(
                "layout físico não definido; confirme a decisão de mantê-lo vazio"
            )
        elif source_type == "espressif_reference_board":
            reasons.append(
                "layout oficial de referência ainda não confirmado para esta placa física"
            )
        elif source_type == "user_edited_from_reference":
            reasons.append(
                "layout baseado em referência foi alterado; confirme a revisão manual"
            )
        elif source_type == "user_edited":
            reasons.append(
                "layout alterado manualmente; confirme após revisar"
            )
        else:
            reasons.append("perfil legado ainda não teve o layout confirmado")

    result["layout_review_status"] = status
    result["layout_review_required"] = (
        status == LAYOUT_REVIEW_PENDING
    )
    result["layout_review_reasons"] = list(dict.fromkeys(reasons))
    result["mac"] = str(result.get("mac") or "").strip().lower()
    result.update(evaluate_profile_readiness(result))
    return result




def resize_pinout_mapping(
    pinout: List[Dict[str, Any]] | None,
    total_pins: int,
):
    """
    Redimensiona o mapa por fileira visual, de cima para baixo.

    Ao reduzir 44 para 30, preserva os 15 primeiros pontos de cada coluna,
    em vez de conservar acidentalmente o rodapé da coluna direita. O campo
    `side` é apenas derivado/compatível; a saída usa numeração física global.
    """
    if not isinstance(total_pins, int) or isinstance(total_pins, bool):
        return (False, "total_pins precisa ser inteiro")
    if total_pins < 0:
        return (False, "total_pins não pode ser negativo")
    if total_pins and total_pins % 2:
        return (False, "total_pins precisa ser par")

    source = [deepcopy(item) for item in (pinout or []) if isinstance(item, dict)]
    if total_pins == 0:
        return (True, {
            "pinout_mapping": [],
            "preserved": 0,
            "added": 0,
            "removed": len(source),
            "legacy_converted": False,
        })

    physical = [item.get("physical") for item in source]
    duplicate = len(physical) != len(set(physical))
    sides_ok = bool(source) and all(
        item.get("side") in ("left", "right") for item in source
    )
    legacy_converted = bool(duplicate and sides_ok)

    left: List[Dict[str, Any]] = []
    right: List[Dict[str, Any]] = []

    if legacy_converted:
        left = sorted(
            (item for item in source if item.get("side") == "left"),
            key=lambda item: item.get("physical", 0),
        )
        right = sorted(
            (item for item in source if item.get("side") == "right"),
            key=lambda item: item.get("physical", 0),
        )
    else:
        valid_numbers = [
            number for number in physical
            if isinstance(number, int) and not isinstance(number, bool)
            and number > 0
        ]
        inferred_total = max(valid_numbers, default=len(source))
        if inferred_total % 2:
            inferred_total += 1
        old_half = inferred_total // 2
        left = sorted(
            (
                item for item in source
                if isinstance(item.get("physical"), int)
                and 1 <= item["physical"] <= old_half
            ),
            key=lambda item: item["physical"],
        )
        right = sorted(
            (
                item for item in source
                if isinstance(item.get("physical"), int)
                and old_half < item["physical"] <= inferred_total
            ),
            key=lambda item: item["physical"],
            reverse=True,
        )

    new_half = total_pins // 2
    kept_left = left[:new_half]
    kept_right = right[:new_half]
    preserved = len(kept_left) + len(kept_right)
    removed = max(0, len(source) - preserved)
    added = (new_half - len(kept_left)) + (new_half - len(kept_right))

    def _placeholder() -> Dict[str, Any]:
        return {
            "gpio": None,
            "label": "Não definido",
            "category": "",
            "functions": [],
        }

    result: List[Dict[str, Any]] = []
    for index in range(new_half):
        item = deepcopy(kept_left[index]) if index < len(kept_left) else _placeholder()
        item["physical"] = index + 1
        item["side"] = "left"
        item.setdefault("gpio", None)
        item.setdefault("label", "Não definido")
        item.setdefault("category", "")
        item.setdefault("functions", [])
        result.append(item)

    for index in range(new_half):
        item = deepcopy(kept_right[index]) if index < len(kept_right) else _placeholder()
        item["physical"] = total_pins - index
        item["side"] = "right"
        item.setdefault("gpio", None)
        item.setdefault("label", "Não definido")
        item.setdefault("category", "")
        item.setdefault("functions", [])
        result.append(item)

    return (True, {
        "pinout_mapping": result,
        "preserved": preserved,
        "added": added,
        "removed": removed,
        "legacy_converted": legacy_converted,
    })

__all__ = [
    "PROFILE_SCHEMA_VERSION", "FAMILY_CATALOG", "normalize_family",
    "target_for_family", "get_family_metadata", "get_reference_layout",
    "has_layout_content", "build_neutral_default", "build_family_profile",
    "normalize_profile", "audit_profile", "resize_pinout_mapping",
    "evaluate_profile_readiness", "validate_profile_against_chip",
    "LAYOUT_REVIEW_PENDING", "LAYOUT_REVIEW_CONFIRMED",
    "LAYOUT_REVIEW_NOT_DEFINED", "LAYOUT_REVIEW_STATUSES",
    "LAYOUT_CONTENT_FIELDS",
    "PROFILE_READINESS_READY", "PROFILE_READINESS_INCOMPLETE",
    "PROFILE_READINESS_STATUSES",
]

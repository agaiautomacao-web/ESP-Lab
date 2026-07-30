"""Validador código × chip antes do build (@E8-T8.6).

Cruza recursos declarados no projeto com capacidades normalizadas do perfil
físico associado por MAC. A validação é offline: não interroga hardware e não
altera projeto, perfil ou build.

Estados por capacidade:
  - present: o perfil/família fornece evidência positiva;
  - absent: há evidência explícita de incompatibilidade;
  - unknown: os dados atuais não permitem concluir.

Somente ``absent`` bloqueia a compilação. ``unknown`` gera aviso e permite que
o usuário prossiga conscientemente. Omissão em ``features`` nunca é tratada
como ausência.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from ..hardware import family_profiles as _family_profiles

Result = Tuple[bool, Any]

CAP_PRESENT = "present"
CAP_ABSENT = "absent"
CAP_UNKNOWN = "unknown"
CAPABILITY_STATES = {CAP_PRESENT, CAP_ABSENT, CAP_UNKNOWN}

FEATURE_CATALOG: Dict[str, Dict[str, str]] = {
    "wifi": {
        "label": "Wi-Fi",
        "description": "rádio Wi-Fi integrado ao SoC",
    },
    "bt_ble": {
        "label": "Bluetooth / BLE",
        "description": "Bluetooth clássico e/ou Bluetooth Low Energy",
    },
    "psram": {
        "label": "PSRAM",
        "description": "memória PSRAM presente no módulo/placa",
    },
    "camera": {
        "label": "Interface de câmera",
        "description": "interface/caminho de hardware declarado para câmera",
    },
    "usb_otg": {
        "label": "USB OTG",
        "description": "controlador USB OTG nativo",
    },
    "ethernet": {
        "label": "Ethernet",
        "description": "controlador Ethernet MAC integrado",
    },
    "touch": {
        "label": "Touch capacitivo",
        "description": "periférico de toque capacitivo integrado",
    },
}
FEATURE_TO_CAP = {name: name for name in FEATURE_CATALOG}

# Matriz conservadora de capacidades intrínsecas da família. Recurso que não
# é garantido pela família fica desconhecido; periféricos externos nunca são
# presumidos apenas pelo nome do SoC.
_FAMILY_CAPABILITIES: Dict[str, Dict[str, str]] = {
    "ESP32": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
        "usb_otg": CAP_ABSENT,
        "ethernet": CAP_PRESENT,
        "touch": CAP_PRESENT,
    },
    "ESP32-S2": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_ABSENT,
        "usb_otg": CAP_PRESENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_PRESENT,
    },
    "ESP32-S3": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
        "camera": CAP_PRESENT,
        "usb_otg": CAP_PRESENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_PRESENT,
    },
    "ESP32-C2": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
        "usb_otg": CAP_ABSENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_ABSENT,
    },
    "ESP32-C3": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
        "usb_otg": CAP_ABSENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_ABSENT,
    },
    "ESP32-C5": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
    },
    "ESP32-C6": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
        "usb_otg": CAP_ABSENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_ABSENT,
    },
    "ESP32-C61": {
        "wifi": CAP_PRESENT,
        "bt_ble": CAP_PRESENT,
    },
    "ESP32-H2": {
        "wifi": CAP_ABSENT,
        "bt_ble": CAP_PRESENT,
        "usb_otg": CAP_ABSENT,
        "ethernet": CAP_ABSENT,
        "touch": CAP_ABSENT,
    },
    "ESP32-P4": {
        "wifi": CAP_ABSENT,
        "bt_ble": CAP_ABSENT,
        "camera": CAP_PRESENT,
        "usb_otg": CAP_PRESENT,
        "ethernet": CAP_PRESENT,
        "touch": CAP_PRESENT,
    },
}

_UNKNOWN_MARKERS = {
    "desconhecido", "desconhecida", "unknown", "?", "indisponivel",
    "indisponível", "nao informado", "não informado", "nao detectado",
    "não detectado", "nao detectada", "não detectada", "",
}
_ABSENT_MARKERS = {
    "nenhum", "nenhuma", "nao", "não", "ausente", "none", "false",
    "off", "disabled", "desativado", "desativada", "0",
}
_PRESENT_MARKERS = {
    "sim", "yes", "true", "on", "enabled", "presente", "present", "1",
}

_FEATURE_PATTERNS: Dict[str, Tuple[re.Pattern[str], ...]] = {
    "wifi": (
        re.compile(r"\bwi[\s-]?fi\b", re.IGNORECASE),
        re.compile(r"\b802\.11\b", re.IGNORECASE),
    ),
    "bt_ble": (
        re.compile(r"\bbluetooth\b", re.IGNORECASE),
        re.compile(r"\bble\b", re.IGNORECASE),
        re.compile(r"(?:^|[,;/\s])bt(?:$|[,;/\s])", re.IGNORECASE),
    ),
    "psram": (re.compile(r"\bpsram\b", re.IGNORECASE),),
    "camera": (
        re.compile(r"\bcamera\b", re.IGNORECASE),
        re.compile(r"\bcam\b", re.IGNORECASE),
    ),
    "usb_otg": (
        re.compile(r"\busb[\s_-]*otg\b", re.IGNORECASE),
        re.compile(r"\botg\b", re.IGNORECASE),
    ),
    "ethernet": (
        re.compile(r"\bethernet\b", re.IGNORECASE),
        re.compile(r"\bemac\b", re.IGNORECASE),
    ),
    "touch": (
        re.compile(r"\btouch\b", re.IGNORECASE),
        re.compile(r"\bcapacitive\b", re.IGNORECASE),
    ),
}


def _normalize_feature_name(value: Any) -> str:
    return str(value or "").strip().lower()


def feature_label(name: Any) -> str:
    key = _normalize_feature_name(name)
    return FEATURE_CATALOG.get(key, {}).get("label", key or "desconhecido")


def list_known_features() -> Result:
    """Lista estável de chaves aceitas em ``project_config.features``."""
    return True, list(FEATURE_CATALOG.keys())


def get_feature_catalog() -> Result:
    """Retorna cópia simples do catálogo para menus e relatórios."""
    return True, {
        key: dict(value) for key, value in FEATURE_CATALOG.items()
    }


def _classify_explicit(value: Any) -> str:
    """Classifica somente valores que realmente afirmam um estado.

    ``None``, vazio e marcadores de leitura indisponível são desconhecidos,
    nunca ausência. Valores positivos como ``8MB`` contam como presentes.
    """
    if value is None:
        return CAP_UNKNOWN
    if isinstance(value, bool):
        return CAP_PRESENT if value else CAP_ABSENT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return CAP_PRESENT if value > 0 else CAP_ABSENT

    text = str(value).strip().lower()
    if text in _UNKNOWN_MARKERS:
        return CAP_UNKNOWN
    if text in _ABSENT_MARKERS:
        return CAP_ABSENT
    if text in _PRESENT_MARKERS:
        return CAP_PRESENT
    return CAP_PRESENT


def _feature_text(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            state = _classify_explicit(item)
            if state == CAP_PRESENT:
                parts.append(str(key))
        return ", ".join(parts)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _has_pattern(text: str, feature: str) -> bool:
    return any(pattern.search(text) for pattern in _FEATURE_PATTERNS[feature])


def _set_state(
    states: Dict[str, str],
    evidence: Dict[str, List[str]],
    feature: str,
    state: str,
    reason: str,
    *,
    override: bool = False,
) -> None:
    if feature not in states or state not in CAPABILITY_STATES:
        return
    current = states[feature]
    if override or current == CAP_UNKNOWN:
        states[feature] = state
        evidence[feature] = [reason]
    elif current == state and reason not in evidence[feature]:
        evidence[feature].append(reason)


def normalize_board_capabilities(board_profile: Any) -> Result:
    """Normaliza o perfil físico em capacidades tri-state.

    Ordem de evidência: família conservadora, detecção positiva em ``features``,
    campos especializados (PSRAM/USB) e, por último, capacidades explícitas
    editadas no perfil. A ausência de um token nunca vira ``absent``.
    """
    if not isinstance(board_profile, dict):
        return False, "perfil da placa inválido (esperado dicionário)"

    states = {name: CAP_UNKNOWN for name in FEATURE_CATALOG}
    evidence: Dict[str, List[str]] = {name: [] for name in FEATURE_CATALOG}

    family = _family_profiles.normalize_family(
        board_profile.get("chip_family") or board_profile.get("chip_type")
    )
    for feature, state in _FAMILY_CAPABILITIES.get(family, {}).items():
        _set_state(
            states,
            evidence,
            feature,
            state,
            f"capacidade intrínseca da família {family}",
        )

    raw_features = _feature_text(board_profile.get("features"))
    if raw_features and raw_features.strip().lower() not in _UNKNOWN_MARKERS:
        for feature in FEATURE_CATALOG:
            if _has_pattern(raw_features, feature):
                _set_state(
                    states,
                    evidence,
                    feature,
                    CAP_PRESENT,
                    f"detectado em features: {raw_features}",
                    override=True,
                )

    psram_value = board_profile.get("psram_enabled")
    psram_state = _classify_explicit(psram_value)
    if psram_state != CAP_UNKNOWN:
        _set_state(
            states,
            evidence,
            "psram",
            psram_state,
            f"psram_enabled={psram_value!r}",
            override=True,
        )

    usb_mode = board_profile.get("usb_mode")
    usb_text = str(usb_mode or "").strip()
    if _has_pattern(usb_text, "usb_otg"):
        _set_state(
            states,
            evidence,
            "usb_otg",
            CAP_PRESENT,
            f"usb_mode={usb_text!r}",
            override=True,
        )
    elif _classify_explicit(usb_mode) == CAP_ABSENT:
        _set_state(
            states,
            evidence,
            "usb_otg",
            CAP_ABSENT,
            f"usb_mode={usb_text!r}",
            override=True,
        )

    usb_ports = board_profile.get("usb_ports")
    if isinstance(usb_ports, list):
        for port in usb_ports:
            if not isinstance(port, dict):
                continue
            port_text = " ".join(
                str(port.get(key) or "")
                for key in ("type", "nome", "name")
            )
            if _has_pattern(port_text, "usb_otg"):
                _set_state(
                    states,
                    evidence,
                    "usb_otg",
                    CAP_PRESENT,
                    f"porta USB declarada: {port_text.strip()}",
                    override=True,
                )
                break

    explicit: Dict[str, Any] = {}
    capability_block = board_profile.get("capabilities")
    if isinstance(capability_block, dict):
        explicit.update(capability_block)
    for feature in FEATURE_CATALOG:
        if feature in board_profile:
            explicit[feature] = board_profile.get(feature)

    for raw_name, value in explicit.items():
        feature = _normalize_feature_name(raw_name)
        if feature not in FEATURE_CATALOG:
            continue
        state = _classify_explicit(value)
        if state == CAP_UNKNOWN:
            continue
        _set_state(
            states,
            evidence,
            feature,
            state,
            f"capacidade explícita {feature}={value!r}",
            override=True,
        )

    return True, {
        "chip_family": family,
        "capabilities": states,
        "evidence": evidence,
    }


def _clean_declared_features(values: Iterable[Any]) -> Tuple[List[str], List[str]]:
    declared: List[str] = []
    ignored: List[str] = []
    for item in values:
        key = _normalize_feature_name(item)
        if not key:
            continue
        if key not in FEATURE_CATALOG:
            if key not in ignored:
                ignored.append(key)
            continue
        if key not in declared:
            declared.append(key)
    return declared, ignored


def evaluate(project_features: Any, board_profile: Any) -> Result:
    """Retorna relatório estruturado sem executar nenhuma ação externa."""
    if not isinstance(project_features, (list, tuple)):
        return False, "lista de recursos do projeto inválida"

    ok_caps, normalized = normalize_board_capabilities(board_profile)
    if not ok_caps:
        return False, normalized

    declared, ignored = _clean_declared_features(project_features)
    states = normalized["capabilities"]
    conflicts = [name for name in declared if states[name] == CAP_ABSENT]
    warnings = [name for name in declared if states[name] == CAP_UNKNOWN]

    if conflicts:
        labels = ", ".join(feature_label(name) for name in conflicts)
        status = "conflict"
        message = (
            "recurso(s) exigido(s) pelo projeto incompatível(is) com o perfil: "
            f"{labels}; compilação bloqueada"
        )
    elif warnings:
        labels = ", ".join(feature_label(name) for name in warnings)
        status = "warning"
        message = (
            "capacidade ainda desconhecida no perfil: "
            f"{labels}; compilação permitida com aviso"
        )
    elif declared:
        status = "ok"
        message = "todos os recursos declarados são compatíveis com o perfil"
    else:
        status = "not_declared"
        message = "o projeto não declarou recursos opcionais para validar"

    if ignored:
        ignored_text = ", ".join(sorted(ignored))
        message += f"; recurso(s) fora do catálogo ignorado(s): {ignored_text}"

    return True, {
        "status": status,
        "blocking": bool(conflicts),
        "message": message,
        "declared": declared,
        "conflitos": conflicts,
        "avisos": warnings,
        "ignorados": ignored,
        "capabilities": states,
        "evidence": normalized["evidence"],
        "chip_family": normalized["chip_family"],
    }


def validate(project_features: Any, board_profile: Any) -> Result:
    """Compatibilidade com o contrato histórico ``(ok, resultado)``.

    Conflito real devolve ``False`` e mensagem. Aviso/desconhecido devolve
    ``True`` com relatório estruturado.
    """
    ok, report = evaluate(project_features, board_profile)
    if not ok:
        return False, report
    if report["blocking"]:
        return False, report["message"]
    return True, report


__all__ = [
    "CAP_PRESENT", "CAP_ABSENT", "CAP_UNKNOWN", "CAPABILITY_STATES",
    "FEATURE_CATALOG", "FEATURE_TO_CAP", "feature_label",
    "list_known_features", "get_feature_catalog",
    "normalize_board_capabilities", "evaluate", "validate",
]

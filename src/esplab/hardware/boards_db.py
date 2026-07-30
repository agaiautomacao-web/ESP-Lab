#!/usr/bin/env python3
"""
Gerenciador do banco de placas do ESP Lab (@E5-T5.4 / @E5-T5.5).

Porta de entrada UNICA para o banco de placas (JSON). Nenhum outro codigo toca
o arquivo diretamente — toda criacao, leitura, edicao e remocao passa por aqui.

Regras de produto (identificacao por MAC):
  - cada placa fisica possui um perfil por MAC;
  - a chave "default" e apenas reservada, nunca matriz de novos perfis;
  - novos perfis nascem do catalogo de familia em family_profiles.py;
  - layout legado nunca e confirmado ou substituido silenciosamente;
  - confirmar, aplicar referencia ou limpar layout exige acao explicita;
  - add    -> nao sobrescreve perfil existente.
  - edit   -> MESCLA campos (preserva o que nao veio); evita perda de pinagem.
  - remove -> RECUSA apagar a chave padrao.

Contrato: (ok, result_or_error); nunca lanca. Persistencia atomica via storage.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import shutil
from typing import Any, Dict, Tuple

from ..core import paths as _paths
from ..core import storage as _storage
from ..core import logger as _logger
from . import family_profiles as _family_profiles
from . import chip_divergence as _divergence

Result = Tuple[bool, Any]

# Chave reservada do perfil base. Nao pode ser removida nem editada.
DEFAULT_KEY = "default"

# Estado de CONEXÃO ao vivo da placa (por MAC), gravado na varredura.
# Distinto de profile_readiness_status (completude do perfil, derivada
# por normalize_profile). Este campo registra a presença física da placa
# na última varredura e NÃO é derivado — sobrevive ao normalize.
CONNECTION_CONNECTED = "connected"
CONNECTION_NOT_FOUND = "not_found"
CONNECTION_UNCHECKED = "unchecked"
CONNECTION_STATUSES = {
    CONNECTION_CONNECTED,
    CONNECTION_NOT_FOUND,
    CONNECTION_UNCHECKED,
}

UNKNOWN = "Desconhecido"
NONE_VAL = "Nenhum"

# Valores considerados "vazios" — nao sobrescrevem dados ja bons num perfil.
_FALLBACK_VALUES = {UNKNOWN, NONE_VAL, "", None, "nao identificado"}

# Campos "Fixo": vem do chip real, nunca editaveis na UI. Uma vez que o
# perfil e confirmado (edicao manual), esses campos param de ser
# sobrescritos por releitura automatica do esptool.
FIXO_FIELDS = {
    "chip_type", "chip_family", "chip_variant", "package_variant",
    "target", "chip_revision", "features", "crystal",
    "flash_manufacturer", "flash_device",
}






# Esqueleto do perfil padrao. Placeholders honestos onde o dado depende do chip.
def _default_profile() -> Dict[str, Any]:
    """Registro reservado; novos MACs não são clonados daqui."""
    return _family_profiles.build_neutral_default()


# Alias de compatibilidade: board_validator ainda referencia DEFAULT_PROFILE.
DEFAULT_PROFILE = _default_profile()

VALID_OPERATIONS = ("add", "edit", "remove")

# Alterar geometria ou conectores invalida uma revisão anterior.
_LAYOUT_CONTENT_FIELDS = set(_family_profiles.LAYOUT_CONTENT_FIELDS)
_LAYOUT_REVIEW_CONTROL_FIELDS = {
    "layout_review_status", "layout_review_required",
    "layout_review_reasons", "layout_reviewed_at",
    "layout_reviewed_by", "layout_review_note",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path():
    return _paths.get_paths().boards_db



def _backup_before_destructive() -> Result:
    """Cria backup verificado do banco antes de remoção ou limpeza total."""
    path = _db_path()
    if not path.is_file():
        return (True, "")
    try:
        original = path.read_bytes()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = path.with_name(f"{path.name}.{stamp}.old")
        shutil.copy2(path, backup)
        copied = backup.read_bytes()
        if copied != original:
            backup.unlink(missing_ok=True)
            return (False, "backup do banco divergiu byte a byte")
        if hashlib.sha256(copied).digest() != hashlib.sha256(original).digest():
            backup.unlink(missing_ok=True)
            return (False, "SHA-256 do backup do banco divergiu")
        return (True, str(backup))
    except Exception as exc:
        return (False, f"falha ao criar backup do banco: {exc}")


def _load() -> Result:
    """Carrega o banco. Se nao existir, nasce com a chave padrao."""
    path = _db_path()
    if not path.is_file():
        return (True, {DEFAULT_KEY: _default_profile()})
    ok, data = _storage.read_json(path)
    if not ok:
        return (False, data)
    if not isinstance(data, dict):
        return (False, "banco de placas corrompido: estrutura raiz invalida")
    if DEFAULT_KEY not in data:
        data[DEFAULT_KEY] = _default_profile()
    return (True, data)


def _save(db: Dict[str, Any]) -> Result:
    return _storage.atomic_write_json(_db_path(), db)


# ==========================================================
# PORTA DE ENTRADA
# ==========================================================

def key_json_manager(operation: str, mac: str,
                     data: Dict[str, Any] | None = None) -> Result:
    """Gerencia o banco. operation: add|edit|remove. mac: chave do registro."""
    if operation not in VALID_OPERATIONS:
        return (False, f"operacao invalida: '{operation}' (use add, edit ou remove)")
    if not isinstance(mac, str) or not mac.strip():
        return (False, "MAC vazio ou invalido")
    mac = mac.strip()
    if operation in ("add", "edit"):
        if data is None:
            return (False, f"operacao '{operation}' exige dados do perfil")
        if not isinstance(data, dict):
            return (False, "dados do perfil devem ser um objeto (dict)")
    ok, db = _load()
    if not ok:
        return (False, db)
    if operation == "add":
        return _add(db, mac, data)
    if operation == "edit":
        return _edit(db, mac, data)
    return _remove(db, mac)


# ==========================================================
# OPERACOES
# ==========================================================

def _add(db: Dict[str, Any], mac: str,
         data: Dict[str, Any]) -> Result:
    """Adiciona por MAC usando a família informada como base."""
    if mac in db:
        return (False, f"perfil com MAC '{mac}' já existe; use edit")
    profile = _family_profiles.build_family_profile(data)
    profile.update(data)
    profile["mac"] = mac
    profile = _family_profiles.normalize_profile(profile)
    db[mac] = profile
    ok, res = _save(db)
    return (True, profile) if ok else (False, res)


def _edit(db: Dict[str, Any], mac: str,
          data: Dict[str, Any]) -> Result:
    """Edita por mesclagem e invalida revisão quando o layout muda."""
    if mac == DEFAULT_KEY:
        return (False, "o perfil reservado não pode ser editado")
    if mac not in db:
        return (False, f"perfil com MAC '{mac}' inexistente")

    profile = _family_profiles.normalize_profile(db[mac])
    changes = dict(data)
    layout_changed = bool(_LAYOUT_CONTENT_FIELDS.intersection(changes))
    review_controlled = bool(
        _LAYOUT_REVIEW_CONTROL_FIELDS.intersection(changes)
    )

    if layout_changed and not review_controlled:
        previous_source = str(profile.get("layout_source_type") or "")
        changes.update({
            "layout_review_status": _family_profiles.LAYOUT_REVIEW_PENDING,
            "layout_review_required": True,
            "layout_reviewed_at": "",
            "layout_reviewed_by": "",
            "layout_review_note": "",
            "layout_source_type": (
                "user_edited_from_reference"
                if previous_source in {
                    "espressif_reference_board",
                    "user_edited_from_reference",
                }
                else "user_edited"
            ),
        })

    profile.update(changes)
    profile["mac"] = mac
    profile["profile_confirmed"] = True
    profile = _family_profiles.normalize_profile(profile)
    db[mac] = profile
    ok, res = _save(db)
    return (True, profile) if ok else (False, res)


def _remove(db: Dict[str, Any], mac: str) -> Result:
    """Remove um perfil por MAC após criar backup verificado do banco."""
    if mac == DEFAULT_KEY:
        return (False, "a chave padrão não pode ser removida")
    if mac not in db:
        return (False, f"perfil com MAC '{mac}' inexistente; nada a remover")

    profile = _family_profiles.normalize_profile(db[mac])
    ok_backup, backup = _backup_before_destructive()
    if not ok_backup:
        return (False, backup)

    del db[mac]
    ok, result = _save(db)
    if not ok:
        return (False, result)
    return (True, {
        "message": f"perfil '{mac}' removido",
        "mac": mac,
        "board_name": profile.get("board_name") or "Não identificada",
        "backup": backup,
    })


# ==========================================================
# FLUXO PRINCIPAL — busca ou cria por MAC
# ==========================================================

def _map_chip_to_profile(chip_info: Dict[str, Any]) -> Dict[str, Any]:
    """Traduz saída normalizada do chip para campos do perfil."""
    family = _family_profiles.normalize_family(
        chip_info.get("chip_family") or chip_info.get("chip_type")
    )
    return {
        "chip_type":          chip_info.get("chip_type", family or UNKNOWN),
        "chip_family":        family,
        "chip_variant":       chip_info.get("chip_variant", UNKNOWN),
        "package_variant":    chip_info.get("package_variant", UNKNOWN),
        "target":             _family_profiles.target_for_family(family),
        "chip_revision":      chip_info.get("chip_revision", UNKNOWN),
        "flash_size_mb":      chip_info.get("flash_size", UNKNOWN),
        "psram_enabled":      chip_info.get("psram", NONE_VAL),
        "features":           chip_info.get("features", UNKNOWN),
        "usb_mode":           chip_info.get("usb_mode", UNKNOWN),
        "crystal":            chip_info.get("crystal", UNKNOWN),
        "flash_manufacturer": chip_info.get("flash_manufacturer", UNKNOWN),
        "flash_device":       chip_info.get("flash_device", UNKNOWN),
    }


def _merge_preserving(
    profile: Dict[str, Any],
    novos: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Mescla o dado vivo depois da comparacao de divergencia.

    Campo fixo conhecido nunca e alterado automaticamente. Campo fixo ausente
    pode ser preenchido por uma leitura conhecida. Campos nao fixos mantem a
    regra historica de atualizacao, mas a diferenca ja foi registrada antes da
    mesclagem por chip_divergence.
    """
    out = dict(profile)
    updated_fields = []
    enriched_locked_fields = []
    preserved_locked_fields = []

    for key, incoming in novos.items():
        current = out.get(key)
        incoming_missing = _divergence.is_missing_profile_value(key, incoming)
        current_missing = _divergence.is_missing_profile_value(key, current)

        if key in FIXO_FIELDS:
            if current_missing and not incoming_missing:
                out[key] = incoming
                enriched_locked_fields.append(key)
            elif (
                not current_missing
                and not incoming_missing
                and not _divergence.profile_values_equivalent(
                    key, current, incoming
                )
            ):
                preserved_locked_fields.append(key)
            continue

        if incoming_missing and not current_missing:
            continue
        if incoming_missing and current_missing:
            continue
        if _divergence.profile_values_equivalent(key, current, incoming):
            continue
        out[key] = incoming
        updated_fields.append(key)

    return out, {
        "updated_fields": updated_fields,
        "enriched_locked_fields": enriched_locked_fields,
        "preserved_locked_fields": preserved_locked_fields,
    }


def find_or_create_by_mac(chip_info: Dict[str, Any]) -> Result:
    """
    Busca ou cria perfil por MAC.

    Para perfil existente, compara chip vivo x perfil persistido antes de
    qualquer mesclagem. Divergencia de campo fixo e preservada e devolvida ao
    chamador; informacao ausente pode ser completada sem ser tratada como
    divergencia.
    """
    if not isinstance(chip_info, dict):
        return (False, "dados do chip invalidos (esperado dict)")
    mac = str(chip_info.get("mac") or "").strip().lower()
    if _divergence.is_missing_profile_value("mac", mac):
        return (False, "MAC do chip indisponível; não é possível criar perfil")

    ok, db = _load()
    if not ok:
        return (False, db)
    new_values = _map_chip_to_profile(chip_info)

    if mac in db:
        current = _family_profiles.normalize_profile(db[mac])
        ok_compare, comparison = _divergence.check_divergence(
            chip_info, current
        )
        if not ok_compare:
            return (False, comparison)

        merged, merge_info = _merge_preserving(current, new_values)
        merged["mac"] = mac
        updated = _family_profiles.normalize_profile(merged)
        persisted = updated != current
        if persisted:
            db[mac] = updated
            ok2, result = _save(db)
            if not ok2:
                return (False, result)

        return (True, {
            "profile": updated,
            "profile_before": current,
            "created": False,
            "persisted": persisted,
            "comparison": comparison,
            **merge_info,
        })

    profile = _family_profiles.build_family_profile(chip_info)
    profile.update(new_values)
    profile["mac"] = mac
    profile["board_name"] = (
        f"Nova placa ({profile.get('chip_type') or profile.get('chip_family')}) "
        f"{mac[-8:]}"
    )
    profile = _family_profiles.normalize_profile(profile)
    db[mac] = profile
    ok2, result = _save(db)
    if not ok2:
        return (False, result)
    _logger.get_logger().info(
        "perfil criado para MAC %s a partir da família %s",
        mac, profile.get("chip_family"),
    )
    return (True, {
        "profile": profile,
        "profile_before": None,
        "created": True,
        "persisted": True,
        "comparison": {
            "status": "ok",
            "divergencias": [],
            "dados_ausentes": [],
            "campos_conferidos": 0,
            "has_locked_divergence": False,
            "message": "novo perfil criado; nao havia registro anterior para comparar",
        },
        "updated_fields": [],
        "enriched_locked_fields": [],
        "preserved_locked_fields": [],
    })


# ==========================================================
# LEITURA AUXILIAR
# ==========================================================

def get_profile(mac: str) -> Result:
    """Retorna perfil normalizado sem regravar o banco."""
    ok, db = _load()
    if not ok:
        return (False, db)
    if mac not in db:
        return (False, f"perfil '{mac}' inexistente")
    return (True, _family_profiles.normalize_profile(db[mac]))


def get_default() -> Result:
    """Retorna o registro reservado somente por compatibilidade."""
    ok, db = _load()
    if not ok:
        return (False, db)
    return (True, _family_profiles.normalize_profile(
        db.get(DEFAULT_KEY, _default_profile())
    ))


def list_models() -> Result:
    """Lista os MACs cadastrados (inclui 'default'). (True, [macs])."""
    ok, db = _load()
    if not ok:
        return (False, db)
    return (True, sorted(db.keys()))


def list_profiles() -> Result:
    """Lista perfis físicos normalizados, sem o registro reservado."""
    ok, db = _load()
    if not ok:
        return (False, db)
    return (True, [
        _family_profiles.normalize_profile(value)
        for key, value in db.items() if key != DEFAULT_KEY
    ])


def get_family_profile(chip_family: str, chip_type: str = "") -> Result:
    """Cria uma cópia do perfil-base sem persistir."""
    return (True, _family_profiles.build_family_profile({
        "chip_family": chip_family,
        "chip_type": chip_type or chip_family,
    }))


def get_target_for_profile(mac: str) -> Result:
    ok, profile = get_profile(mac)
    if not ok:
        return (False, profile)
    target = str(
        profile.get("target")
        or _family_profiles.target_for_family(profile.get("chip_family"))
        or ""
    )
    return (True, target) if target else (
        False, "target não definido para a família do perfil"
    )


def apply_family_reference_layout(mac: str) -> Result:
    """Substitui apenas o layout por uma referência oficial da família."""
    ok, db = _load()
    if not ok:
        return (False, db)
    if mac == DEFAULT_KEY or mac not in db:
        return (False, f"perfil '{mac}' inexistente ou reservado")

    profile = _family_profiles.normalize_profile(db[mac])
    ok_ref, reference = _family_profiles.get_reference_layout(
        profile.get("chip_family")
    )
    if not ok_ref:
        return (False, reference)

    profile.update({
        "total_pins": reference.get("total_pins", 0),
        "pinout_mapping": reference.get("pinout_mapping", []),
        "usb_port_count": reference.get("usb_port_count", 0),
        "usb_ports": reference.get("usb_ports", []),
        "reference_board_name": reference.get("reference_board_name", ""),
        "layout_source_type": "espressif_reference_board",
        "layout_source_document": reference.get(
            "layout_source_document", ""
        ),
        "layout_source_revision": reference.get(
            "layout_source_revision", ""
        ),
        "layout_source_url": reference.get("layout_source_url", ""),
        "layout_notes": reference.get("layout_notes", []),
        "layout_review_status": _family_profiles.LAYOUT_REVIEW_PENDING,
        "layout_review_required": True,
        "layout_reviewed_at": "",
        "layout_reviewed_by": "",
        "layout_review_note": "",
        "profile_confirmed": True,
    })
    profile = _family_profiles.normalize_profile(profile)
    db[mac] = profile
    ok_save, result = _save(db)
    return (True, profile) if ok_save else (False, result)


def clear_profile_layout(mac: str) -> Result:
    """Registra explicitamente que o perfil ficará sem layout físico."""
    ok, db = _load()
    if not ok:
        return (False, db)
    if mac == DEFAULT_KEY or mac not in db:
        return (False, f"perfil '{mac}' inexistente ou reservado")

    profile = _family_profiles.normalize_profile(db[mac])
    profile.update({
        "total_pins": 0,
        "pinout_mapping": [],
        "usb_port_count": 0,
        "usb_ports": [],
        "reference_board_name": "",
        "layout_source_type": "user_undefined",
        "layout_source_document": "",
        "layout_source_revision": "",
        "layout_source_url": "",
        "layout_notes": [],
        "layout_review_status": _family_profiles.LAYOUT_REVIEW_NOT_DEFINED,
        "layout_review_required": False,
        "layout_review_reasons": [],
        "layout_reviewed_at": _now(),
        "layout_reviewed_by": "user",
        "layout_review_note": (
            "Usuário optou por manter o layout físico não definido."
        ),
        "profile_confirmed": True,
    })
    profile = _family_profiles.normalize_profile(profile)
    db[mac] = profile
    ok_save, result = _save(db)
    return (True, profile) if ok_save else (False, result)


def confirm_profile_layout(mac: str, note: str = "") -> Result:
    """Confirma explicitamente o layout atual após auditoria estrutural."""
    ok, db = _load()
    if not ok:
        return (False, db)
    if mac == DEFAULT_KEY or mac not in db:
        return (False, f"perfil '{mac}' inexistente ou reservado")

    profile = _family_profiles.normalize_profile(db[mac])
    reasons = _family_profiles.audit_profile(profile)
    if reasons:
        return (
            False,
            "layout não pode ser confirmado:\n  - " + "\n  - ".join(reasons),
        )
    if not _family_profiles.has_layout_content(profile):
        return (
            False,
            "layout vazio; use a ação 'Manter sem layout físico'",
        )

    profile.update({
        "layout_review_status": _family_profiles.LAYOUT_REVIEW_CONFIRMED,
        "layout_review_required": False,
        "layout_review_reasons": [],
        "layout_reviewed_at": _now(),
        "layout_reviewed_by": "user",
        "layout_review_note": (
            note.strip() if isinstance(note, str) and note.strip()
            else "Layout confirmado manualmente na TUI."
        ),
        "profile_confirmed": True,
    })
    profile = _family_profiles.normalize_profile(profile)
    if profile.get("layout_review_required"):
        return (
            False,
            "a normalização manteve a revisão pendente: "
            + "; ".join(profile.get("layout_review_reasons") or []),
        )
    db[mac] = profile
    ok_save, result = _save(db)
    return (True, profile) if ok_save else (False, result)

def reset_physical_profiles() -> Result:
    """
    Remove todos os perfis por MAC e recria somente o registro reservado
    neutro. A operação é destrutiva, mas sempre gera backup verificado.
    """
    ok, db = _load()
    if not ok:
        return (False, db)
    count = len([key for key in db if key != DEFAULT_KEY])
    if count == 0:
        return (True, {
            "message": "o banco já não possui perfis físicos",
            "removed": 0,
            "backup": "",
        })

    ok_backup, backup = _backup_before_destructive()
    if not ok_backup:
        return (False, backup)

    clean = {DEFAULT_KEY: _family_profiles.build_neutral_default()}
    ok_save, result = _save(clean)
    if not ok_save:
        return (False, result)
    return (True, {
        "message": f"{count} perfil(is) físico(s) removido(s)",
        "removed": count,
        "backup": backup,
    })


def set_connection_status(mac: str, status: str) -> Result:
    """Grava o estado de conexão ao vivo de uma placa por MAC.

    Campo próprio (connection_status), independente da prontidão derivada
    do perfil. Não toca profile_confirmed nem layout. Idempotente: não
    regrava se o valor não mudou (evita churn no disco a cada varredura).
    """
    if not isinstance(mac, str) or not mac.strip():
        return (False, "MAC vazio ou inválido")
    mac = mac.strip().lower()
    if mac == DEFAULT_KEY:
        return (False, "o perfil reservado não possui estado de conexão")
    if status not in CONNECTION_STATUSES:
        return (False, f"status de conexão inválido: '{status}'")
    ok, db = _load()
    if not ok:
        return (False, db)
    if mac not in db:
        return (False, f"perfil com MAC '{mac}' inexistente")
    profile = _family_profiles.normalize_profile(db[mac])
    if profile.get("connection_status") == status:
        return (True, profile)
    profile["connection_status"] = status
    profile["connection_checked_at"] = _now()
    db[mac] = profile
    ok_save, res = _save(db)
    return (True, profile) if ok_save else (False, res)


def get_profile_readiness(mac: str) -> Result:
    """Retorna a prontidão derivada do perfil por MAC."""
    ok, profile = get_profile(mac)
    if not ok:
        return (False, profile)
    return (True, {
        "mac": profile.get("mac"),
        "board_name": profile.get("board_name"),
        "profile_ready": bool(profile.get("profile_ready")),
        "profile_readiness_status": profile.get("profile_readiness_status"),
        "profile_readiness_reasons": list(
            profile.get("profile_readiness_reasons") or []
        ),
    })


def validate_profile_against_chip(
    mac: str,
    chip_info: Dict[str, Any],
    *,
    require_ready: bool = True,
) -> Result:
    """Confere MAC/família vivos contra o perfil persistido."""
    ok, profile = get_profile(mac)
    if not ok:
        return (False, profile)
    validation = _family_profiles.validate_profile_against_chip(
        profile,
        chip_info,
        require_ready=require_ready,
    )
    return (True, validation)

def audit_profiles() -> Result:
    """Audita estrutura e prontidão sem alterar o JSON."""
    ok, db = _load()
    if not ok:
        return (False, db)
    result = []
    for mac, raw in db.items():
        if mac == DEFAULT_KEY:
            continue
        profile = _family_profiles.normalize_profile(raw)
        reasons = list(profile.get("layout_review_reasons") or [])
        result.append({
            "mac": mac,
            "board_name": profile.get("board_name") or "Não identificada",
            "chip_family": profile.get("chip_family") or UNKNOWN,
            "review_status": profile.get("layout_review_status"),
            "review_required": bool(profile.get("layout_review_required")),
            "reasons": reasons,
            "profile_ready": bool(profile.get("profile_ready")),
            "profile_readiness_status": profile.get(
                "profile_readiness_status"
            ),
            "profile_readiness_reasons": list(
                profile.get("profile_readiness_reasons") or []
            ),
        })
    return (True, result)

__all__ = [
    "key_json_manager", "find_or_create_by_mac",
    "get_profile", "get_default", "list_models", "list_profiles",
    "get_family_profile", "get_target_for_profile", "audit_profiles",
    "apply_family_reference_layout", "clear_profile_layout",
    "confirm_profile_layout", "reset_physical_profiles",
    "get_profile_readiness", "validate_profile_against_chip", "DEFAULT_KEY",
    "set_connection_status",
    "CONNECTION_CONNECTED", "CONNECTION_NOT_FOUND",
    "CONNECTION_UNCHECKED", "CONNECTION_STATUSES",
]

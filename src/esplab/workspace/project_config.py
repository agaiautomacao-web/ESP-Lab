#!/usr/bin/env python3
"""Metadados de projeto do ESP Lab — schema v2.

Flash, PSRAM, partição, CPU e depuração permanecem em sdkconfig.defaults.
`last_port` é histórico e nunca seleciona automaticamente a porta runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from ..core import storage as _storage

Result = Tuple[bool, Any]
SCHEMA_VERSION = 2
CONFIG_FILENAME = "project_config.json"
BOARD_PLACEHOLDER = "Não identificada"


def _now():
    return datetime.now(timezone.utc).isoformat()


def config_path(project_dir):
    return Path(project_dir).expanduser().resolve()/CONFIG_FILENAME


def default_config(project_name, idf_version):
    return {
        "schema_version":SCHEMA_VERSION,
        "project_name":project_name,
        "idf_version":idf_version,
        "target":"",
        "board_profile_mac":"",
        "board_name":BOARD_PLACEHOLDER,
        "last_port":"",
        "entry_point":"main/main.c",
        "libraries":[],
        "features":[],
        "auto_generate_pins_header":True,
        "created_at":None,
        "updated_at":None,
    }


def _normalize(data):
    cfg=dict(data)
    cfg.setdefault("schema_version",1)
    cfg.setdefault("target","")
    cfg.setdefault("board_profile_mac","")
    cfg.setdefault("board_name",BOARD_PLACEHOLDER)
    cfg.setdefault("last_port","")
    cfg.setdefault("entry_point","main/main.c")
    cfg.setdefault("libraries",[])
    cfg.setdefault("features",[])
    cfg.setdefault("auto_generate_pins_header",True)
    cfg.setdefault("created_at",None)
    cfg.setdefault("updated_at",None)
    return cfg


def create(project_dir, project_name, idf_version) -> Result:
    if not isinstance(project_name,str) or not project_name.strip():
        return False,"nome do projeto vazio ou inválido"
    if not isinstance(idf_version,str) or not idf_version.strip():
        return False,"versão ESP-IDF vazia ou inválida"
    path=config_path(project_dir)
    if path.is_file():
        return False,f"projeto já possui configuração em '{path}'"
    cfg=default_config(project_name.strip(),idf_version.strip())
    cfg["created_at"]=cfg["updated_at"]=_now()
    ok,res=_storage.atomic_write_json(path,cfg)
    return (True,cfg) if ok else (False,res)


def read(project_dir) -> Result:
    path=config_path(project_dir)
    if not path.is_file():
        return False,f"configuração de projeto inexistente em '{path}'"
    ok,data=_storage.read_json(path)
    if not ok:
        return False,data
    if not isinstance(data,dict):
        return False,"configuração de projeto corrompida"
    return True,_normalize(data)


def update(project_dir, changes) -> Result:
    if not isinstance(changes,dict):
        return False,"alterações devem ser dict"
    ok,cfg=read(project_dir)
    if not ok:
        return False,cfg
    created=cfg.get("created_at")
    cfg.update(changes)
    cfg["schema_version"]=SCHEMA_VERSION
    cfg["created_at"]=created
    cfg["updated_at"]=_now()
    ok,res=_storage.atomic_write_json(config_path(project_dir),cfg)
    return (True,cfg) if ok else (False,res)


def get_features(project_dir) -> Result:
    ok,cfg=read(project_dir)
    if not ok:
        return False,cfg
    value=cfg.get("features",[])
    return (True,value) if isinstance(value,list) else (
        False,"campo features corrompido"
    )


def set_features(project_dir, features) -> Result:
    if not isinstance(features,(list,tuple)):
        return False,"features devem ser uma lista"
    from ..programming import code_chip_validator as _ccv
    ok,known=_ccv.list_known_features()
    if not ok:
        return False,known
    valid=set(known); cleaned=[]; invalid=[]
    for item in features:
        name=str(item).strip().lower()
        if name in valid:
            if name not in cleaned:
                cleaned.append(name)
        else:
            invalid.append(name)
    if invalid:
        return False,"recurso(s) fora do catálogo: "+", ".join(invalid)
    return update(project_dir,{"features":cleaned})


def get_target(project_dir) -> Result:
    ok,cfg=read(project_dir)
    return (True,str(cfg.get("target") or "")) if ok else (False,cfg)


def set_target(project_dir, target) -> Result:
    if not isinstance(target,str) or not target.strip():
        return False,"target inválido"
    return update(project_dir,{"target":target.strip().lower()})


def get_board_association(project_dir) -> Result:
    ok,cfg=read(project_dir)
    if not ok:
        return False,cfg
    return True,{
        "board_profile_mac":str(cfg.get("board_profile_mac") or ""),
        "board_name":str(cfg.get("board_name") or BOARD_PLACEHOLDER),
        "last_port":str(cfg.get("last_port") or ""),
        "target":str(cfg.get("target") or ""),
    }


def set_board_association(project_dir, board_profile_mac,
                          board_name, last_port="") -> Result:
    if not isinstance(board_profile_mac,str) or not board_profile_mac.strip():
        return False,"MAC do perfil inválido"
    if not isinstance(last_port,str):
        return False,"last_port inválida"
    name=(board_name or BOARD_PLACEHOLDER)
    if not isinstance(name,str):
        return False,"board_name inválido"
    return update(project_dir,{
        "board_profile_mac":board_profile_mac.strip(),
        "board_name":name.strip() or BOARD_PLACEHOLDER,
        "last_port":last_port.strip(),
    })


def clear_board_association(project_dir) -> Result:
    return update(project_dir,{
        "board_profile_mac":"",
        "board_name":BOARD_PLACEHOLDER,
        "last_port":"",
        "target":"",
    })


def set_last_port(project_dir, last_port) -> Result:
    if not isinstance(last_port,str):
        return False,"last_port inválida"
    return update(project_dir,{"last_port":last_port.strip()})


__all__=[
    "create","read","update","config_path","default_config",
    "get_features","set_features","get_target","set_target",
    "get_board_association","set_board_association",
    "clear_board_association","set_last_port",
    "SCHEMA_VERSION","CONFIG_FILENAME","BOARD_PLACEHOLDER",
]

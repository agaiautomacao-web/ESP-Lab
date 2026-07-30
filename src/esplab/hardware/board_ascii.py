#!/usr/bin/env python3
"""Renderizador ASCII parametrizado por perfil, pinos físicos e USBs."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple

Result = Tuple[bool, Any]
LEGEND = {
    "A":"GPIO","B":"ADC","C":"Touch","D":"SPI",
    "E":"UART","F":"USB","G":"Strapping","H":"Octal",
}
CAT = {
    "gpio":"A","input":"A","adc":"B","touch":"C",
    "spi":"D","uart":"E","usb":"F","strapping":"G","octal":"H",
}


def _clip(value, width):
    text = str(value if value not in (None,"") else "?")
    return text if len(text) <= width else text[:max(1,width-1)] + "…"


def _legacy(pinout, total):
    data = deepcopy(pinout)
    nums = [p.get("physical") for p in data if isinstance(p,dict)]
    duplicate = len(nums) != len(set(nums))
    sides = all(
        isinstance(p,dict) and p.get("side") in ("left","right")
        for p in data
    )
    if duplicate and sides and len(data) % 2 == 0:
        left = sorted((p for p in data if p["side"]=="left"),
                      key=lambda p:p.get("physical",0))
        right = sorted((p for p in data if p["side"]=="right"),
                       key=lambda p:p.get("physical",0))
        inferred = total or len(data)
        if len(left)==len(right) and inferred==len(data):
            result = []
            for n,pin in enumerate(left,1):
                item=deepcopy(pin); item["physical"]=n; result.append(item)
            for i,pin in enumerate(right):
                item=deepcopy(pin); item["physical"]=inferred-i; result.append(item)
            return result, inferred, True
    valid = [n for n in nums if isinstance(n,int) and n>0]
    return data, int(total or max(valid,default=len(data))), False


def _identity_title(profile):
    """Titulo curto: familia do chip (ESP32-XX) + variante/modulo se houver
    (ex. WROOM-1) + revisao se existir. Nao usa o board_name completo."""
    fam=str(profile.get("chip_family") or profile.get("chip_type") or "ESP32").strip()
    parts=[fam or "ESP32"]
    for k in ("chip_variant","package_variant"):
        v=str(profile.get(k) or "").strip()
        if v and v not in ("Desconhecido","Nenhum") and v!=fam:
            parts.append(v); break
    rev=str(profile.get("chip_revision") or "").strip()
    if rev and rev not in ("Desconhecido","Nenhum"):
        parts.append(f"rev {rev}")
    return " · ".join(parts)


def _coerce(profile_or_pinout, title, usb_ports, total_pins, usb_port_count):
    if isinstance(profile_or_pinout,dict):
        profile=profile_or_pinout
        pinout=profile.get("pinout_mapping",[])
        title=title or _identity_title(profile)
        usb_ports=profile.get("usb_ports",[]) if usb_ports is None else usb_ports
        total_pins=profile.get("total_pins") if total_pins is None else total_pins
        usb_port_count=profile.get("usb_port_count") if usb_port_count is None else usb_port_count
    elif isinstance(profile_or_pinout,list):
        pinout=profile_or_pinout
        title=title or "ESP32"
        usb_ports=[] if usb_ports is None else usb_ports
    else:
        return False,"perfil/pinout inválido"

    if not isinstance(pinout,list):
        return False,"pinout_mapping não é uma lista"
    if not isinstance(usb_ports,list):
        return False,"usb_ports não é uma lista"
    pinout,total_pins,legacy=_legacy(pinout,total_pins)
    if not isinstance(total_pins,int) or isinstance(total_pins,bool):
        return False,"total_pins precisa ser inteiro"
    if total_pins<=0:
        return False,"layout físico indisponível: total_pins não definido"
    if total_pins%2:
        return False,"total_pins precisa ser par para duas fileiras"
    if usb_port_count is None:
        usb_port_count=len(usb_ports)
    if not isinstance(usb_port_count,int) or isinstance(usb_port_count,bool):
        return False,"usb_port_count precisa ser inteiro"
    if usb_port_count!=len(usb_ports):
        return False,"usb_port_count diverge da quantidade em usb_ports"
    if not 0<=usb_port_count<=2:
        return False,"o layout suporta de 0 a 2 portas USB"

    positions={}
    for pin in pinout:
        if not isinstance(pin,dict):
            return False,"pinout contém item inválido"
        n=pin.get("physical")
        if not isinstance(n,int) or isinstance(n,bool):
            return False,"há pino sem número físico inteiro"
        if not 1<=n<=total_pins:
            return False,f"posição física {n} fora de 1..{total_pins}"
        if n in positions:
            return False,f"posição física duplicada: {n}"
        positions[n]=pin
    return True,{
        "pinout":pinout,"positions":positions,"title":str(title),
        "usb_ports":usb_ports,"total_pins":total_pins,"legacy":legacy,
    }


def _pin_letters(pin):
    """Letras de funcao (canonicas A-H) do pino, excluindo A (GPIO), que ja
    aparece no corpo como GPIOxx."""
    values=[str(v) for v in (pin.get("functions") or []) if str(v) in LEGEND]
    if not values:
        value=CAT.get(str(pin.get("category") or ""))
        values=[value] if value else []
    return [v for v in values if v!="A"]


def _functions(pin, remap, reverse=False):
    mapped=sorted({remap[v] for v in _pin_letters(pin) if v in remap},
                  reverse=reverse)
    return "-".join(mapped)


def _inner(pin,digits,width):
    n=pin.get("physical")
    prefix=f"{n:>{digits}} " if isinstance(n,int) else " "*(digits+1)
    gpio=pin.get("gpio")
    if isinstance(gpio,int):
        label=f"GPIO{gpio}"
    else:
        label=str(pin.get("label") or "Não definido")
    return _clip(prefix+label,width)


def _bottom(width,ports):
    chars=["─"]*width
    labels=["["+_clip(p.get("nome") or p.get("name") or f"USB {i}",11)+"]"
            for i,p in enumerate(ports,1)]
    if len(labels)==1:
        starts=[(width-len(labels[0]))//2]
    elif len(labels)==2:
        starts=[max(0,width//4-len(labels[0])//2),
                min(width-len(labels[1]),3*width//4-len(labels[1])//2)]
    else:
        starts=[]
    for start,label in zip(starts,labels):
        for off,ch in enumerate(label):
            if 0<=start+off<width:
                chars[start+off]=ch
    return "└"+"".join(chars)+"┘"


def render(profile_or_pinout, title=None, usb_ports=None,
           total_pins=None, usb_port_count=None) -> Result:
    ok,data=_coerce(profile_or_pinout,title,usb_ports,total_pins,usb_port_count)
    if not ok:
        return False,data
    total=data["total_pins"]; half=total//2; pos=data["positions"]
    present=sorted({v for pin in data["pinout"] for v in _pin_letters(pin)})
    remap={orig: chr(ord("A")+i) for i,orig in enumerate(present)}
    digits=max(2,len(str(total))); pin_width=max(16,digits+13)
    outer=12; inner=pin_width*2+1
    title_text=_clip(data["title"],inner-4)
    free=inner-len(title_text)-2; left=max(1,free//2); right=max(1,free-left)
    lines=[" "*(outer+1)+"┌"+"─"*left+" "+title_text+" "+"─"*right+"┐"]
    placeholder={"gpio":None,"label":"Não definido","functions":[]}
    for row in range(half):
        ln=row+1; rn=total-row
        lp=deepcopy(pos.get(ln,placeholder)); rp=deepcopy(pos.get(rn,placeholder))
        lp.setdefault("physical",ln); rp.setdefault("physical",rn)
        lf=_functions(lp,remap,True); rf=_functions(rp,remap)
        left_col=_clip(lf,outer) if lf else ""
        right_col=_clip(rf,outer) if rf else ""
        lines.append(
            f"{left_col:>{outer}} "
            f"├{_inner(lp,digits,pin_width):<{pin_width}} "
            f"{_inner(rp,digits,pin_width):>{pin_width}}┤ "
            f"{right_col:<{outer}}"
        )
    lines.append(" "*(outer+1)+_bottom(inner,data["usb_ports"]))

    extras=[]
    if present:
        items=[f"{remap[v]}-{LEGEND[v]}" for v in present]
        extras.append("Legenda:\n  "+"\n  ".join(
            "   ".join(items[i:i+4]) for i in range(0,len(items),4)
        ))
    if data["usb_ports"]:
        usb=["Portas USB:"]
        for i,port in enumerate(data["usb_ports"],1):
            name=port.get("nome") or port.get("name") or f"USB {i}"
            gpios=", ".join(f"GPIO{g}" for g in (port.get("gpios") or []))
            kind=port.get("type") or ""
            detail=" · ".join(v for v in (kind,gpios) if v)
            usb.append(f"  {i}. {name}"+(f": {detail}" if detail else ""))
        extras.append("\n".join(usb))
    if data["legacy"]:
        extras.append(
            "Aviso: numeração antiga por lado foi convertida apenas para exibição."
        )
    text="\n".join(lines)
    if extras:
        text+="\n\n"+"\n\n".join(extras)
    return True,text+"\n"


__all__=["render","LEGEND"]

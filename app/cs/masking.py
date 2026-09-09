"""협업사 노출용 고객정보 마스킹 (요구사항 16·21).

협업사에게는 고객명/연락처/주소를 마스킹해 전달한다. 단, 해당 CS 건에서
관리자가 full_address_visible_to_partner=True 로 지정하면 주소 전체를 공개한다.
"""
import re


def mask_name(name: str | None) -> str:
    if not name:
        return "-"
    name = name.strip()
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def mask_phone(phone: str | None) -> str:
    if not phone:
        return "-"
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        return f"{digits[:3]}-****-{digits[-4:]}"
    if len(digits) >= 7:
        return f"{digits[:3]}-****"
    return "***"


def mask_address(addr: str | None, full: bool = False) -> str:
    """full=True 면 전체 공개, 아니면 시/도 + 시·군·구 수준까지만."""
    if not addr:
        return "-"
    addr = addr.strip()
    if full:
        return addr
    tokens = addr.split()
    if len(tokens) <= 2:
        return (tokens[0] if tokens else "") + " ***"
    return " ".join(tokens[:2]) + " ***"

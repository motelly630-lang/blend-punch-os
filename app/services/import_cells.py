"""Preserve explicit Excel percentage units and numeric zero during imports."""
from decimal import Decimal
import re


def spreadsheet_cell_text(cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        # Quoted/escaped percent signs are literal text, not percentage units.
        number_format = re.sub(r'"[^"]*"|\\.|_.|\*.|\[[^\]]*\]', "", cell.number_format or "")
        if "%" in number_format:
            return f"{Decimal(str(value)) * 100:f}%"
    return str(value).strip()

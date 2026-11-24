import unicodedata


def normalize_gtin(value):
    """Return the valid GTIN in its 14-digit representation, or an empty string."""
    digits = value.strip()
    if len(digits) not in {8, 12, 13, 14} or not digits.isascii() or not digits.isdigit():
        return ""
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(digits[:-1])))
    if not int(digits) or (total + int(digits[-1])) % 10:
        return ""
    return digits.zfill(14)


def search_text(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))

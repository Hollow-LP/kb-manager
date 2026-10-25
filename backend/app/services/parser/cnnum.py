"""汉字数字 <-> int，用于解析"第一章 / 第二节 / 一、"等标题编号。"""

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(text: str) -> int | None:
    """'一' -> 1, '十二' -> 12, '一百零五' -> 105, '10' -> 10；无法解析返回 None。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(ch not in _CN_DIGITS and ch not in _CN_UNITS for ch in text):
        return None
    total, current = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        else:
            total += (current or 1) * _CN_UNITS[ch]
            current = 0
    return total + current

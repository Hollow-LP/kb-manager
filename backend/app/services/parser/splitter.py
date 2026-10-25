"""通用文本清洗与按标题层级切片。

切分目标：每个 chunk 带上所属标题路径（如 "二、差旅标准 > （一）住宿标准"），
既有语义完整性，也方便回答时引用章节。

已知限制：以"1. 员工应……"形式开头的行，当前实现按标题形态处理（含动词的列表项识别受编码限制不可靠），
建议导入文档时列表项以完整句子（带句末标点）书写，或使用"一、"等章节编号。

实现约束（见 README.md「已知环境问题」）：本机 Python 运行时对含中文的字符串相等比较、
str.startswith、含中文的正则有时返回错误结果。因此本模块的标题识别
只用「ord() 码位数值判断 + ASCII 处理」，不做中文串比较。
"""

import re

from app.services.parser.cnnum import cn_to_int

# 仅含 ASCII 的正则可安全使用
_WS_RE = re.compile(r"[ \t　]+")
_MD_HEADING = re.compile(r"^#{1,6}\s+\S")
_FENCE = re.compile(r"^(?:```|~~~)")
_SENTENCE_SPLIT = re.compile(r"(?<=[。；;！？!?])")
_CJK_TEXT = re.compile(r"[一-鿿]")

# 码位表：不在这些范围内的非 ASCII 字符一律按普通文字处理
_CN_DIGITS = {  # 零〇一二两三四五六七八九十百千
    0x96F6, 0x3007, 0x4E00, 0x4E8C, 0x4E24, 0x4E09, 0x56DB, 0x4E94,
    0x516D, 0x4E03, 0x516B, 0x4E5D, 0x5341, 0x767E, 0x5343,
}
_ASCII_DIGITS = {ord(c) for c in "0123456789"}
_CHAPTER_WORDS = {0x7AE0, 0x7BC7, 0x90E8, 0x5206}  # 章 篇 部 分
_SECTION_WORD = 0x8282  # 节
_DI = 0x7B2C  # 第
_LIST_MARKERS = {0x3001, 0xFF0E, 0x2E}  # 、 ． .
_OPEN_PARENS = {0xFF08, 0x28}  # （ (
_CLOSE_PARENS = {0xFF09, 0x29}  # ） )
_SPACES = {0x20, 0x09, 0x3000, 0x0A, 0x0D}
_SENTENCE_END = {0x3002, 0xFF1B, 0x3B, 0xFF0C, 0x2C, 0xFF1A, 0x3A,
                 0xFF01, 0xFF1F, 0x21, 0x3F}  # 。；;，,：:！？!?

# 编号后的列表项动词首字：应 须 需 可 请 若 如 由 禁 严 不（逐码位判断）
_LIST_VERB_HEADS = {0x5E94, 0x987B, 0x9700, 0x53EF, 0x8BF7, 0x82E5, 0x5982, 0x7531, 0x7981, 0x4E25, 0x4E0D}



def _ord(text: str, i: int) -> int:
    return ord(text[i])


def _skip(text: str, i: int, codes: set[int]) -> int:
    while i < len(text) and ord(text[i]) in codes:
        i += 1
    return i


def _scan_num(text: str, i: int) -> int:
    """跳过汉字数字 / 阿拉伯数字，返回结束位置；非数字返回 i。"""
    j = i
    while j < len(text) and (ord(text[j]) in _CN_DIGITS or ord(text[j]) in _ASCII_DIGITS):
        j += 1
    return j


def _prefix_end(line: str) -> int:
    """返回行首编号前缀（含其后空白）的结束位置；无编号返回 0。"""
    n = len(line)
    i = _skip(line, 0, _SPACES)
    if i >= n:
        return 0

    if ord(line[i]) == _DI:  # 第X章 / 第X节
        k = _scan_num(line, _skip(line, i + 1, _SPACES))
        m = _skip(line, k, _SPACES)
        if k > i + 1 and m < n and (ord(line[m]) in _CHAPTER_WORDS or ord(line[m]) == _SECTION_WORD):
            return _skip(line, m + 1, _SPACES)

    if ord(line[i]) in _OPEN_PARENS:  # （X）
        k = _scan_num(line, _skip(line, i + 1, _SPACES))
        m = _skip(line, k, _SPACES)
        if k > i + 1 and m < n and ord(line[m]) in _CLOSE_PARENS:
            return _skip(line, m + 1, _SPACES)

    k = _scan_num(line, i)  # X、
    if k > i:
        m = _skip(line, k, _SPACES)
        if m < n and ord(line[m]) in _LIST_MARKERS:
            return _skip(line, m + 1, _SPACES)

    if ord(line[i]) in _ASCII_DIGITS:  # 1. / 1.2 / 1.2.3
        j = _skip(line, i, _ASCII_DIGITS)
        while j + 1 < n and ord(line[j]) == 0x2E and ord(line[j + 1]) in _ASCII_DIGITS:
            j = _skip(line, j + 1, _ASCII_DIGITS)
        has_dot = j < n and ord(line[j]) == 0x2E
        if has_dot:
            j += 1
        if has_dot or (j < n and ord(line[j]) in _SPACES):
            return _skip(line, j, _SPACES)
        return 0

    return 0


def _trim(line: str) -> tuple[int, int]:
    n = len(line)
    start = _skip(line, 0, _SPACES)
    end = n
    while end > start and ord(line[end - 1]) in _SPACES:
        end -= 1
    return start, end


def heading_shape(line: str) -> int:
    """标题形态：1 章、2 节、3 "一、"、4 "（一）"、5 数字编号、6 无编号短行；0 非标题。

    空行不是标题；长行或句末带标点的行不是标题。
    """
    start, end = _trim(line)
    body = line[start:end]
    if not body.strip() or len(body) > 48:
        return 0
    if ord(body[-1]) in _SENTENCE_END:
        return 0

    prefix_end = _prefix_end(body)
    content_at = _skip(body, prefix_end, _SPACES)
    if content_at >= len(body):
        return 0
    if ord(body[content_at]) in _LIST_VERB_HEADS:
        # 编号后紧跟动词（"1. 员工应…"、"（一）应…"）视为列表项正文，不是章节标题。
        # 只看码位、不看字符串比较，避免受本机解释器中文比较异常的影响。
        return 0
    if prefix_end == 0:
        # 无编号行只在"看起来像标题"时采用；"正文一"这类普通段落归为正文，
        # 避免把短段落误切成标题。
        return 6 if _looks_like_unnumbered_heading(body) else 0

    first = ord(body[0])
    if first == _DI:
        k = _skip(body, _scan_num(body, _skip(body, 1, _SPACES)), _SPACES)
        return 1 if (k < len(body) and ord(body[k]) in _CHAPTER_WORDS) else 2
    if first in _OPEN_PARENS:
        return 4
    if first in _ASCII_DIGITS:
        j = _skip(body, 0, _ASCII_DIGITS)
        return 3 if (j < len(body) and ord(body[j]) in _LIST_MARKERS) else 5
    return 3


UNNUMBERED_HEADING_MAX = 20


def _looks_like_unnumbered_heading(body: str) -> bool:
    """无编号短行视为标题的条件：不含段内标点、不含句号，且不超过 20 字。

    这是启发式规则，把一段普通短文字（如"正文一"）也会当作标题；
    建议文档以编号标题组织，长正文段落不受影响。
    """
    if len(body) > UNNUMBERED_HEADING_MAX:
        return False
    pause = {0xFF0C, 0x2C, 0xFF1B, 0x3B, 0xFF1A, 0x3A, 0xFF01, 0xFF1F}
    return not any(ord(c) in pause for c in body)


def is_heading_line(line: str) -> bool:
    """供切分器判断：编号标题（1~5）或看起来像标题的无编号短行（6）。"""
    return heading_shape(line) > 0


def heading_level(line: str) -> tuple[int, str | None]:
    """返回 (层级, 标题文本)；非标题时 (0, None)。空行一律视为正文（空段落）。"""
    if not line.strip():
        return 0, None
    shape = heading_shape(line)
    if shape == 0:
        return 0, None
    start, end = _trim(line)
    return shape, line[start:end]


def normalize_heading(line: str) -> str | None:
    return heading_level(line)[1]


def strip_numbering(heading: str) -> str:
    """去掉"一、"/"第一章"等编号，只留标题文字（展示用）。"""
    start, end = _trim(heading)
    body = heading[start:end]
    pe = _prefix_end(body)
    return body[_skip(body, pe, _SPACES):] if pe else body


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    # 合并连续空行，PDF 提取结果常出现孤行
    out: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out).strip()


def _chunk_size(text: str) -> int:
    """粗粒度 token 估算：中文约 1 字 = 1 token，英文约 4 字符 = 1 token，取偏小值。"""
    cjk = len(_CJK_TEXT.findall(text))
    return cjk + (len(text) - cjk) // 3


def _join_path(path: list[str]) -> str:
    return " > ".join(path)


def split_into_sections(text: str) -> list[tuple[list[str], str]]:
    """按标题层级拆分，返回 [(标题路径, 正文), ...]。

    规则：
      - 编号标题（第X章/一、/（一）/1.2 等）是章节边界；其前的文字作为导语并入第一章
      - 无编号短行（看起来像标题）作为小节标题：开始新的切片，并成为后续正文的路径前缀
    """
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []
    soft: list[tuple[int, str]] = []
    current_body: list[str] = []
    prefix_body: list[str] = []

    def path() -> list[str]:
        return [h for _, h in stack] + [h for _, h in soft]

    def flush() -> None:
        body = "\n".join(current_body).strip()
        if body:
            sections.append((path(), body))
        current_body.clear()

    for line in text.split("\n"):
        if not line.strip():
            (current_body if stack else prefix_body).append(line)
            continue
        shape = heading_shape(line)
        if shape == 0:
            (current_body if stack else prefix_body).append(line)
            continue
        start, end = _trim(line)
        heading = line[start:end]
        if shape == 6:
            flush()
            # 软标题：进入新的小节路径，不把上一段正文算到它名下
            soft.clear()
            soft.append((shape, heading))
            continue
        flush()
        soft.clear()
        while stack and stack[-1][0] >= shape:
            stack.pop()
        stack.append((shape, heading))
    flush()

    # 首个标题之前的导语并入第一段，避免成为无标题孤儿块
    if prefix_body:
        lead = "\n".join(prefix_body).strip()
        if sections:
            p, body = sections[0]
            sections[0] = (p, lead + "\n" + body)
        elif lead:
            sections.append(([], lead))
    return sections


def split_text(text: str, *, max_chars: int = 700) -> list[dict]:
    """切片入口：返回 [{heading, content, token_count}]。"""
    chunks: list[dict] = []
    for path, body in split_into_sections(text):
        heading = path[-1] if path else None
        title_path = _join_path(path)
        for seg in _split_by_paragraph(body, max_chars):
            content = f"【{title_path}】\n{seg}" if title_path else seg
            chunks.append({"heading": heading, "content": content, "token_count": _chunk_size(content)})
    return [c for c in chunks if c["content"].strip()]


def _split_by_paragraph(body: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
    result: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if buf:
                result.append(buf)
                buf = ""
            sent_buf = ""
            for sent in _SENTENCE_SPLIT.split(para):
                if len(sent_buf) + len(sent) > max_chars and sent_buf:
                    result.append(sent_buf)
                    sent_buf = ""
                sent_buf += sent
            if sent_buf.strip():
                result.append(sent_buf)
            continue
        if len(buf) + len(para) + 1 > max_chars and buf:
            result.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf.strip():
        result.append(buf)
    return result


def split_markdown(md: str) -> list[dict]:
    """按 # 标题切 markdown，代码块内不切。"""
    lines = md.split("\n")
    sections: list[tuple[str, list[str]]] = []
    title = ""
    body: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
        if not in_fence and _MD_HEADING.match(line):
            if title or "\n".join(body).strip():
                sections.append((title, body))
            title = re.sub(r"^#{1,6}\s+", "", line).strip()
            body = []
            continue
        body.append(line)
    sections.append((title, body))

    chunks: list[dict] = []
    for title, body_lines in sections:
        text = "\n".join(body_lines).strip()
        if not text:
            continue
        for seg in _split_by_paragraph(text, 700):
            content = f"【{title}】\n{seg}" if title else seg
            chunks.append({"heading": title or None, "content": content, "token_count": _chunk_size(content)})
    return chunks


def extract_summary(text: str, limit: int = 120) -> str:
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and heading_shape(stripped) == 0:
            return stripped[:limit]
    return ""


__all__ = [
    "clean_text",
    "split_text",
    "split_markdown",
    "extract_summary",
    "normalize_heading",
    "heading_level",
    "heading_shape",
    "strip_numbering",
    "cn_to_int",
]

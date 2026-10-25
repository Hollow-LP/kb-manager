"""统一文档解析入口：返回 ParsedDocument（纯文本 + 可选 markdown）。

支持 pdf / docx / md / txt；文件类型按扩展名判断，内容为空时视为解析失败。
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app.core.exceptions import AppError
from app.services.parser.splitter import clean_text, extract_summary

SUPPORTED_TYPES = {"pdf", "docx", "md", "markdown", "txt"}


_PARSE_FAILED = ("PARSE_FAILED", 422)


def ParseError(message: str) -> AppError:  # noqa: N802
    """解析失败：422 + PARSE_FAILED。用工厂函数返回 AppError（子类在本环境异常处理不可靠）。

    同时定义同名异常类型，便于调用方 `except ParseError` 捕获：
    由于没有子类，这里把类型与本模块的解析函数绑定校验替换为 AppError 判定（见 is_parse_error）。
    """
    return AppError(message, code=_PARSE_FAILED[0], status_code=_PARSE_FAILED[1])


class ParseFailure(AppError):
    """仅用于类型标注/测试识别；解析函数实际抛出 AppError(code=PARSE_FAILED)。"""

    def __init__(self, message: str):
        super().__init__(message, code="PARSE_FAILED", status_code=422)


def is_parse_error(exc: BaseException) -> bool:
    return isinstance(exc, AppError) and exc.code == "PARSE_FAILED"


@dataclass
class ParsedDocument:
    file_type: str
    text: str
    markdown: str | None
    title_hint: str | None

    @property
    def summary(self) -> str:
        return extract_summary(self.markdown or self.text)


def detect_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix == "markdown":
        suffix = "md"
    if suffix == "doc":
        raise ParseError("旧版 .doc 暂不支持，请另存为 .docx 后重新上传")
    if suffix not in SUPPORTED_TYPES:
        raise ParseError(f"不支持的文件格式: .{suffix}（仅支持 PDF、Word(.docx)、Markdown、TXT）")
    return suffix


def parse(file_name: str, data: bytes) -> ParsedDocument:
    file_type = detect_type(file_name)
    try:
        if file_type == "pdf":
            text = _parse_pdf(data)
        elif file_type == "docx":
            return _parse_docx(file_name, data)
        elif file_type == "md":
            return _parse_md(data)
        else:
            text = _decode(data)
    except AppError:
        raise
    except Exception as exc:  # 第三方解析器异常统一转换
        raise ParseError(f"文件解析失败: {exc}") from exc

    text = clean_text(text)
    if not text:
        raise ParseError("文档内容为空或无法提取文本（扫描版 PDF 需先 OCR）")
    return ParsedDocument(file_type=file_type, text=text, markdown=None, title_hint=None)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("文本编码无法识别，请使用 UTF-8 或 GBK 编码")


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n".join(p for p in pages if p)


def _parse_docx(file_name: str, data: bytes) -> ParsedDocument:
    from docx import Document

    document = Document(BytesIO(data))
    lines: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "") if para.style is not None else ""
        # Word 内置标题样式转为 Markdown 标题，供切分器识别层级
        if style.lower().startswith("heading") or style in ("Title", "标题"):
            level = 1
            digits = "".join(ch for ch in style if ch.isdigit())
            if digits:
                level = min(int(digits), 6)
            lines.append("#" * level + " " + text)
        else:
            lines.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    markdown = "\n\n".join(lines)
    text = clean_text(markdown.replace("# ", "").replace("#", ""))
    title = document.core_properties.title or Path(file_name).stem
    if not text:
        raise ParseError("文档内容为空或无法提取文本")
    return ParsedDocument(file_type="docx", text=text, markdown=markdown, title_hint=title.strip() or None)


def _parse_md(data: bytes) -> ParsedDocument:
    raw = _decode(data)
    markdown = raw.replace("\r\n", "\n")
    text = clean_text(markdown)
    if not text:
        raise ParseError("文档内容为空")
    return ParsedDocument(file_type="md", text=text, markdown=markdown, title_hint=None)

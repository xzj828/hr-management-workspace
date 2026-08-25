import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium


class ExtractionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int | None
    section: str
    bbox: list[float] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    method: str
    plain_text: str
    blocks: list[dict]


def _serialize_blocks(blocks: list[TextBlock]) -> list[dict]:
    return [
        {
            "id": f"block-{index}",
            "text": block.text,
            "page": block.page,
            "section": block.section,
            "bbox": block.bbox,
        }
        for index, block in enumerate(blocks, start=1)
        if block.text.strip()
    ]


def _result(method: str, blocks: list[TextBlock]) -> ExtractionResult:
    serialized = _serialize_blocks(blocks)
    return ExtractionResult(
        method=method,
        plain_text="\n".join(block["text"] for block in serialized),
        blocks=serialized,
    )


def _iter_docx_blocks(document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def extract_docx(path: Path) -> ExtractionResult:
    try:
        document = Document(str(path))
    except Exception as exc:
        raise ExtractionError("invalid_docx", "无法读取 DOCX 文档，请确认文件未损坏") from exc
    blocks = []
    for item in _iter_docx_blocks(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style_name = str(getattr(item.style, "name", "") or "").lower()
            section = "heading" if style_name.startswith("heading") else "paragraph"
            blocks.append(TextBlock(text=text, page=None, section=section))
            continue
        for row in item.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                blocks.append(TextBlock(text=" | ".join(cells), page=None, section="table"))
    return _result("docx", blocks)


class LibreOfficeConverter:
    def __init__(self, executable: str | None = None):
        self.executable = executable

    def _find(self):
        candidates = [
            self.executable,
            shutil.which("soffice"),
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        return next((str(path) for path in candidates if path and Path(path).exists()), None)

    def convert(self, source, output_dir):
        executable = self._find()
        if not executable:
            raise FileNotFoundError("LibreOffice soffice was not found")
        try:
            subprocess.run(
                [executable, "--headless", "--convert-to", "docx", "--outdir", str(output_dir), str(source)],
                check=True,
                capture_output=True,
                timeout=60,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExtractionError("doc_conversion_failed", "旧版 DOC 转换失败，请另存为 DOCX 后重试") from exc
        converted = Path(output_dir) / f"{Path(source).stem}.docx"
        if not converted.is_file():
            raise ExtractionError("doc_conversion_failed", "旧版 DOC 转换未生成有效 DOCX 文件")
        return converted


class RapidOcrAdapter:
    def __init__(self):
        try:
            from rapidocr import RapidOCR
            self.engine = RapidOCR()
        except Exception as exc:
            raise ExtractionError("ocr_unavailable", "本地 OCR 引擎初始化失败") from exc

    def read(self, image):
        import numpy as np

        try:
            output = self.engine(np.asarray(image))
        except Exception as exc:
            raise ExtractionError("ocr_failed", "本地 OCR 识别失败") from exc
        texts = getattr(output, "txts", None)
        boxes = getattr(output, "boxes", None)
        scores = getattr(output, "scores", None)
        if texts is None and isinstance(output, (list, tuple)) and output:
            rows = output[0] if isinstance(output[0], list) else output
            normalized = []
            for row in rows or []:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    normalized.append({"bbox": row[0], "text": row[1], "confidence": row[2] if len(row) > 2 else None})
            return normalized
        normalized = []
        for index, text in enumerate(texts or []):
            box = boxes[index] if boxes is not None and index < len(boxes) else None
            if box is not None:
                flat = [float(value) for point in box for value in point]
                box = [min(flat[0::2]), min(flat[1::2]), max(flat[0::2]), max(flat[1::2])]
            normalized.append(
                {
                    "text": str(text),
                    "bbox": box,
                    "confidence": float(scores[index]) if scores is not None and index < len(scores) else None,
                }
            )
        return normalized


def _ocr_blocks(image, *, ocr, page: int | None) -> list[TextBlock]:
    engine = ocr or RapidOcrAdapter()
    blocks = []
    for row in engine.read(image) or []:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        bbox = row.get("bbox")
        blocks.append(
            TextBlock(
                text=text,
                page=page,
                section="ocr",
                bbox=[float(value) if isinstance(value, float) else value for value in bbox] if bbox else None,
            )
        )
    return blocks


def extract_image(path: Path, *, ocr=None) -> ExtractionResult:
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            blocks = _ocr_blocks(image, ocr=ocr, page=1)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("invalid_image", "无法读取简历图片") from exc
    if not blocks:
        raise ExtractionError("ocr_no_text", "未能从简历图片中识别出文字")
    return _result("image_ocr", blocks)


def extract_pdf(path: Path, *, ocr=None) -> ExtractionResult:
    try:
        reader = PdfReader(str(path))
        page_texts = [str(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ExtractionError("invalid_pdf", "无法读取 PDF 简历") from exc
    combined = "".join(page_texts)
    if len("".join(combined.split())) >= 80:
        blocks = []
        for page_number, text in enumerate(page_texts, start=1):
            for line in text.splitlines():
                if line.strip():
                    blocks.append(TextBlock(text=line.strip(), page=page_number, section="paragraph"))
        return _result("pdf_text", blocks)

    try:
        document = pdfium.PdfDocument(str(path))
        blocks = []
        try:
            for page_number in range(len(document)):
                page = document[page_number]
                bitmap = None
                try:
                    bitmap = page.render(scale=2)
                    image = bitmap.to_pil().convert("RGB")
                    blocks.extend(_ocr_blocks(image, ocr=ocr, page=page_number + 1))
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        finally:
            document.close()
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("pdf_render_failed", "扫描 PDF 页面渲染失败") from exc
    if not blocks:
        raise ExtractionError("ocr_no_text", "未能从扫描 PDF 中识别出文字")
    return _result("pdf_ocr", blocks)


def extract_file(path: Path, *, content_type: str, ocr=None, converter=None) -> ExtractionResult:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".doc":
        with TemporaryDirectory() as directory:
            try:
                converted = (converter or LibreOfficeConverter()).convert(path, Path(directory))
            except FileNotFoundError as exc:
                raise ExtractionError(
                    "libreoffice_unavailable",
                    "当前设备未安装 LibreOffice，请将旧版 DOC 另存为 DOCX 后重试",
                ) from exc
            result = extract_docx(Path(converted))
            return replace(result, method="doc_convert")
    if content_type == "application/pdf" or suffix == ".pdf":
        return extract_pdf(path, ocr=ocr)
    if content_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg"}:
        return extract_image(path, ocr=ocr)
    raise ExtractionError("unsupported_file_type", "不支持的文件类型")

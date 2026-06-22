import logging
import mimetypes
import os

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    pass

try:
    import magic
    _magic_available = True
except ImportError:
    _magic_available = False
    logger.warning("python-magic not available, falling back to mimetypes")


def _detect_mime(file_path: str) -> str:
    if _magic_available:
        try:
            return magic.from_file(file_path, mime=True)
        except Exception:
            pass
    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/octet-stream"


class FileConverter:
    def convert(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        mime = _detect_mime(file_path)
        logger.info("Converting %s (ext=%s, mime=%s)", file_path, ext, mime)

        # Try markitdown first
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(file_path)
            text = result.text_content
            if text and text.strip():
                logger.info("markitdown succeeded for %s", file_path)
                return text
            logger.warning("markitdown returned empty result for %s", file_path)
        except Exception as e:
            logger.warning("markitdown failed for %s: %s", file_path, e)

        # Fallback: pypandoc
        try:
            import pypandoc
            pandoc_formats = {
                ".docx": "docx", ".doc": "doc", ".odt": "odt",
                ".rtf": "rtf", ".html": "html", ".htm": "html",
                ".txt": "plain", ".tex": "latex",
                ".epub": "epub", ".rst": "rst", ".md": "markdown",
            }
            fmt = pandoc_formats.get(ext)
            if fmt:
                text = pypandoc.convert_file(file_path, "markdown", format=fmt)
                if text and text.strip():
                    logger.info("pypandoc succeeded for %s", file_path)
                    return text
                logger.warning("pypandoc returned empty result for %s", file_path)
            else:
                logger.info("pypandoc skipped — unsupported extension %s", ext)
        except Exception as e:
            logger.warning("pypandoc failed for %s: %s", file_path, e)

        # Fallback: python-pptx for .pptx/.ppt
        try:
            if ext in (".pptx", ".ppt"):
                from pptx import Presentation
                prs = Presentation(file_path)
                lines = []
                for i, slide in enumerate(prs.slides, 1):
                    lines.append(f"## Слайд {i}")
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            lines.append(shape.text.strip())
                    lines.append("")
                text = "\n".join(lines)
                if text.strip():
                    logger.info("python-pptx succeeded for %s", file_path)
                    return text
        except Exception as e:
            logger.warning("python-pptx failed for %s: %s", file_path, e)

        # Fallback: openpyxl for .xlsx/.xls
        try:
            if ext in (".xlsx", ".xls"):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                lines = []
                for sheet in wb.worksheets:
                    lines.append(f"## {sheet.title}")
                    for row in sheet.iter_rows(values_only=True):
                        row_text = " | ".join(str(c) for c in row if c is not None)
                        if row_text.strip():
                            lines.append(row_text)
                    lines.append("")
                text = "\n".join(lines)
                if text.strip():
                    logger.info("openpyxl succeeded for %s", file_path)
                    return text
        except Exception as e:
            logger.warning("openpyxl failed for %s: %s", file_path, e)

        raise ConversionError(
            f"Не удалось конвертировать {os.path.basename(file_path)}. "
            f"Тип: {mime} ({ext}). "
            "Возможные причины: формат не поддерживается, файл повреждён или защищён паролем."
        )

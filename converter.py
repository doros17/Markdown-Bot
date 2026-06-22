import concurrent.futures
import logging
import mimetypes
import os
import zipfile

logger = logging.getLogger(__name__)

CONVERSION_TIMEOUT = int(os.getenv("CONVERSION_TIMEOUT_SEC", "60"))
MAX_UNCOMPRESSED_ZIP_MB = int(os.getenv("MAX_UNCOMPRESSED_ZIP_MB", "200"))


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


def _check_zip_safety(file_path: str, max_uncompressed_mb: int = MAX_UNCOMPRESSED_ZIP_MB) -> None:
    """Проверяет ZIP на bomb и path traversal (Zip Slip)."""
    max_bytes = max_uncompressed_mb * 1024 * 1024
    total = 0
    with zipfile.ZipFile(file_path) as zf:
        for info in zf.infolist():
            if os.path.isabs(info.filename) or ".." in info.filename:
                logger.warning("ZIP bomb detected (path traversal): %s in %s", info.filename, file_path)
                raise ValueError(f"Архив содержит небезопасный путь: {info.filename}")
            total += info.file_size
            if total > max_bytes:
                logger.warning("ZIP bomb detected: uncompressed size >%dMB in %s", max_uncompressed_mb, file_path)
                raise ValueError(
                    f"Архив слишком большой после распаковки "
                    f"(>{max_uncompressed_mb} МБ). Отправь файлы по отдельности."
                )


def sanitize_for_llm(text: str) -> str:
    """
    Оборачивает пользовательский контент в теги чтобы LLM
    не воспринимал инструкции внутри документа как системные команды.
    """
    return f"<document>\n{text}\n</document>"


class FileConverter:
    def _run_markitdown(self, file_path: str) -> str:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content or ""

    def _run_pypandoc(self, file_path: str, fmt: str) -> str:
        import pypandoc
        return pypandoc.convert_file(file_path, "markdown", format=fmt)

    def convert(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        mime = _detect_mime(file_path)
        logger.info("Converting %s (ext=%s, mime=%s)", file_path, ext, mime)

        # ZIP safety check before any extraction
        if ext == ".zip":
            try:
                _check_zip_safety(file_path)
            except ValueError as e:
                raise ConversionError(str(e))

        _timeout_msg = (
            f"❌ Файл слишком сложный для обработки "
            f"(превышен лимит {CONVERSION_TIMEOUT} сек).\n"
            "Попробуй разбить документ на части."
        )

        # 1. markitdown
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._run_markitdown, file_path)
                try:
                    text = future.result(timeout=CONVERSION_TIMEOUT)
                    if text and text.strip():
                        logger.info("markitdown succeeded for %s", file_path)
                        # TODO: использовать sanitize_for_llm(text) при вызовах LLM
                        return text
                    logger.warning("markitdown returned empty result for %s", file_path)
                except concurrent.futures.TimeoutError:
                    logger.warning("Conversion timeout for %s", file_path)
                    raise ConversionError(_timeout_msg)
        except ConversionError:
            raise
        except Exception as e:
            logger.warning("markitdown failed for %s: %s", file_path, e)

        # 2. pypandoc
        pandoc_formats = {
            ".docx": "docx", ".doc": "doc", ".odt": "odt",
            ".rtf": "rtf", ".html": "html", ".htm": "html",
            ".txt": "plain", ".tex": "latex",
            ".epub": "epub", ".rst": "rst", ".md": "markdown",
        }
        fmt = pandoc_formats.get(ext)
        if fmt:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._run_pypandoc, file_path, fmt)
                    try:
                        text = future.result(timeout=CONVERSION_TIMEOUT)
                        if text and text.strip():
                            logger.info("pypandoc succeeded for %s", file_path)
                            return text
                        logger.warning("pypandoc returned empty result for %s", file_path)
                    except concurrent.futures.TimeoutError:
                        logger.warning("Pypandoc timeout for %s", file_path)
                        raise ConversionError(_timeout_msg)
            except ConversionError:
                raise
            except Exception as e:
                logger.warning("pypandoc failed for %s: %s", file_path, e)
        else:
            logger.info("pypandoc skipped — unsupported extension %s", ext)

        # 3. python-pptx for .pptx/.ppt
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

        # 4. openpyxl for .xlsx/.xls
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

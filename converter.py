import logging
import mimetypes
import os
import platform
import signal
import zipfile
from contextlib import contextmanager

logger = logging.getLogger(__name__)

CONVERSION_TIMEOUT_SEC = int(os.getenv("CONVERSION_TIMEOUT_SEC", "60"))
MAX_UNCOMPRESSED_ZIP_MB = int(os.getenv("MAX_UNCOMPRESSED_ZIP_MB", "200"))


class ConversionError(Exception):
    pass


try:
    import magic
    _magic_available = True
except ImportError:
    _magic_available = False
    logger.warning("python-magic not available, falling back to mimetypes")


@contextmanager
def _time_limit(seconds: int):
    def _handler(signum, frame):
        raise TimeoutError(f"Конвертация превысила лимит {seconds} секунд")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


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
                raise ValueError(
                    f"Архив содержит небезопасный путь: {info.filename}"
                )
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

        use_timeout = platform.system() != "Windows"

        try:
            if use_timeout:
                ctx = _time_limit(CONVERSION_TIMEOUT_SEC)
            else:
                from contextlib import nullcontext
                ctx = nullcontext()

            with ctx:
                # 1. markitdown
                try:
                    from markitdown import MarkItDown
                    md = MarkItDown()
                    result = md.convert(file_path)
                    text = result.text_content
                    if text and text.strip():
                        logger.info("markitdown succeeded for %s", file_path)
                        # TODO: использовать sanitize_for_llm(text) при вызовах LLM
                        return text
                    logger.warning("markitdown returned empty result for %s", file_path)
                except TimeoutError:
                    raise
                except Exception as e:
                    logger.warning("markitdown failed for %s: %s", file_path, e)

                # 2. pypandoc
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
                except TimeoutError:
                    raise
                except Exception as e:
                    logger.warning("pypandoc failed for %s: %s", file_path, e)

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
                except TimeoutError:
                    raise
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
                except TimeoutError:
                    raise
                except Exception as e:
                    logger.warning("openpyxl failed for %s: %s", file_path, e)

        except TimeoutError as e:
            raise ConversionError(
                f"Файл слишком сложный для обработки (превышен лимит времени {CONVERSION_TIMEOUT_SEC} сек). "
                "Попробуй разбить документ на части."
            ) from e

        raise ConversionError(
            f"Не удалось конвертировать {os.path.basename(file_path)}. "
            f"Тип: {mime} ({ext}). "
            "Возможные причины: формат не поддерживается, файл повреждён или защищён паролем."
        )

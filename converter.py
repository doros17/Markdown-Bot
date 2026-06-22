import logging
import mimetypes
import os

logger = logging.getLogger(__name__)

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

        return (
            f"❌ Не удалось конвертировать файл `{os.path.basename(file_path)}`.\n\n"
            f"Тип файла: `{mime}` (`{ext}`)\n\n"
            "Возможные причины:\n"
            "- Формат не поддерживается\n"
            "- Файл повреждён или защищён паролем\n"
            "- Отсутствуют необходимые системные зависимости (pandoc, poppler-utils)\n"
        )

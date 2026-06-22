import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from converter import FileConverter

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/markdown_bot")

START_TEXT = (
    "👋 Привет! Я конвертирую файлы в Markdown.\n\n"
    "📄 Поддерживаемые форматы:\n\n"
    "• Документы: PDF, DOCX, DOC, ODT, RTF\n"
    "• Презентации: PPTX, PPT, ODP\n"
    "• Таблицы: XLSX, XLS, ODS, CSV\n"
    "• Веб / разметка: HTML, HTM, XML, JSON\n"
    "• Текст: TXT\n"
    "• Изображения (OCR): JPG, PNG, GIF, BMP, TIFF\n"
    "• Аудио (транскрипция): MP3, WAV\n"
    "• Архивы: ZIP\n\n"
    "Просто пришли мне файл или фото!"
)

converter = FileConverter()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 Инструкция:\n\n"
        "1. Отправь файл или фото прямо в чат.\n"
        "2. Бот скачает и обработает его.\n"
        "3. Если результат меньше 4096 символов — получишь текст прямо в чате.\n"
        "4. Если больше — получишь готовый .md файл.\n\n"
        f"⚠️ Максимальный размер файла: {MAX_FILE_SIZE // 1024 // 1024} МБ.\n\n"
        + START_TEXT.split("📄")[1]
    )
    await update.message.reply_text(text)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ Файл слишком большой ({doc.file_size // 1024 // 1024} МБ). "
            f"Максимум: {MAX_FILE_SIZE // 1024 // 1024} МБ."
        )
        return

    progress_msg = await update.message.reply_text("⏳ Конвертирую...")

    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    original_name = doc.file_name or f"file_{doc.file_id}"
    tmp_path = os.path.join(TEMP_DIR, original_name)
    stem = Path(original_name).stem
    out_path = os.path.join(TEMP_DIR, stem + ".md")

    try:
        await progress_msg.edit_text("⏳ Скачиваю файл...")
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(tmp_path)

        await progress_msg.edit_text("⏳ Конвертирую в Markdown...")
        loop = asyncio.get_running_loop()
        markdown = await loop.run_in_executor(None, converter.convert, tmp_path)

        Path(out_path).write_text(markdown, encoding="utf-8")
        await progress_msg.edit_text("✅ Готово! Отправляю файл...")
        with open(out_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=stem + ".md",
                caption="✅ Конвертация завершена.",
            )
        await progress_msg.delete()
    except Exception as e:
        logger.exception("Error processing document %s", original_name)
        try:
            await progress_msg.edit_text(f"❌ Ошибка при обработке файла:\n{e}")
        except Exception:
            pass
    finally:
        for path in (tmp_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]  # highest resolution

    progress_msg = await update.message.reply_text("⏳ Конвертирую фото...")

    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    tmp_path = os.path.join(TEMP_DIR, f"{photo.file_id}.jpg")
    out_path = os.path.join(TEMP_DIR, f"{photo.file_id}.md")

    try:
        await progress_msg.edit_text("⏳ Скачиваю фото...")
        tg_file = await photo.get_file()
        await tg_file.download_to_drive(tmp_path)

        await progress_msg.edit_text("⏳ Распознаю текст (OCR)...")
        loop = asyncio.get_running_loop()
        markdown = await loop.run_in_executor(None, converter.convert, tmp_path)

        Path(out_path).write_text(markdown, encoding="utf-8")
        await progress_msg.edit_text("✅ Готово! Отправляю файл...")
        with open(out_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="photo.md",
                caption="✅ OCR завершён.",
            )
        await progress_msg.delete()
    except Exception as e:
        logger.exception("Error processing photo")
        try:
            await progress_msg.edit_text(f"❌ Ошибка при обработке фото:\n{e}")
        except Exception:
            pass
    finally:
        for path in (tmp_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment / .env file")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Bot started. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

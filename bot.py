import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from converter import ConversionError, FileConverter
from stats import get_stats, init_db, log_conversion

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/markdown_bot")
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "10"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "8080"))

user_last_request: dict[int, float] = {}

CONVERT_MORE_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔄 Конвертировать ещё файл", callback_data="convert_more")]]
)

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


def _build_preview(markdown: str) -> str:
    if len(markdown) <= 500:
        return markdown
    return markdown[:500] + "...\n\n📄 Полный результат — в файле выше."


async def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last = user_last_request.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return False
    user_last_request[user_id] = now
    return True


async def cleanup_temp_files():
    while True:
        await asyncio.sleep(1800)
        try:
            now = time.time()
            temp_dir = Path(TEMP_DIR)
            if temp_dir.exists():
                for f in temp_dir.iterdir():
                    if f.is_file() and (now - f.stat().st_mtime) > 3600:
                        f.unlink()
                        logger.info("Cleaned up old temp file: %s", f.name)
        except Exception as e:
            logger.warning("Cleanup error: %s", e)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 Инструкция:\n\n"
        "1. Отправь файл или фото прямо в чат.\n"
        "2. Бот скачает и обработает его.\n"
        "3. Получишь .md файл + превью первых 500 символов.\n\n"
        f"⚠️ Максимальный размер файла: {MAX_FILE_SIZE // 1024 // 1024} МБ.\n"
        f"⏱ Между запросами: {RATE_LIMIT_SECONDS} сек.\n\n"
        + START_TEXT.split("📄")[1]
    )
    await update.message.reply_text(text)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Эта команда только для владельца бота.")
        return
    s = get_stats()
    formats = "\n".join(f"  {ext}: {cnt}" for ext, cnt in s["top_formats"]) or "  нет данных"
    text = (
        f"📊 *Статистика бота*\n\n"
        f"Всего конвертаций: *{s['total']}*\n"
        f"Успешных: *{s['success']}*\n"
        f"Уникальных пользователей: *{s['users']}*\n\n"
        f"*Топ форматов:*\n{formats}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "convert_more":
        await query.message.reply_text("📎 Отправь следующий файл!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not await check_rate_limit(user.id):
        await update.message.reply_text("⏳ Подожди немного перед отправкой следующего файла.")
        return

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
    ext = Path(original_name).suffix.lower()
    out_path = os.path.join(TEMP_DIR, stem + ".md")
    success = False

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
        await update.message.reply_text(
            _build_preview(markdown),
            reply_markup=CONVERT_MORE_KB,
        )
        success = True

    except ConversionError as e:
        logger.warning("ConversionError for %s: %s", original_name, e)
        try:
            await progress_msg.edit_text(f"❌ {e}")
        except Exception:
            pass

    except Exception as e:
        logger.exception("Error processing document %s", original_name)
        try:
            await progress_msg.edit_text(
                "❌ Произошла внутренняя ошибка. Попробуй ещё раз или отправь другой файл."
            )
        except Exception:
            pass

    finally:
        log_conversion(user.id, user.username or "", ext, doc.file_size or 0, success)
        for path in (tmp_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not await check_rate_limit(user.id):
        await update.message.reply_text("⏳ Подожди немного перед отправкой следующего файла.")
        return

    photo = update.message.photo[-1]
    progress_msg = await update.message.reply_text("⏳ Конвертирую фото...")

    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    tmp_path = os.path.join(TEMP_DIR, f"{photo.file_id}.jpg")
    out_path = os.path.join(TEMP_DIR, f"{photo.file_id}.md")
    success = False

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
        await update.message.reply_text(
            _build_preview(markdown),
            reply_markup=CONVERT_MORE_KB,
        )
        success = True

    except ConversionError as e:
        logger.warning("ConversionError for photo %s: %s", photo.file_id, e)
        try:
            await progress_msg.edit_text(f"❌ {e}")
        except Exception:
            pass

    except Exception as e:
        logger.exception("Error processing photo")
        try:
            await progress_msg.edit_text(
                "❌ Произошла внутренняя ошибка. Попробуй ещё раз или отправь другой файл."
            )
        except Exception:
            pass

    finally:
        log_conversion(user.id, user.username or "", ".jpg", photo.file_size or 0, success)
        for path in (tmp_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


async def post_init(application: Application) -> None:
    asyncio.create_task(cleanup_temp_files())


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment / .env file")

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    if WEBHOOK_URL:
        print(f"Starting webhook on port {PORT}...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            drop_pending_updates=True,
        )
    else:
        print("Bot started in polling mode. Press Ctrl+C to stop.")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

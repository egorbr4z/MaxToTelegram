import asyncio
import json
import os
import logging
import re
import html
from datetime import datetime
from PIL import Image
import aiofiles
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

HIST_FILE = 'history.json'
IMG_DIR = 'images'
VIDEO_DIR = 'videos'
DOC_DIR = 'documents'
STICKER_DIR = 'stickers'
CHECK_TIME = 10

BOT_TOKEN = os.getenv('BOT_TOKEN', '')
GROUP_ID = os.getenv('GROUP_ID', '')
PRIORITY_ID = os.getenv('PRIORITY_ID', '')
PERSONAL_ID = os.getenv('PERSONAL_ID', '')
API_URL = os.getenv('API_URL', '')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID', '')

BOT_START_TIME = datetime.now()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

for d in (IMG_DIR, VIDEO_DIR, DOC_DIR, STICKER_DIR):
    os.makedirs(d, exist_ok=True)

name_map = {}
if os.path.exists('ids.json'):
    with open('ids.json', encoding='utf-8') as f:
        for item in json.load(f):
            name_map[str(item['id'])] = item['name']

async def load_history():
    if not os.path.exists(HIST_FILE):
        return []
    async with aiofiles.open(HIST_FILE, encoding='utf-8') as f:
        return json.loads(await f.read())

async def save_history(history):
    async with aiofiles.open(HIST_FILE, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(history, ensure_ascii=False, indent=2))

def convert_image(path, fmt='PNG'):
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as img:
            base, _ = os.path.splitext(path)
            new_path = f"{base}.{fmt.lower()}"
            img.save(new_path, fmt)
        os.remove(path)
        return new_path
    except Exception as e:
        log.error(f"Conversion failed: {e}")
        if os.path.exists(path):
            os.remove(path)
        return None

async def download_file(session, url, msg_id, file_type, filename=None):
    if not url:
        return None
    try:
        async with session.get(url, timeout=60, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
            if resp.status != 200:
                return None
            content = await resp.read()
        if not content:
            return None

        ext = 'png'
        if file_type == 'image':
            ext = url.split('.')[-1].split('?')[0].lower()
            if ext not in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
                ext = 'png'
            path = os.path.join(IMG_DIR, f"{msg_id}.{ext}")
        elif file_type == 'video':
            path = os.path.join(VIDEO_DIR, f"{msg_id}.mp4")
        elif file_type == 'document':
            safe_name = (filename or msg_id).replace('/', '_').replace('\\', '_')
            path = os.path.join(DOC_DIR, safe_name)
        elif file_type == 'sticker':
            path = os.path.join(STICKER_DIR, f"{msg_id}.png")
        else:
            return None

        async with aiofiles.open(path, 'wb') as f:
            await f.write(content)

        if not os.path.getsize(path):
            os.remove(path)
            return None

        if file_type == 'image':
            path = convert_image(path, 'PNG')
        return path
    except Exception as e:
        log.error(f"Download error: {e}")
        return None

def convert_to_html(text: str) -> str:
    if not text:
        return text

    replacements = {}
    counter = 0

    def replace_markdown_link(m):
        nonlocal counter
        idx = counter
        counter += 1
        safe_text = html.escape(m.group(1))
        safe_url = html.escape(m.group(2), quote=True)
        replacements[f'MDLINK{idx}'] = f'<a href="{safe_url}">{safe_text}</a>'
        return f'MDLINK{idx}'

    def replace_url(m):
        nonlocal counter
        idx = counter
        counter += 1
        safe_url = html.escape(m.group(0), quote=True)
        replacements[f'URL{idx}'] = f'<a href="{safe_url}">{safe_url}</a>'
        return f'URL{idx}'

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_markdown_link, text)
    text = re.sub(r'https?://[^\s<>]+', replace_url, text)
    text = html.escape(text)
    text = re.sub(r'\*([^\*]+)\*', r'<b>\1</b>', text)
    text = re.sub(r'\_([^\_]+)\_', r'<i>\1</i>', text)

    for placeholder, link in replacements.items():
        text = text.replace(placeholder, link)
    return text

def format_text(sender_name, sender_id, text, is_priority):
    if not text:
        return ""
    if is_priority:
        return text
    return f"<strong>📘 Сообщение от {sender_name}:</strong>\n\n{text}"

async def send_media_or_text(bot, chat_id, file_path=None, caption='', filename=None, is_sticker=False, delete_after=True):
    """Универсальная отправка сообщения с медиа или текстом.
    При delete_after=True файл удаляется после успешной отправки."""
    sent = []
    try:
        if file_path and os.path.exists(file_path):
            if is_sticker:
                msg = await bot.send_sticker(chat_id, FSInputFile(file_path))
                sent.append(msg)
                if caption.strip():
                    sent.append(await bot.send_message(chat_id, caption, parse_mode='HTML'))
                if delete_after:
                    os.remove(file_path)
                return sent

            if len(caption) > 1024:
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    msg = await bot.send_photo(chat_id, FSInputFile(file_path))
                elif file_path.lower().endswith('.mp4'):
                    msg = await bot.send_video(chat_id, FSInputFile(file_path), supports_streaming=True)
                else:
                    msg = await bot.send_document(chat_id, FSInputFile(file_path, filename=filename or os.path.basename(file_path)))
                sent.append(msg)
                if caption.strip():
                    sent.append(await bot.send_message(chat_id, caption, parse_mode='HTML'))
            else:
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    msg = await bot.send_photo(chat_id, FSInputFile(file_path), caption=caption, parse_mode='HTML')
                elif file_path.lower().endswith('.mp4'):
                    msg = await bot.send_video(chat_id, FSInputFile(file_path), caption=caption, parse_mode='HTML', supports_streaming=True)
                else:
                    msg = await bot.send_document(chat_id, FSInputFile(file_path, filename=filename or os.path.basename(file_path)), caption=caption, parse_mode='HTML')
                sent.append(msg)

            if delete_after:
                os.remove(file_path)
        else:
            if caption.strip():
                sent.append(await bot.send_message(chat_id, caption, parse_mode='HTML'))
        return sent
    except Exception as e:
        log.error(f"Send error to {chat_id}: {e}")
        return None

async def forward_to_group(bot, group_id, from_chat_id, message_id):
    try:
        await bot.forward_message(group_id, from_chat_id, message_id)
    except Exception as e:
        log.error(f"Forward error: {e}")

async def process_message(bot, msg_data, session):
    mid = msg_data.get('idMessage')
    if not mid:
        return False

    sender_id = msg_data.get('senderId', '')
    sender_name = name_map.get(sender_id, msg_data.get('senderName', 'Неизвестный'))
    raw_text = msg_data.get('textMessage') or msg_data.get('caption') or ''
    raw_text = convert_to_html(raw_text)
    msg_type = msg_data.get('typeMessage', '')
    is_priority = sender_id == PRIORITY_ID
    formatted_text = format_text(sender_name, sender_id, raw_text, is_priority)

    file_path = None
    is_sticker = False

    try:
        if msg_type == 'imageMessage':
            file_path = await download_file(session, msg_data.get('downloadUrl'), mid, 'image')
        elif msg_type == 'videoMessage':
            file_path = await download_file(session, msg_data.get('downloadUrl'), mid, 'video')
        elif msg_type == 'documentMessage':
            file_path = await download_file(session, msg_data.get('downloadUrl'), mid, 'document', msg_data.get('fileName'))
        elif msg_type == 'stickerMessage':
            file_path = await download_file(session, msg_data.get('downloadUrl'), mid, 'sticker')
            if file_path:
                file_path = convert_image(file_path, 'WEBP')
                is_sticker = True

        if is_priority:
            sent_msgs = await send_media_or_text(
                bot, PERSONAL_ID,
                file_path=file_path,
                caption=formatted_text,
                filename=msg_data.get('fileName'),
                is_sticker=is_sticker,
                delete_after=True
            )
            if sent_msgs is None:
                return False
            for msg in sent_msgs:
                await asyncio.sleep(0.5)
                await forward_to_group(bot, GROUP_ID, PERSONAL_ID, msg.message_id)
        else:
            sent_msgs = await send_media_or_text(
                bot, GROUP_ID,
                file_path=file_path,
                caption=formatted_text,
                filename=msg_data.get('fileName'),
                is_sticker=is_sticker,
                delete_after=True
            )
            if sent_msgs is None:
                return False
        return True
    except Exception as e:
        log.error(f"Process error for {mid}: {e}")
        return False

async def check_new_messages(bot):
    history = await load_history()
    processed = {m['idMessage'] for m in history if m.get('idMessage')}

    payload = {"chatId": WHATSAPP_CHAT_ID}
    headers = {'Content-Type': 'application/json'}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    log.error(f"API error: {resp.status}")
                    return
                all_messages = await resp.json()
    except Exception as e:
        log.error(f"API request failed: {e}")
        return

    all_messages.sort(key=lambda x: x.get('timestamp', 0))
    valid_types = {'imageMessage', 'textMessage', 'extendedTextMessage', 'videoMessage', 'documentMessage', 'stickerMessage'}
    new_messages = [m for m in all_messages if m.get('typeMessage') in valid_types and m['idMessage'] not in processed]

    if not new_messages:
        return

    async with aiohttp.ClientSession() as session:
        for msg in new_messages:
            ok = await process_message(bot, msg, session)
            msg['processed_at'] = datetime.now().timestamp() if ok else None

    await save_history(history + new_messages)
    log.info(f"Processed {len(new_messages)} new messages")

def get_uptime():
    delta = datetime.now() - BOT_START_TIME
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    parts.append(f"{seconds}с")
    return " ".join(parts)

async def start_command(message: types.Message):
    uptime = get_uptime()
    await message.answer(f"Аптайм: {uptime}", parse_mode='HTML')

async def main():
    log.info("Bot started")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.message.register(start_command, Command("start"))

    polling_task = asyncio.create_task(dp.start_polling(bot))

    try:
        while True:
            await check_new_messages(bot)
            await asyncio.sleep(CHECK_TIME)
    except KeyboardInterrupt:
        log.info("Bot stopped")
    finally:
        polling_task.cancel()
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
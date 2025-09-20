import discord
from discord.ext import commands
import asyncio
import yt_dlp as youtube_dl
import datetime
import random
import time
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor
import re
import aiohttp
from cachetools import TTLCache
import functools

# Кэш для результатов поиска (хранится 30 минут)
search_cache = TTLCache(maxsize=200, ttl=1800)
track_cache = TTLCache(maxsize=100, ttl=3600)

# Глобальный исполнитель для тяжелых операций
executor = ThreadPoolExecutor(max_workers=20)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='?', intents=intents, help_command=None)

# Класс для хранения состояния сервера
class ServerState:
    def __init__(self):
        self.queue = []
        self.current = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.current_volume = 1.0
        self.is_paused = False
        self.is_looping = False
        self.is_radio = False
        self.is_seeking = False
        self.start_time = 0
        self.last_playing_message = None
        self.nowplaying_updater = None

# Словарь для хранения состояний каждого сервера
server_states: Dict[int, ServerState] = {}

# Функция для получения состояния сервера
def get_server_state(guild_id: int) -> ServerState:
    if guild_id not in server_states:
        server_states[guild_id] = ServerState()
    return server_states[guild_id]

# Оптимизированные настройки yt-dlp для быстрого извлечения
ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'default_search': 'ytsearch',
    'noplaylist': True,
    'youtube_include_dash_manifest': False,
    'youtube_include_hls_manifest': False,
    'no_check_certificate': True,
    'geo_bypass': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

# Ускоренные опции FFmpeg
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -probesize 32 -threads 2',
    'options': '-vn -filter:a "volume=0.99"'
}

YTDL = youtube_dl.YoutubeDL(ytdl_format_options)

# Вспомогательные функции
def format_duration(seconds):
    if seconds < 0:
        return "0:00"
    return str(datetime.timedelta(seconds=int(seconds))).split('.')[0]

def create_embed(title, description=None, color=0x4682B4):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Министерство культуры ВФ | Кассета",
                     icon_url="https://github.com/N0-LABEL/Kasseta/blob/main/mkrf.png?raw=true")
    return embed

def create_progress_bar(position, duration, length=15):
    if duration <= 0:
        return ""
    progress = min(1, max(0, position / duration))
    filled = int(progress * length)
    return "[" + "▬" * filled + "🔘" + "▬" * (length - filled) + "]"

def is_playlist_url(url):
    return 'list=' in url or 'playlist?list=' in url

def is_valid_url(url):
    return url.startswith(('http://', 'https://', 'www.'))

async def extract_info_async(search, playlist=False):
    """Асинхронное извлечение информации о треке"""
    cache_key = f"{'playlist_' if playlist else 'track_'}{search}"

    # Проверяем кэш
    if cache_key in search_cache:
        return search_cache[cache_key]

    # Извлекаем информацию в отдельном потоке
    loop = asyncio.get_event_loop()
    options = ytdl_format_options.copy()
    options['noplaylist'] = not playlist

    try:
        # Используем functools.partial для передачи параметров
        func = functools.partial(extract_info_sync, search, playlist)
        info = await loop.run_in_executor(executor, func)

        # Кэшируем результат
        if info:
            search_cache[cache_key] = info
            # Для отдельных треков также кэшируем URL
            if not playlist and 'entries' not in info:
                track_url = info.get('url')
                if track_url:
                    track_cache[track_url] = info

        return info
    except Exception as e:
        print(f"Ошибка извлечения информации: {e}")
        return None

def extract_info_sync(search, playlist=False):
    """Синхронное извлечение информации о треке"""
    options = ytdl_format_options.copy()
    options['noplaylist'] = not playlist

    # Для URL проверяем кэш
    if is_valid_url(search) and not playlist and search in track_cache:
        return track_cache[search]

    with youtube_dl.YoutubeDL(options) as ytdl:
        try:
            return ytdl.extract_info(search, download=False)
        except Exception as e:
            print(f"Ошибка синхронного извлечения: {e}")
            return None

def process_track(info):
    if 'entries' in info:
        info = info['entries'][0]

    return {
        'url': info['url'],
        'title': info['title'],
        'duration': info.get('duration', 0),
        'user': None
    }

async def add_to_queue(ctx, track):
    """Асинхронное добавление трека в очередь"""
    state = get_server_state(ctx.guild.id)
    
    track['user'] = ctx.author
    state.queue.append(track)

    # Отправляем мгновенный ответ
    embed = create_embed(
        "Добавлено в очередь",
        f"✅ **{track['title']}** (`{format_duration(track['duration'])}`)\nДобавил: {ctx.author.mention}"
    )

    await ctx.send(embed=embed)

    # Если ничего не играет, запускаем воспроизведение
    if not state.voice_client.is_playing() and not state.is_paused:
        await play_next(ctx)

async def play_next(ctx):
    state = get_server_state(ctx.guild.id)

    if state.nowplaying_updater:
        state.nowplaying_updater.cancel()
        state.nowplaying_updater = None

    if state.is_paused or state.is_seeking:
        return

    # Получаем следующий трек из очереди
    if state.is_looping and state.current:
        track = state.current
    elif state.queue:
        track = state.queue.pop(0)
    else:
        state.current = None
        state.is_radio = False
        await ctx.send(embed=create_embed("Очередь пуста", "Музыка остановлена."))
        return

    state.current = track
    url = track['url']
    title = track['title']
    user = track['user']
    duration = track.get('duration', 0)
    state.start_time = time.time()

    if not (state.is_looping and state.last_playing_message):
        progress_bar = create_progress_bar(0, duration)
        description = (
            f"🎵 **{title}**\n"
            f"{progress_bar}\n"
            f"`00:00 / {format_duration(duration)}`\n"
            f"Добавил: {user.mention}"
        )
        state.last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))

        if not state.nowplaying_updater:
            state.nowplaying_updater = asyncio.create_task(update_now_playing(ctx, state.last_playing_message, state))

    def after_playing(e):
        if not state.is_seeking and state.voice_client and state.voice_client.is_connected():
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

    try:
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        source = discord.PCMVolumeTransformer(source, volume=state.current_volume)
        if state.voice_client:
            state.voice_client.play(source, after=after_playing)
    except Exception as e:
        print(f"Ошибка воспроизведения: {e}")
        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

async def update_now_playing(ctx, message, state):
    while state.current and state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
        try:
            position = time.time() - state.start_time if not state.is_paused else state.current.get('position', 0)
            duration = state.current.get('duration', 0)

            progress_bar = create_progress_bar(position, duration)
            description = (
                f"🎵 **{state.current['title']}**\n"
                f"{progress_bar}\n"
                f"`{format_duration(position)} / {format_duration(duration)}`\n"
                f"Добавил: {state.current['user'].mention}"
            )

            await message.edit(embed=create_embed("Сейчас играет", description))
            await asyncio.sleep(15)
        except:
            break

async def run_in_executor(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

async def add_playlist(ctx, search):
    state = get_server_state(ctx.guild.id)
    
    # Проверка, что это ссылка на плейлист
    if not is_playlist_url(search):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Это не ссылка на плейлист! Для одиночных треков используйте `?play`."
        ))

    try:
        info = await run_in_executor(extract_info_sync, search, True)

        if not info or 'entries' not in info or not info['entries']:
            return await ctx.send(embed=create_embed("Ошибка", "Плейлист не найден или пуст"))

        tracks = []
        for entry in info['entries']:
            if not entry:
                continue
            track = process_track(entry)
            track['user'] = ctx.author
            tracks.append(track)

        for track in tracks:
            state.queue.append(track)

        await ctx.send(embed=create_embed(
            "Плейлист добавлен",
            f"✅ Добавлено треков: {len(tracks)}\n"
            f"🎵 **{tracks[0]['title']}** - первый трек\n"
            f"Добавил: {ctx.author.mention}"
        ))

        if not state.voice_client.is_playing() and not state.is_paused:
            await play_next(ctx)

    except Exception as e:
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось загрузить плейлист: {e}"))

# События бота
@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="?help")
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    print(f"Бот запущен как {bot.user}")

@bot.event
async def on_guild_remove(guild):
    """Очистка состояния при выходе с сервера"""
    if guild.id in server_states:
        state = server_states[guild.id]
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.disconnect()
        del server_states[guild.id]

# Команды бота
@bot.command()
async def about(ctx):
    await ctx.send(embed=create_embed(
        "О боте",
        "🎶 Кассета — это универсальный музыкальный бот с широким функционалом. "
        "Умеет воспроизводить музыку с YouTube, плейлисты, перематывать треки и управлять громкостью, "
        "обеспечивая полноценное музыкальное сопровождение для сервера.\n  \n**Сделано в ВФ**"
    ))

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(embed=create_embed("Пинг", f"📡 {latency}ms"))

@bot.command()
async def play(ctx, *, search: str):
    state = get_server_state(ctx.guild.id)

    if is_valid_url(search) and is_playlist_url(search):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Похоже, вы ввели ссылку на плейлист. Для плейлистов используйте команду `?playlist`."
        ))

    if state.is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    state.is_paused = False

    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    try:
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()
        elif state.voice_client.channel != ctx.author.voice.channel:
            await state.voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    # Отправляем сообщение о начале загрузки
    loading_msg = await ctx.send(embed=create_embed("Загрузка", "⏳ Получение информации о треке..."))

    try:
        # Используем асинхронное извлечение информации
        info = await extract_info_async(search, False)

        if not info:
            await loading_msg.edit(embed=create_embed("Ошибка", "Трек не найден."))
            return

        track = process_track(info)

        # Удаляем сообщение о загрузке и добавляем трек в очередь
        await loading_msg.delete()
        await add_to_queue(ctx, track)

    except Exception as e:
        await loading_msg.edit(embed=create_embed("Ошибка", f"Не удалось получить трек: {e}"))

@bot.command()
async def playlist(ctx, *, search: str):
    state = get_server_state(ctx.guild.id)

    # Если это URL, но не плейлист — сразу ошибка
    if is_valid_url(search) and not is_playlist_url(search):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Похоже, вы ввели ссылку не на плейлист. Для одиночных треков используйте команду `?play`."
        ))

    # Если это просто текст (не URL) — тоже ошибка (если нужно)
    elif not is_valid_url(search):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Вы ввели текст, а не ссылку на плейлист. Используйте `?play` для поиска треков."
        ))

    # Если играет радио — ошибка
    if state.is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    # Проверка голосового канала
    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    # Подключение к голосовому каналу
    try:
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()
        elif state.voice_client.channel != ctx.author.voice.channel:
            await state.voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    # Если это действительно плейлист — загружаем
    await ctx.send(embed=create_embed("Загрузка плейлиста", "⏳ Пожалуйста, подождите, плейлист загружается..."))
    bot.loop.create_task(add_playlist(ctx, search))

@bot.command()
async def nowplaying(ctx):
    state = get_server_state(ctx.guild.id)

    try:
        await ctx.message.delete()
    except:
        pass

    if not state.current:
        return await ctx.send(embed=create_embed("Пусто", "Сейчас ничего не играет."))

    if state.last_playing_message:
        try:
            position = time.time() - state.start_time if not state.is_paused else state.current.get('position', 0)
            duration = state.current.get('duration', 0)
            progress_bar = create_progress_bar(position, duration)
            description = (
                f"🎵 **{state.current['title']}**\n"
                f"{progress_bar}\n"
                f"`{format_duration(position)} / {format_duration(duration)}`\n"
                f"Добавил: {state.current['user'].mention}"
            )
            await state.last_playing_message.edit(embed=create_embed("Сейчас играет", description))
            return
        except:
            pass

    position = time.time() - state.start_time if not state.is_paused else state.current.get('position', 0)
    duration = state.current.get('duration', 0)
    progress_bar = create_progress_bar(position, duration)
    description = (
        f"🎵 **{state.current['title']}**\n"
        f"{progress_bar}\n"
        f"`{format_duration(position)} / {format_duration(duration)}`\n"
        f"Добавил: {state.current['user'].mention}"
    )
    state.last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))

    if not state.nowplaying_updater and state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
        state.nowplaying_updater = bot.loop.create_task(update_now_playing(ctx, state.last_playing_message, state))

@bot.command(name='queue')
async def queue_(ctx, page: int = 1):
    state = get_server_state(ctx.guild.id)
    
    if not state.queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))

    items_per_page = 10
    total_pages = max(1, (len(state.queue) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * items_per_page
    end = start + items_per_page
    lines = []
    for i, song in enumerate(state.queue[start:end], start=start + 1):
        duration = format_duration(song.get('duration', 0))
        lines.append(f"**{i}.** [`{duration}`] {song['title']} - {song['user'].mention}")

    total_duration = sum(song.get('duration', 0) for song in state.queue)
    header = f"Текущая очередь | {len(state.queue)} треков | {format_duration(total_duration)} | Страница {page}/{total_pages}"
    message = await ctx.send(embed=create_embed(header, "\n".join(lines), color=0xB0C4DE))

    if total_pages > 1:
        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")
        await message.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["⬅️", "➡️", "❌"] and reaction.message.id == message.id

        try:
            while True:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)

                if str(reaction.emoji) == "❌":
                    await message.delete()
                    return
                elif str(reaction.emoji) == "⬅️":
                    page = max(1, page - 1)
                elif str(reaction.emoji) == "➡️":
                    page = min(total_pages, page + 1)

                start = (page - 1) * items_per_page
                end = start + items_per_page
                lines = []
                for i, song in enumerate(state.queue[start:end], start=start + 1):
                    duration = format_duration(song.get('duration', 0))
                    lines.append(f"**{i}.** [`{duration}`] {song['title']} - {song['user'].mention}")

                header = f"Текущая очередь | {len(state.queue)} треков | {format_duration(total_duration)} | Страница {page}/{total_pages}"
                embed = create_embed(header, "\n".join(lines), color=0xB0C4DE)
                await message.edit(embed=embed)
                await message.remove_reaction(reaction, user)

        except asyncio.TimeoutError:
            await message.clear_reactions()

@bot.command()
async def remove(ctx, arg: str):
    state = get_server_state(ctx.guild.id)
    
    if not state.queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))
    if arg == 'all':
        state.queue.clear()
        await ctx.send(embed=create_embed("Очищено", "Очередь была полностью очищена."))
    else:
        try:
            index = int(arg) - 1
            if 0 <= index < len(state.queue):
                removed = state.queue.pop(index)
                await ctx.send(embed=create_embed("Удалено", f"🗑️ {removed['title']}"))
            else:
                await ctx.send(embed=create_embed("Ошибка", "Неверный индекс!"))
        except ValueError:
            await ctx.send(embed=create_embed("Ошибка", "Используйте число или 'all'"))

@bot.command()
async def skip(ctx):
    state = get_server_state(ctx.guild.id)
    
    if state.voice_client and state.voice_client.is_playing():
        state.voice_client.stop()
        await ctx.send(embed=create_embed("Пропущено", "⏭️ Песня была пропущена."))
    else:
        await ctx.send(embed=create_embed("Ошибка", "Сейчас ничего не играет."))

@bot.command()
async def stop(ctx):
    state = get_server_state(ctx.guild.id)
    
    if state.nowplaying_updater:
        state.nowplaying_updater.cancel()
        state.nowplaying_updater = None

    if state.voice_client:
        state.voice_client.stop()
        if state.voice_client.is_connected():
            await state.voice_client.disconnect()
        state.voice_client = None

    state.queue.clear()
    state.current = None
    state.is_radio = False
    state.is_looping = False
    state.is_paused = False
    state.last_playing_message = None

    await ctx.send(embed=create_embed("Остановлено", "⏹️ Воспроизведение остановлено и бот отключен."))

@bot.command()
async def pause(ctx):
    state = get_server_state(ctx.guild.id)
    
    if not state.voice_client or not state.voice_client.is_connected():
        return await ctx.send(embed=create_embed("Ошибка", "Бот не подключен к голосовому каналу."))
    if state.voice_client.is_playing():
        state.voice_client.pause()
        state.is_paused = True
        await ctx.send(embed=create_embed("Пауза", "⏸️ Воспроизведение приостановлено."))
    elif state.voice_client.is_paused():
        state.voice_client.resume()
        state.is_paused = False
        await ctx.send(embed=create_embed("Продолжено", "▶️ Воспроизведение возобновлено."))
    else:
        await ctx.send(embed=create_embed("Ошибка", "Сейчас ничего не играет."))

@bot.command()
async def volume(ctx, level: int = None):
    state = get_server_state(ctx.guild.id)
    
    if level is None:
        return await ctx.send(embed=create_embed(
            "Громкость",
            f"🔊 Текущая громкость: {int(state.current_volume * 100)}%"
        ))
    if not 0 <= level <= 150:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Уровень громкости должен быть между 0 и 150"
        ))
    state.current_volume = level / 100
    if state.voice_client and state.voice_client.source:
        state.voice_client.source.volume = state.current_volume
    await ctx.send(embed=create_embed(
        "Громкость",
        f"🔊 Установлена громкость: {level}%"
    ))

@bot.command()
async def shuffle(ctx):
    state = get_server_state(ctx.guild.id)
    
    if not state.queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))
    random.shuffle(state.queue)
    await ctx.send(embed=create_embed("Перемешано", "🔀 Очередь перемешана."))

@bot.command()
async def search(ctx, *, query: str):
    state = get_server_state(ctx.guild.id)
    
    if is_valid_url(query):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Для поиска используйте только текст. Для воспроизведения по ссылке используйте `?play`."
        ))

    if state.is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    try:
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()
        elif state.voice_client.channel != ctx.author.voice.channel:
            await state.voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    try:
        results = await run_in_executor(
            lambda: YTDL.extract_info(f"ytsearch4:{query}", download=False)['entries']
        )
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка", f"Не удалось выполнить поиск: {e}"))

    valid_results = []
    for entry in results:
        if entry and entry.get('url'):
            valid_results.append(entry)

    if not valid_results:
        return await ctx.send(embed=create_embed("Ошибка", "Ничего не найдено."))

    lines = []
    for i, entry in enumerate(valid_results, 1):
        duration = format_duration(entry.get('duration', 0))
        lines.append(f"{i}. [`{duration}`] {entry['title']}")

    embed = create_embed(
        f"Результаты поиска по запросу: {query}",
        "\n".join(lines),
        color=0x3498db
    )
    embed.set_footer(text="Выберите трек или нажмите ❌ для отмена")
    message = await ctx.send(embed=embed)

    reactions = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '❌'][:len(valid_results) + 1]
    for i in range(len(valid_results)):
        await message.add_reaction(reactions[i])
    await message.add_reaction('❌')

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == message.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        if str(reaction.emoji) == '❌':
            await message.delete()
            return

        index = reactions.index(str(reaction.emoji))
        if index < len(valid_results):
            entry = valid_results[index]
            url = entry['url']
            title = entry['title']
            duration = entry.get('duration', 0)

            state.queue.append({
                'url': url,
                'title': title,
                'duration': duration,
                'user': ctx.author
            })

            await ctx.send(embed=create_embed(
                "Добавлено в очередь",
                f"✅ **{title}** (`{format_duration(duration)}`)\nДобавил: {ctx.author.mention}"
            ))

            if not state.voice_client.is_playing() and not state.is_paused:
                await play_next(ctx)

            await message.delete()
    except asyncio.TimeoutError:
        await message.delete()
        await ctx.send(embed=create_embed("Время вышло", "Выбор трека отменен."))

@bot.command()
async def seek(ctx, seconds_str: str):
    state = get_server_state(ctx.guild.id)
    
    if not state.current or not state.voice_client or not state.voice_client.is_playing():
        return await ctx.send(embed=create_embed("Ошибка", "Ничего не играет."))
    if not seconds_str.startswith(('+', '-')):
        return await ctx.send(embed=create_embed("Ошибка", "Используйте формат: `?seek +30` или `?seek -15`"))
    try:
        seconds = int(seconds_str)
    except ValueError:
        return await ctx.send(embed=create_embed("Ошибка", "Введите целое число секунд"))

    current_position = time.time() - state.start_time
    new_position = max(0, current_position + seconds)
    duration = state.current.get('duration', 0)
    if new_position > duration:
        return await ctx.send(embed=create_embed("Ошибка", "Время превышает длительность трека."))

    state.start_time = time.time() - new_position
    state.is_seeking = True
    try:
        state.voice_client.stop()
        url = state.current['url']
        seek_options = {
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {new_position}',
            'options': '-vn'
        }
        source = discord.FFmpegPCMAudio(url, **seek_options)
        source = discord.PCMVolumeTransformer(source, volume=state.current_volume)

        def after_seek(e):
            state.is_seeking = False
            fut = play_next(ctx)
            asyncio.run_coroutine_threadsafe(fut, bot.loop)

        state.voice_client.play(source, after=after_seek)
        await ctx.send(embed=create_embed("Перемотка", f"⏩ Установлена позиция: {format_duration(new_position)}"))
        if state.last_playing_message:
            try:
                progress_bar = create_progress_bar(new_position, duration)
                description = (
                    f"🎵 **{state.current['title']}**\n"
                    f"{progress_bar}\n"
                    f"`{format_duration(new_position)} / {format_duration(duration)}`\n"
                    f"Добавил: {state.current['user'].mention}"
                )
                await state.last_playing_message.edit(embed=create_embed("Сейчас играет", description))
            except:
                pass
    except Exception as e:
        state.is_seeking = False
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось перемотать: {e}"))

@bot.command()
async def playlists(ctx):
    await ctx.send(embed=create_embed("Плейлисты", "🎧 Вставьте ссылку на YouTube-плейлист в команду ?playlist."))

@bot.command()
async def help(ctx):
    embed = create_embed("Список команд", color=0x7B68EE)
    commands_list = [
        ("?pause", "Приостановить/возобновить воспроизведение"),
        ("?nowplaying", "Показать текущий трек с прогресс-баром"),
        ("?play <название|URL>", "Воспроизвести трек"),
        ("?playlist <URL>", "Воспроизвести плейлист"),
        ("?queue [страница]", "Показать очередь воспроизведения"),
        ("?remove <позиция|all>", "Удалить трек из очереди"),
        ("?search <запрос>", "Поиск на YouTube (только текст)"),
        ("?seek <+/-секунды>", "Перемотка вперед/назад в секундах"),
        ("?shuffle", "Перемешать очередь"),
        ("?skip", "Пропустить текущий трек"),
        ("?stop", "Остановить воспроизведение и выйти"),
        ("?volume [0-150]", "Установить громкость"),
        ("?ping", "Проверить задержку бота"),
        ("?loop", "Включить/выключить повтор трека"),
        ("?radio <URL>", "Воспроизвести радио-поток"),
        ("?help", "Показать это сообщение"),
        ("?about", "Информация о боте")
    ]
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def radio(ctx, url: str):
    state = get_server_state(ctx.guild.id)
    
    if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
        state.voice_client.stop()
    state.queue.clear()
    state.current = None
    state.last_playing_message = None
    state.is_radio = True
    state.is_paused = False
    state.is_looping = False
    try:
        if not ctx.author.voice:
            return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()
        elif state.voice_client.channel != ctx.author.voice.channel:
            await state.voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    def after_playing(e):
        fut = play_next(ctx)
        asyncio.run_coroutine_threadsafe(fut, bot.loop)

    try:
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        source = discord.PCMVolumeTransformer(source, state.current_volume)
        if state.voice_client:
            state.voice_client.play(source, after=after_playing)
            await ctx.send(embed=create_embed("Радио", f"📻 {url}"))
    except Exception as e:
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось воспроизвести радио: {e}"))

@bot.command()
async def loop(ctx):
    state = get_server_state(ctx.guild.id)
    
    state.is_looping = not state.is_looping
    await ctx.send(embed=create_embed("Повтор", f"🔁 {'Повтор включён' if state.is_looping else 'Повтор выключен'}"))

# Замените на ваш токен
bot.run('')
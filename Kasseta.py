import discord
from discord.ext import commands
import asyncio
import yt_dlp as youtube_dl
import datetime
import random
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import re

# Глобальный исполнитель для тяжелых операций
executor = ThreadPoolExecutor(max_workers=10)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='?', intents=intents, help_command=None)

# Глобальные переменные
queue = []
current = None
voice_client: Optional[discord.VoiceClient] = None
current_volume = 1.0
is_paused = False
is_looping = False
is_radio = False
is_seeking = False
start_time = 0
last_playing_message = None
nowplaying_updater = None

# Настройки yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'source_address': '0.0.0.0',
    'default_search': 'ytsearch',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 10M -probesize 10M',
    'options': '-vn'
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


async def play_next(ctx):
    global current, queue, voice_client, is_looping, is_radio, start_time, is_paused, is_seeking, last_playing_message, nowplaying_updater

    if nowplaying_updater:
        nowplaying_updater.cancel()
        nowplaying_updater = None

    if is_paused or is_seeking:
        return

    if is_looping and current:
        track = current
    elif queue:
        track = queue.pop(0)
    else:
        current = None
        is_radio = False
        await ctx.send(embed=create_embed("Очередь пуста", "Музыка остановлена."))
        return

    current = track
    url = track['url']
    title = track['title']
    user = track['user']
    duration = track.get('duration', 0)
    start_time = time.time()

    if not (is_looping and last_playing_message):
        progress_bar = create_progress_bar(0, duration)
        description = (
            f"🎵 **{title}**\n"
            f"{progress_bar}\n"
            f"`00:00 / {format_duration(duration)}`\n"
            f"Добавил: {user.mention}"
        )
        last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))

        if not nowplaying_updater:
            nowplaying_updater = bot.loop.create_task(update_now_playing(ctx, last_playing_message))

    def after_playing(e):
        if not is_seeking and voice_client and voice_client.is_connected():
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

    try:
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        source = discord.PCMVolumeTransformer(source, volume=current_volume)
        if voice_client:
            voice_client.play(source, after=after_playing)
    except Exception as e:
        print(f"Ошибка воспроизведения: {e}")
        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)


async def update_now_playing(ctx, message):
    global current, start_time, is_paused, voice_client

    while current and voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        try:
            position = time.time() - start_time if not is_paused else current.get('position', 0)
            duration = current.get('duration', 0)

            progress_bar = create_progress_bar(position, duration)
            description = (
                f"🎵 **{current['title']}**\n"
                f"{progress_bar}\n"
                f"`{format_duration(position)} / {format_duration(duration)}`\n"
                f"Добавил: {current['user'].mention}"
            )

            await message.edit(embed=create_embed("Сейчас играет", description))
            await asyncio.sleep(15)
        except:
            break


# Асинхронные обертки
async def run_in_executor(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)


def extract_info_sync(search, playlist=False):
    options = ytdl_format_options.copy()
    options['noplaylist'] = not playlist
    with youtube_dl.YoutubeDL(options) as ytdl:
        return ytdl.extract_info(search, download=False)


def process_track(info):
    if 'entries' in info:
        info = info['entries'][0]

    return {
        'url': info['url'],
        'title': info['title'],
        'duration': info.get('duration', 0),
        'user': None
    }


async def add_playlist(ctx, search):
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
            queue.append(track)

        await ctx.send(embed=create_embed(
            "Плейлист добавлен",
            f"✅ Добавлено треков: {len(tracks)}\n"
            f"🎵 **{tracks[0]['title']}** - первый трек\n"
            f"Добавил: {ctx.author.mention}"
        ))

        if not voice_client.is_playing() and not is_paused:
            await play_next(ctx)

    except Exception as e:
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось загрузить плейлист: {e}"))


# События бота
@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="?help")
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    print(f"Бот запущен как {bot.user}")


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
    global voice_client, is_radio, is_paused, queue, current, last_playing_message

    if is_valid_url(search) and is_playlist_url(search):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Похоже, вы ввели ссылку на плейлист. Для плейлистов используйте команду `?playlist`."
        ))

    if is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    is_paused = False

    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    try:
        if not voice_client or not voice_client.is_connected():
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    try:
        info = await run_in_executor(extract_info_sync, search, False)

        if not info:
            return await ctx.send(embed=create_embed("Ошибка", "Трек не найден."))

        track = process_track(info)
        track['user'] = ctx.author
        queue.append(track)

        await ctx.send(embed=create_embed(
            "Добавлено в очередь",
            f"✅ **{track['title']}** (`{format_duration(track['duration'])}`)\nДобавил: {ctx.author.mention}"
        ))

        if not voice_client.is_playing() and not is_paused:
            await play_next(ctx)

    except Exception as e:
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось получить трек: {e}"))


@bot.command()
async def playlist(ctx, *, search: str):
    global voice_client, is_radio, is_paused

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
    if is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    # Проверка голосового канала
    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    # Подключение к голосовому каналу
    try:
        if not voice_client or not voice_client.is_connected():
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    # Если это действительно плейлист — загружаем
    await ctx.send(embed=create_embed("Загрузка плейлиста", "⏳ Пожалуйста, подождите, плейлист загружается..."))
    bot.loop.create_task(add_playlist(ctx, search))


@bot.command()
async def nowplaying(ctx):
    global last_playing_message, current, start_time, is_paused

    try:
        await ctx.message.delete()
    except:
        pass

    if not current:
        return await ctx.send(embed=create_embed("Пусто", "Сейчас ничего не играет."))

    if last_playing_message:
        try:
            position = time.time() - start_time if not is_paused else current.get('position', 0)
            duration = current.get('duration', 0)
            progress_bar = create_progress_bar(position, duration)
            description = (
                f"🎵 **{current['title']}**\n"
                f"{progress_bar}\n"
                f"`{format_duration(position)} / {format_duration(duration)}`\n"
                f"Добавил: {current['user'].mention}"
            )
            await last_playing_message.edit(embed=create_embed("Сейчас играет", description))
            return
        except:
            pass

    position = time.time() - start_time if not is_paused else current.get('position', 0)
    duration = current.get('duration', 0)
    progress_bar = create_progress_bar(position, duration)
    description = (
        f"🎵 **{current['title']}**\n"
        f"{progress_bar}\n"
        f"`{format_duration(position)} / {format_duration(duration)}`\n"
        f"Добавил: {current['user'].mention}"
    )
    last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))

    if not nowplaying_updater and voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        nowplaying_updater = bot.loop.create_task(update_now_playing(ctx, last_playing_message))


@bot.command(name='queue')
async def queue_(ctx, page: int = 1):
    if not queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))

    items_per_page = 10
    total_pages = max(1, (len(queue) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * items_per_page
    end = start + items_per_page
    lines = []
    for i, song in enumerate(queue[start:end], start=start + 1):
        duration = format_duration(song.get('duration', 0))
        lines.append(f"**{i}.** [`{duration}`] {song['title']} - {song['user'].mention}")

    total_duration = sum(song.get('duration', 0) for song in queue)
    header = f"Текущая очередь | {len(queue)} треков | {format_duration(total_duration)} | Страница {page}/{total_pages}"
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
                for i, song in enumerate(queue[start:end], start=start + 1):
                    duration = format_duration(song.get('duration', 0))
                    lines.append(f"**{i}.** [`{duration}`] {song['title']} - {song['user'].mention}")

                header = f"Текущая очередь | {len(queue)} треков | {format_duration(total_duration)} | Страница {page}/{total_pages}"
                embed = create_embed(header, "\n".join(lines), color=0xB0C4DE)
                await message.edit(embed=embed)
                await message.remove_reaction(reaction, user)

        except asyncio.TimeoutError:
            await message.clear_reactions()


@bot.command()
async def remove(ctx, arg: str):
    global queue
    if not queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))
    if arg == 'all':
        queue.clear()
        await ctx.send(embed=create_embed("Очищено", "Очередь была полностью очищена."))
    else:
        try:
            index = int(arg) - 1
            if 0 <= index < len(queue):
                removed = queue.pop(index)
                await ctx.send(embed=create_embed("Удалено", f"🗑️ {removed['title']}"))
            else:
                await ctx.send(embed=create_embed("Ошибка", "Неверный индекс!"))
        except ValueError:
            await ctx.send(embed=create_embed("Ошибка", "Используйте число или 'all'"))


@bot.command()
async def skip(ctx):
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send(embed=create_embed("Пропущено", "⏭️ Песня была пропущена."))
    else:
        await ctx.send(embed=create_embed("Ошибка", "Сейчас ничего не играет."))


@bot.command()
async def stop(ctx):
    global voice_client, queue, current, is_radio, is_looping, is_paused, last_playing_message, nowplaying_updater

    if nowplaying_updater:
        nowplaying_updater.cancel()
        nowplaying_updater = None

    if voice_client:
        voice_client.stop()
        if voice_client.is_connected():
            await voice_client.disconnect()
        voice_client = None

    queue.clear()
    current = None
    is_radio = False
    is_looping = False
    is_paused = False
    last_playing_message = None

    await ctx.send(embed=create_embed("Остановлено", "⏹️ Воспроизведение остановлено и бот отключен."))


@bot.command()
async def pause(ctx):
    global is_paused
    if not voice_client or not voice_client.is_connected():
        return await ctx.send(embed=create_embed("Ошибка", "Бот не подключен к голосовому каналу."))
    if voice_client.is_playing():
        voice_client.pause()
        is_paused = True
        await ctx.send(embed=create_embed("Пауза", "⏸️ Воспроизведение приостановлено."))
    elif voice_client.is_paused():
        voice_client.resume()
        is_paused = False
        await ctx.send(embed=create_embed("Продолжено", "▶️ Воспроизведение возобновлено."))
    else:
        await ctx.send(embed=create_embed("Ошибка", "Сейчас ничего не играет."))


@bot.command()
async def volume(ctx, level: int = None):
    global current_volume
    if level is None:
        return await ctx.send(embed=create_embed(
            "Громкость",
            f"🔊 Текущая громкость: {int(current_volume * 100)}%"
        ))
    if not 0 <= level <= 150:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Уровень громкости должен быть между 0 и 150"
        ))
    current_volume = level / 100
    if voice_client and voice_client.source:
        voice_client.source.volume = current_volume
    await ctx.send(embed=create_embed(
        "Громкость",
        f"🔊 Установлена громкость: {level}%"
    ))


@bot.command()
async def shuffle(ctx):
    if not queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))
    random.shuffle(queue)
    await ctx.send(embed=create_embed("Перемешано", "🔀 Очередь перемешана."))


@bot.command()
async def search(ctx, *, query: str):
    global voice_client

    if is_valid_url(query):
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Для поиска используйте только текст. Для воспроизведения по ссылке используйте `?play`."
        ))

    if is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    try:
        if not voice_client or not voice_client.is_connected():
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)
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
    embed.set_footer(text="Выберите трек или нажмите ❌ для отмены")
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

            queue.append({
                'url': url,
                'title': title,
                'duration': duration,
                'user': ctx.author
            })

            await ctx.send(embed=create_embed(
                "Добавлено в очередь",
                f"✅ **{title}** (`{format_duration(duration)}`)\nДобавил: {ctx.author.mention}"
            ))

            if not voice_client.is_playing() and not is_paused:
                await play_next(ctx)

            await message.delete()
    except asyncio.TimeoutError:
        await message.delete()
        await ctx.send(embed=create_embed("Время вышло", "Выбор трека отменен."))


@bot.command()
async def seek(ctx, seconds_str: str):
    global current, start_time, voice_client, is_seeking, last_playing_message
    if not current or not voice_client or not voice_client.is_playing():
        return await ctx.send(embed=create_embed("Ошибка", "Ничего не играет."))
    if not seconds_str.startswith(('+', '-')):
        return await ctx.send(embed=create_embed("Ошибка", "Используйте формат: `?seek +30` или `?seek -15`"))
    try:
        seconds = int(seconds_str)
    except ValueError:
        return await ctx.send(embed=create_embed("Ошибка", "Введите целое число секунд"))

    current_position = time.time() - start_time
    new_position = max(0, current_position + seconds)
    duration = current.get('duration', 0)
    if new_position > duration:
        return await ctx.send(embed=create_embed("Ошибка", "Время превышает длительность трека."))

    start_time = time.time() - new_position
    is_seeking = True
    try:
        voice_client.stop()
        url = current['url']
        seek_options = {
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {new_position}',
            'options': '-vn'
        }
        source = discord.FFmpegPCMAudio(url, **seek_options)
        source = discord.PCMVolumeTransformer(source, volume=current_volume)

        def after_seek(e):
            global is_seeking
            is_seeking = False
            fut = play_next(ctx)
            asyncio.run_coroutine_threadsafe(fut, bot.loop)

        voice_client.play(source, after=after_seek)
        await ctx.send(embed=create_embed("Перемотка", f"⏩ Установлена позиция: {format_duration(new_position)}"))
        if last_playing_message:
            try:
                progress_bar = create_progress_bar(new_position, duration)
                description = (
                    f"🎵 **{current['title']}**\n"
                    f"{progress_bar}\n"
                    f"`{format_duration(new_position)} / {format_duration(duration)}`\n"
                    f"Добавил: {current['user'].mention}"
                )
                await last_playing_message.edit(embed=create_embed("Сейчас играет", description))
            except:
                pass
    except Exception as e:
        is_seeking = False
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
    global voice_client, is_radio, current, is_paused, queue, last_playing_message
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
    queue.clear()
    current = None
    last_playing_message = None
    is_radio = True
    is_paused = False
    is_looping = False
    try:
        if not ctx.author.voice:
            return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))
        if not voice_client or not voice_client.is_connected():
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    def after_playing(e):
        fut = play_next(ctx)
        asyncio.run_coroutine_threadsafe(fut, bot.loop)

    try:
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        source = discord.PCMVolumeTransformer(source, current_volume)
        if voice_client:
            voice_client.play(source, after=after_playing)
            await ctx.send(embed=create_embed("Радио", f"📻 {url}"))
    except Exception as e:
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось воспроизвести радио: {e}"))


@bot.command()
async def loop(ctx):
    global is_looping
    is_looping = not is_looping
    await ctx.send(embed=create_embed("Повтор", f"🔁 {'Повтор включён' if is_looping else 'Повтор выключен'}"))


# Замените на ваш токен
bot.run('MTIyMzc2MDExODQ0NTg5OTc4Ng.GRgLzk.a-62rexOHKYytHxRdDFfU9PlDT0NIvkzcAESmA')
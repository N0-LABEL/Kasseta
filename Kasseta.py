import discord
from discord.ext import commands
import asyncio
import yt_dlp
import datetime
import random
import time
from typing import Optional

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
is_seeking = False  # Флаг для отслеживания операции перемотки
start_time = 0
last_playing_message = None  # Для отслеживания последнего сообщения о воспроизведении

# Настройки yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'source_address': '0.0.0.0',
    'noplaylist': True,
    'default_search': 'ytsearch',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
YTDL = yt_dlp.YoutubeDL(ytdl_format_options)


# Вспомогательные функции
def format_duration(seconds):
    if seconds < 0:
        return "0:00"
    return str(datetime.timedelta(seconds=int(seconds))).split('.')[0]


def create_embed(title, description=None, color=0x4682B4):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Межсерверный музыкальный бот | Кассета", icon_url="https://world-ocean.ru/images/main/mkrf_icon.png")
    return embed


def create_progress_bar(position, duration, length=15):
    if duration <= 0:
        return ""
    progress = min(1, max(0, position / duration))
    filled = int(progress * length)
    return "[" + "▬" * filled + "🔘" + "▬" * (length - filled) + "]"


async def play_next(ctx):
    global current, queue, voice_client, is_looping, is_radio, start_time, is_paused, is_seeking, last_playing_message

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

    # Отправляем сообщение только если это не повтор
    if not (is_looping and last_playing_message):
        progress_bar = create_progress_bar(0, duration)
        description = (
            f"🎵 **{title}**\n"
            f"{progress_bar}\n"
            f"`00:00 / {format_duration(duration)}`\n"
            f"Добавил: {user.mention}"
        )
        last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))

    def after_playing(e):
        if not is_seeking:
            fut = play_next(ctx)
            asyncio.run_coroutine_threadsafe(fut, bot.loop)

    try:
        source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
        source = discord.PCMVolumeTransformer(source, volume=current_volume)

        if voice_client:
            voice_client.play(source, after=after_playing)
    except Exception as e:
        print(f"Ошибка воспроизведения: {e}")
        fut = play_next(ctx)
        asyncio.run_coroutine_threadsafe(fut, bot.loop)


# События бота
@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="?help")
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    print(f"Бот запущен как {bot.user}")


# Команды бота
@bot.command()
async def about(ctx):
    """Информация о боте"""
    await ctx.send(embed=create_embed(
        "О боте",
        "🎶 Кассета — это универсальный музыкальный бот с широким функционалом. "
        "Умеет воспроизводить музыку с YouTube, плейлисты, перематывать треки и управлять громкостью, "
        "обеспечивая полноценное музыкальное сопровождение для сервера.\n  \n**Сделано в ВФ**"
    ))

@bot.command()
async def ping(ctx):
    """Проверить задержку бота"""
    latency = round(bot.latency * 1000)
    await ctx.send(embed=create_embed("Пинг", f"📡 {latency}ms"))


@bot.command()
async def play(ctx, *, search: str):
    """Воспроизвести трек или плейлист"""
    global voice_client, is_radio, is_paused, queue, current, last_playing_message

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
        info = YTDL.extract_info(search, download=False)
        if 'entries' in info:
            if info['entries']:
                info = info['entries'][0]
            else:
                return await ctx.send(embed=create_embed("Ошибка", "Трек не найден."))

        url = info['url']
        title = info['title']
        duration = info.get('duration', 0)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка", f"Не удалось получить трек: {e}"))

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


@bot.command()
async def radio(ctx, url: str):
    """Воспроизвести радио-поток"""
    global voice_client, is_radio, current, is_paused, queue, last_playing_message

    # Остановить текущее воспроизведение и очистить очередь
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
    """Включить/выключить повтор трека"""
    global is_looping
    is_looping = not is_looping
    await ctx.send(embed=create_embed("Повтор", f"🔁 {'Повтор включён' if is_looping else 'Повтор выключен'}"))


@bot.command()
async def nowplaying(ctx):
    """Показать текущий трек"""
    global last_playing_message

    if current:
        position = time.time() - start_time if not is_paused else current.get('position', 0)
        duration = current.get('duration', 0)

        progress_bar = create_progress_bar(position, duration)
        description = (
            f"🎵 **{current['title']}**\n"
            f"{progress_bar}\n"
            f"`{format_duration(position)} / {format_duration(duration)}`\n"
            f"Добавил: {current['user'].mention}"
        )

        # Обновляем существующее сообщение вместо создания нового
        if last_playing_message:
            try:
                await last_playing_message.edit(embed=create_embed("Сейчас играет", description))
                return
            except:
                pass  # Если не получилось обновить, отправляем новое

        last_playing_message = await ctx.send(embed=create_embed("Сейчас играет", description))
    else:
        await ctx.send(embed=create_embed("Пусто", "Сейчас ничего не играет."))


@bot.command(name='queue')
async def queue_(ctx, page: int = 1):
    """Показать очередь воспроизведения"""
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
    await ctx.send(embed=create_embed(header, "\n".join(lines), color=0xB0C4DE))


@bot.command()
async def remove(ctx, arg: str):
    """Удалить трек из очереди"""
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
    """Пропустить текущий трек"""
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send(embed=create_embed("Пропущено", "⏭️ Песня была пропущена."))
    else:
        await ctx.send(embed=create_embed("Ошибка", "Сейчас ничего не играет."))


@bot.command()
async def stop(ctx):
    """Остановить воспроизведение"""
    global voice_client, queue, current, is_radio, is_looping, is_paused, last_playing_message
    if voice_client:
        if voice_client.is_playing() or voice_client.is_paused():
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

    await ctx.send(embed=create_embed("Остановлено", "⏹️ Воспроизведение остановлено."))


@bot.command()
async def pause(ctx):
    """Приостановить/возобновить воспроизведение"""
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
    """Установить громкость (0-150)"""
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
    """Перемешать очередь"""
    if not queue:
        return await ctx.send(embed=create_embed("Очередь пуста"))

    random.shuffle(queue)
    await ctx.send(embed=create_embed("Перемешано", "🔀 Очередь перемешана."))


@bot.command()
async def search(ctx, *, query: str):
    """Поиск на YouTube с мгновенным выбором"""
    global voice_client

    if is_radio:
        return await ctx.send(embed=create_embed(
            "Ошибка",
            "Сейчас играет радио. Остановите радио командой `?stop`, чтобы добавить треки в очередь."
        ))

    # Подключение к голосовому каналу
    if not ctx.author.voice:
        return await ctx.send(embed=create_embed("Ошибка", "Вы должны находиться в голосовом канале."))

    try:
        if not voice_client or not voice_client.is_connected():
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка подключения", f"{e}"))

    # Поиск треков
    try:
        results = YTDL.extract_info(f"ytsearch4:{query}", download=False)['entries']
    except Exception as e:
        return await ctx.send(embed=create_embed("Ошибка", f"Не удалось выполнить поиск: {e}"))

    # Создание сообщения с выбором
    lines = []
    for i, entry in enumerate(results, 1):
        duration = format_duration(entry.get('duration', 0))
        lines.append(f"{i}. [`{duration}`] {entry['title']}")

    embed = create_embed(
        f"Результаты поиска по запросу: {query}",
        "\n".join(lines),
        color=0x3498db
    )
    embed.set_footer(text="Выберите трек или нажмите ❌ для отмены")

    message = await ctx.send(embed=embed)

    # Добавление реакций
    reactions = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '❌']
    for i in range(min(len(results), 4)):
        await message.add_reaction(reactions[i])
    await message.add_reaction('❌')

    # Обработка выбора
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == message.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)

        if str(reaction.emoji) == '❌':
            await message.delete()
            return

        index = reactions.index(str(reaction.emoji))
        if index < len(results):
            entry = results[index]
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
    """Перемотать текущий трек (+вперед/-назад в секундах)"""
    global current, start_time, voice_client, is_seeking, last_playing_message

    if not current or not voice_client or not voice_client.is_playing():
        return await ctx.send(embed=create_embed("Ошибка", "Ничего не играет."))

    # Проверка формата
    if not seconds_str.startswith(('+', '-')):
        return await ctx.send(embed=create_embed("Ошибка", "Используйте формат: `?seek +30` или `?seek -15`"))

    try:
        seconds = int(seconds_str)
    except ValueError:
        return await ctx.send(embed=create_embed("Ошибка", "Введите целое число секунд"))

    # Рассчет новой позиции
    current_position = time.time() - start_time
    new_position = max(0, current_position + seconds)
    duration = current.get('duration', 0)

    if new_position > duration:
        return await ctx.send(embed=create_embed("Ошибка", "Время превышает длительность трека."))

    # Обновляем позицию
    start_time = time.time() - new_position

    # Установить флаг перемотки
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
            # Сбросить флаг после завершения перемотки
            global is_seeking
            is_seeking = False
            fut = play_next(ctx)
            asyncio.run_coroutine_threadsafe(fut, bot.loop)

        voice_client.play(source, after=after_seek)
        await ctx.send(embed=create_embed("Перемотка", f"⏩ Установлена позиция: {format_duration(new_position)}"))

        # Обновляем сообщение о текущем треке
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
        is_seeking = False  # Сбросить флаг при ошибке
        await ctx.send(embed=create_embed("Ошибка", f"Не удалось перемотать: {e}"))


@bot.command()
async def playlists(ctx):
    """Информация о плейлистах"""
    await ctx.send(embed=create_embed("Плейлисты", "🎧 Вставьте ссылку на YouTube-плейлист в команду ?play."))


@bot.command()
async def help(ctx):
    """Показать список команд"""
    embed = create_embed("Список команд", color=0x7B68EE)

    commands_list = [
        ("?pause", "Приостановить/возобновить воспроизведение"),
        ("?nowplaying", "Показать текущий трек с прогресс-баром"),
        ("?play <название|URL>", "Воспроизвести трек или плейлист"),
        ("?queue [страница]", "Показать очередь воспроизведения"),
        ("?remove <позиция|all>", "Удалить трек из очереди"),
        ("?search <запрос>", "Поиск на YouTube с мгновенным выбором"),
        ("?seek <+/-секунды>", "Перемотка вперед/назад в секундах"),
        ("?shuffle", "Перемешать очередь"),
        ("?skip", "Пропустить текущий трек"),
        ("?stop", "Остановить воспроизведение и очистить очередь"),
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

# Замените на ваш токен
bot.run('')


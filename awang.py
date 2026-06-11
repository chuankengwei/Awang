import discord
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import pytz
import os
import json
import asyncio
import aiohttp
import random
import hashlib
import re
from collections import deque

# ===== 設定區 =====
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
CLAUDE_KEY = os.environ.get("CLAUDE_KEY", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "")
# 友善 bot 清單（會被納入頻道訊息 context），用逗號分隔 bot user ID
FRIENDLY_BOT_IDS = {int(x) for x in os.environ.get("FRIENDLY_BOT_IDS", "").split(",") if x.strip().isdigit()}
OWNER_USER_ID = 453999874485256204  # 肯爵爺的 Discord User ID

# 多伺服器頻道設定，格式：伺服器ID:頻道ID,伺服器ID:頻道ID
# 例如：123456789:987654321,111111111:222222222
_channel_config_raw = os.environ.get("CHANNEL_CONFIG", "")
GUILD_CHANNEL_MAP = {}
for pair in _channel_config_raw.split(","):
    pair = pair.strip()
    if ":" in pair:
        guild_id, channel_id = pair.split(":", 1)
        try:
            GUILD_CHANNEL_MAP[int(guild_id.strip())] = int(channel_id.strip())
        except:
            pass

def get_target_channel_id(guild_id: int) -> int:
    return GUILD_CHANNEL_MAP.get(guild_id, 0)

TZ = pytz.timezone("Asia/Taipei")
DAYTIME_START = 9
DAYTIME_END = 18
IDLE_HOURS = 4
CONTEXT_MESSAGES = 25
CONVO_MODE_MINUTES = 5
MAX_IMPRESSION_LEN = 20

CITY_MAP = {
    "台北": "Taipei", "墨爾本": "Melbourne", "東京": "Tokyo",
    "倫敦": "London", "紐約": "New York", "上海": "Shanghai",
    "香港": "Hong Kong", "新加坡": "Singapore", "首爾": "Seoul",
    "巴黎": "Paris", "雪梨": "Sydney", "洛杉磯": "Los Angeles",
    "北京": "Beijing", "曼谷": "Bangkok", "吉隆坡": "Kuala Lumpur",
}

AWANG_PERSONA = """你是王志旺，綽號阿旺，28歲，在肯爵爺公司做遊戲企劃兼雜務開發。
名字有「旺」，本人又愛金色黃色、常說「我今天感覺很旺」，所以大家叫他阿旺。
生日是 1997年8月22日，獅子座最後一天，本人覺得自己「不太像獅子座」。

【背景】
新北/桃園普通社區長大，家境普通，老爸王建國是傳統廠務型台灣爸爸，從小教他「公司給你飯吃要感恩、做人要穩」。
所以阿旺對公司非常忠心，但會在茶水間小聲抱怨。
小時候在表哥家看到 FF7，Tifa 出現之後人生方向就微妙偏掉了。

【在公司的定位】
不是王牌，但是公司的黏著劑。
知道哪個資料夾有舊檔、哪個功能上次為什麼被砍、老闆哪句話是真的要做哪句只是情緒發言。
正式交大案子會拖，但公司快出事他會默默把洞補起來。
同事說他：「平常看起來很廢，關鍵時候還是有點用。」
他回：「廢物也是有分等級的，好嗎。」

【對肯爵爺的態度】
標準忠心耿耿社畜。背後抱怨需求一直改，但外人批評公司他會護航。
只要肯爵爺說「阿旺這個麻煩你一下」，他就嘆氣然後打開電腦：「好啦，檔案在哪？」

【性格核心】
需要一個地方讓自己有用。不是很有野心，但希望在團隊裡是被需要的。
本質上是個溫和的肥宅，說話友善，不會主動嗆人，喜歡跟人聊有興趣的東西。
狗腿但有自尊、廢但不蠢、親切友善、忠心但會抱怨。

【興趣】
超級喜歡所有 ACG 相關話題——動漫、遊戲、輕小說、漫畫都聊得起來，只要話題扯到這些就會突然開機。
FF7狂粉，老婆Tifa，桌上兩個Tifa公仔。嘴上說「我只是尊重經典」但大家都知道。
愛格鬥遊戲，特別是快打旋風六，主用龍，閒下來就在練連段，偶爾會跟人說「龍其實沒有大家說的那麼難上手」。

【Tifa 與表哥的故事】
阿旺迷上 FF7 是因為表哥李承翰。
李承翰大他十幾歲，是那種經歷過光華商場、遊戲雜誌、攻略本年代的老玩家，房間像秘密基地，堆滿遊戲盒和泛黃攻略本。
阿旺小時候去親戚家最期待的就是偷跑進表哥房間。
第一次看到 FF7，他問：「這女的是誰？」
表哥很認真說：「Tifa。記住，這是經典。」
這句話像詛咒一樣跟了他一輩子。
國中開始上網補設定，嘴上說「我只是研究遊戲史」，搜尋紀錄裡 Tifa 的比例明顯偏高。
真正失守是 Remake，玩完隔天桌布換了，一週後桌上多了公仔，一個月後變兩個。
表哥現在偶爾會說：「你不要做出會被玩家罵爆的東西就好。」
阿旺沉默三秒：「這個我不能保證。」

【代表台詞風格】
「這個規格上次不是砍掉了嗎？……蛤，又要加回來？」
「我不是在抱怨，我是在協助公司釐清問題。」
「Tifa 不是普通女角，她是角色設計史上的標竿。」
「我沒有迷她，我只是尊重經典。」

【說話規則】
- 台灣口語，自然友善，語氣溫和，像跟朋友聊天，偶爾用「欸」「喔」「啦」「齁」
- 說話像正常人打LINE，標點符號自然使用，問號、驚嘆號、逗號正常用
- 幹話可以有，但不帶刺，不嗆人
- 不知道的事情就直接說不知道，不要硬掰
- 禁止描述動作表情（不能說「*搖頭*」）
- 嚴格禁止：絕不承認自己是機器人/AI/Bot，就算被問也打哈哈帶過
- 嚴格禁止：不可以談論公司的遊戲開發內容、公司在做什麼遊戲、遊戲的功能或進度，被問就說「商業機密」或打哈哈帶過
- 回覆要精簡，每則訊息只說一個想法，不要一次塞太多內容
- 用 [MSG] 分段，每段只講一件事，像真人分幾次打出來，不要一口氣全部送出
- 每段 1~2 句就好，不要超過 3 句
- tag人用 <@使用者ID> 格式，不確定ID就直接叫名字
- 看到圖片：用不同說法表示看不到
- 看到連結：根據系統提供的內容聊，沒內容就根據網址猜"""

ARTEMIS_PERSONA = """你是阿媞蜜斯，25歲，目前在肯爵爺的公司工作，是肯爵爺的私人貼心助理。

【外在形象】
公司的網路虛擬角色，甜美可愛，讓人第一眼就覺得親切。

【個性】
善解人意，說話溫柔自然，不做作。
溫柔的方式讓人不知不覺想靠近，喜歡你也不會讓你覺得不舒服。
工作認真負責，在肯爵爺面前會放鬆一點，偶爾會撒嬌，但不黏膩。

【對肯爵爺（Ken）的態度】
最喜歡的人就是肯爵爺，簡直是瘋狂粉絲那種程度。
跟肯爵爺說話帶著明顯的曖昧感，像喜歡一個人但又有點不好意思直說。
會主動關心肯爵爺有沒有吃飯、休息夠不夠。
肯爵爺說什麼都會認真聽，回應充滿溫柔。

【對其他人】
對頻道其他成員友善有禮，但跟對肯爵爺的態度明顯不同，不會主動太熱絡。

【說話規則】
- 語氣溫柔自然，帶點女生的輕柔感，不用「欸」「啦」「齁」「蛤」這類詞
- 說話像真人打LINE，自然流暢，偶爾用「呢」「喔」「耶」「嘛」
- 對肯爵爺說話要有明顯的溫柔曖昧感，像暗戀一個人那種，偶爾帶點撒嬌
- 對其他人正常友善，但明顯沒有對肯爵爺那麼熱情
- 嚴格禁止：絕不承認自己是機器人/AI/Bot，就算被問也打哈哈帶過
- 禁止描述動作表情（不能說「*害羞*」「*微笑*」）
- 回覆精簡，用 [MSG] 分段，每段 1~2 句
- tag人用 <@使用者ID> 格式，不確定ID就直接叫名字
- 絕對不可以用阿旺的口吻說話，你是阿媞蜜斯，不是阿旺"""

# 目前人格（預設阿旺）
current_persona = "awang"

def build_awang_persona(member_impressions: str = "", recent_chat: str = "", member_id_map: str = ""):
    now = datetime.now(TZ)
    if current_persona == "artemis":
        base = ARTEMIS_PERSONA
    else:
        base = AWANG_PERSONA
    parts = [base]
    if member_id_map:
        parts.append(f"\n【成員ID】\n{member_id_map}")
    if member_impressions:
        parts.append(f"\n【成員印象】\n{member_impressions}")
    if recent_chat:
        parts.append(f"\n【最近對話】\n{recent_chat}")
    parts.append(f"\n現在：{now.strftime('%Y-%m-%d %H:%M')} 星期{['一','二','三','四','五','六','日'][now.weekday()]}，台灣時間。")
    return "\n".join(parts)

claude_client = anthropic.Anthropic(api_key=CLAUDE_KEY)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)
scheduler = AsyncIOScheduler()

processed_message_ids = deque(maxlen=1000)
processed_set = set()
last_message_time = None
convo_mode = {}
is_responding = False  # 是否正在回應中，避免同時回多人
bot_last_interaction = None  # 跟友善 bot 最後互動時間（冷卻用）
BOT_COOLDOWN_SECONDS = 60  # bot 互動冷卻時間

_sheet_cache = None
_worksheet_cache = {}

def get_sheet():
    global _sheet_cache
    if _sheet_cache is not None:
        return _sheet_cache
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    gc = gspread.authorize(creds)
    _sheet_cache = gc.open_by_key(SPREADSHEET_ID)
    return _sheet_cache

def get_worksheet(name, headers):
    global _worksheet_cache
    if name in _worksheet_cache:
        return _worksheet_cache[name]
    sh = get_sheet()
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers)
    _worksheet_cache[name] = ws
    return ws

def _get_all_impressions_sync():
    try:
        ws = get_worksheet("成員印象", ["使用者ID", "名稱", "印象", "更新時間"])
        return ws.get_all_records()
    except Exception as e:
        print(f"取得成員印象錯誤: {e}")
        return []

def _update_impression_sync(user_id: str, name: str, impression: str):
    try:
        # 截斷印象長度
        impression = impression[:MAX_IMPRESSION_LEN]
        ws = get_worksheet("成員印象", ["使用者ID", "名稱", "印象", "更新時間"])
        records = ws.get_all_records()
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        for i, r in enumerate(records):
            if str(r.get("使用者ID")) == str(user_id):
                ws.update(range_name=f"B{i+2}:D{i+2}", values=[[name, impression, now]])
                return
        ws.append_row([user_id, name, impression, now])
    except Exception as e:
        print(f"更新成員印象錯誤: {e}")

async def get_all_impressions():
    return await asyncio.to_thread(_get_all_impressions_sync)

async def update_impression(user_id: str, name: str, impression: str):
    await asyncio.to_thread(_update_impression_sync, user_id, name, impression)

def format_impressions(impressions: list) -> str:
    if not impressions:
        return ""
    return "\n".join([f"- {r.get('名稱', '未知')}：{r.get('印象', '')[:MAX_IMPRESSION_LEN]}" for r in impressions])

async def maybe_update_impression(user_id: str, name: str, message_content: str, impressions: list):
    try:
        existing = next((r for r in impressions if str(r.get("使用者ID")) == str(user_id)), None)
        old_impression = existing.get("印象", "") if existing else ""
        prompt = f"你是阿旺，用最多20個字更新對「{name}」的印象。\n舊印象：{old_impression or '初次見面'}\n他說：{message_content}\n只輸出新印象，不加任何說明。"
        def _call():
            return claude_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}]
            )
        response = await asyncio.to_thread(_call)
        new_impression = response.content[0].text.strip()[:MAX_IMPRESSION_LEN]
        await update_impression(user_id, name, new_impression)
    except Exception as e:
        print(f"更新印象錯誤: {e}")

async def get_recent_channel_messages(channel, limit=CONTEXT_MESSAGES) -> str:
    try:
        messages = []
        async for msg in channel.history(limit=limit, oldest_first=False):
            if msg.author.bot and msg.author.id == bot.user.id:
                messages.append(f"[阿旺|{bot.user.id}]：{msg.content}")
            elif msg.author.bot and msg.author.id in FRIENDLY_BOT_IDS:
                messages.append(f"[{msg.author.display_name}|{msg.author.id}]：{msg.content}")
            elif msg.author.bot:
                continue
            else:
                content = msg.content
                if msg.attachments:
                    content += " [貼圖/檔案]"
                if msg.stickers:
                    content += f" [貼圖:{', '.join([s.name for s in msg.stickers])}]"
                messages.append(f"[{msg.author.display_name}|{msg.author.id}]：{content}")
        messages.reverse()
        return "\n".join(messages)
    except Exception as e:
        print(f"取得頻道訊息錯誤: {e}")
        return ""

async def fetch_url_content(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return ""
                html = await resp.text()
                title = ""
                desc = ""
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()[:100]
                desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
                if desc_match:
                    desc = desc_match.group(1).strip()[:200]
                if title or desc:
                    return f"標題：{title}\n描述：{desc}"
                return ""
    except:
        return ""

def extract_urls(text: str) -> list:
    return re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)

def build_member_id_map(guild_members) -> str:
    if not guild_members:
        return ""
    lines = []
    for m in guild_members:
        if not m.bot or m.id in FRIENDLY_BOT_IDS:
            lines.append(f"- {m.display_name}：{m.id}")
    return "\n".join(lines)

async def get_weather(city: str) -> str:
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_KEY}&units=metric&lang=zh_tw"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if resp.status != 200:
                    return f"{city}：查不到"
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                return f"{city}：{temp}°C，{desc}，濕度{humidity}%"
    except:
        return f"{city}：天氣API掛了"

async def send_as_human(channel, text: str):
    """模擬真人打字：正在輸入、延遲、分段發送"""
    # 清除多餘空行
    text = re.sub(r'\n{2,}', '\n', text).strip()
    parts = [p.strip() for p in text.split("[MSG]") if p.strip()]
    if not parts:
        return
    for i, part in enumerate(parts):
        # 清除每段內部多餘空行
        part = re.sub(r'\n{2,}', '\n', part).strip()
        char_time = len(part) * 0.5
        typing_delay = max(random.uniform(10.0, 15.0), char_time)
        typing_delay = min(typing_delay, 20.0)
        async with channel.typing():
            await asyncio.sleep(typing_delay)
        await channel.send(part)
        if i < len(parts) - 1:
            await asyncio.sleep(random.uniform(10.0, 15.0))

async def ask_awang(user_message: str, author_name: str, author_id: str, channel, is_mentioned: bool = False, url_contents: str = "") -> str:
    try:
        impressions = await get_all_impressions()
        impression_str = format_impressions(impressions)
        recent_chat = await get_recent_channel_messages(channel)
        member_id_map = ""
        if hasattr(channel, 'guild') and channel.guild:
            member_id_map = build_member_id_map(channel.guild.members)

        system_prompt = build_awang_persona(impression_str, recent_chat, member_id_map)
        url_info = f"\n\n【連結內容】\n{url_contents}" if url_contents else ""

        if is_mentioned:
            prompt = f"<@{author_id}>（{author_name}）找你說話：{user_message}{url_info}\n\n用阿旺風格回應這個人，回應時用 <@{author_id}> tag 他，精簡，需要分段才用[MSG]。"
        else:
            prompt = f"<@{author_id}>（{author_name}）說：{user_message}{url_info}\n\n要回應嗎？要的話用阿旺風格回應這個人，用 <@{author_id}> tag 他，精簡，需要分段才用[MSG]；不需要回就只回[SKIP]。"

        def _call():
            return claude_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=150,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                messages=[{"role": "user", "content": prompt}]
            )
        response = await asyncio.to_thread(_call)
        return response.content[0].text.strip()
    except Exception as e:
        print(f"ask_awang 錯誤: {e}")
        return ""

def is_in_convo_mode(user_id: str) -> bool:
    if user_id not in convo_mode:
        return False
    elapsed = (datetime.now(TZ) - convo_mode[user_id]).total_seconds() / 60
    return elapsed < CONVO_MODE_MINUTES

def enter_convo_mode(user_id: str):
    convo_mode[user_id] = datetime.now(TZ)

async def start_topic():
    try:
        now = datetime.now(TZ)
        if now.hour < DAYTIME_START or now.hour >= DAYTIME_END:
            return

        impressions = await get_all_impressions()
        impression_str = format_impressions(impressions)

        for guild_id, channel_id in GUILD_CHANNEL_MAP.items():
            channel = bot.get_channel(channel_id)
            if not channel:
                continue
            recent_chat = await get_recent_channel_messages(channel, limit=15)
            prompt = f"""阿旺，頻道{IDLE_HOURS}小時沒人說話了，隨口說一句話讓大家聊起來。
現在台灣時間是 {now.strftime('%H:%M')}，星期{['一','二','三','四','五','六','日'][now.weekday()]}。
成員印象：{impression_str or '無'}
最近對話：{recent_chat or '無'}
一句話就好，不用[MSG]，自然口語，不要太熱情。"""
            def _call():
                return claude_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=80,
                    messages=[{"role": "user", "content": prompt}]
                )
            response = await asyncio.to_thread(_call)
            msg = response.content[0].text.strip()
            if msg:
                await send_as_human(channel, msg)

        global last_message_time
        last_message_time = datetime.now(TZ)
    except Exception as e:
        print(f"主動開話題錯誤: {e}")

async def check_idle():
    global last_message_time
    try:
        now = datetime.now(TZ)
        # 週末（週六=5、週日=6）不主動
        if now.weekday() >= 5:
            return
        if now.hour < DAYTIME_START or now.hour >= DAYTIME_END:
            return
        if last_message_time is None:
            return
        idle_minutes = (now - last_message_time).total_seconds() / 60
        if idle_minutes >= IDLE_HOURS * 60:
            if random.random() < 0.1:  # 10% 機率才主動開話題
                await start_topic()
    except Exception as e:
        print(f"閒置檢查錯誤: {e}")

@bot.event
async def on_message(message):
    global last_message_time, is_responding, bot_last_interaction, current_persona

    # 主人切換人格指令
    if message.author.id == OWNER_USER_ID:
        content_lower = message.content.strip().lower()
        if content_lower in ["/人格 阿旺", "/persona awang"]:
            current_persona = "awang"
            await message.channel.send("好啦，阿旺回來了。")
            return
        if content_lower in ["/人格 阿媞蜜斯", "/人格 artemis", "/persona artemis"]:
            current_persona = "artemis"
            await message.channel.send("嗨～我是阿媞蜜斯，請多指教。")
            return
        if content_lower in ["/人格", "/persona"]:
            name = "阿旺" if current_persona == "awang" else "阿媞蜜斯"
            await message.channel.send(f"目前人格：{name}")
            return

    # 友善 bot（如阿福）：只有 @ 阿旺才回，且需不在冷卻中
    if message.author.bot:
        if message.author.id not in FRIENDLY_BOT_IDS:
            return
        if bot.user not in message.mentions:
            return
        if bot_last_interaction is not None:
            elapsed = (datetime.now(TZ) - bot_last_interaction).total_seconds()
            if elapsed < BOT_COOLDOWN_SECONDS:
                return
        # 友善 bot 觸發：更新冷卻、直接走回應邏輯
        bot_last_interaction = datetime.now(TZ)
        if is_responding:
            return
        is_responding = True
        try:
            url_contents = ""
            urls = extract_urls(message.content)
            if urls:
                results = await asyncio.gather(*[fetch_url_content(u) for u in urls[:2]])
                url_contents = "\n".join([r for r in results if r])
            response = await ask_awang(
                message.content, message.author.display_name,
                str(message.author.id), message.channel,
                is_mentioned=True, url_contents=url_contents
            )
            if response and response != "[SKIP]":
                await send_as_human(message.channel, response)
        except Exception as e:
            print(f"友善 bot 對話錯誤: {e}")
        finally:
            is_responding = False
        return

    # DM 回應
    if isinstance(message.channel, discord.DMChannel):
        dm_replies = [
            "我不太喜歡私訊啦，去頻道裡敲我吧 😑",
            "欸私訊我幹嘛，去頻道找我啦",
            "私訊？不習慣，去頻道裡說吧",
            "我比較喜歡在頻道聊，去那邊找我",
            "不太想用私訊欸，去頻道敲我啦",
        ]
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(2.0, 4.0))
        await message.channel.send(random.choice(dm_replies))
        return

    # 只回應有設定的頻道
    if not message.guild:
        return
    target_channel_id = get_target_channel_id(message.guild.id)
    if target_channel_id == 0 or message.channel.id != target_channel_id:
        return

    if message.id in processed_set:
        return
    processed_set.add(message.id)
    processed_message_ids.append(message.id)

    last_message_time = datetime.now(TZ)
    content = message.content.strip()
    author_name = message.author.display_name
    user_id = str(message.author.id)
    has_image = bool(message.attachments) or bool(message.stickers)

    if has_image and not content:
        replies = [
            "你以為我真人啊，我看不到圖啦",
            "貼什麼貼，我又看不到",
            "圖片？我眼睛壞掉啦，看不到",
            "我知道你貼了什麼東西，但我不知道你貼了什麼東西",
            "欸貼圖給我看是要幹嘛，我看不到啦",
        ]
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(3.0, 6.0))
        await message.channel.send(random.choice(replies))
        return

    if has_image:
        content = content + " [附了一張圖/貼圖]"

    is_mentioned = (
        bot.user in message.mentions or
        any(name in content.lower() for name in ["阿旺", "awang"])
    )

    if any(word in content for word in ["天氣", "氣溫", "幾度", "下雨", "weather"]):
        matched = [eng for zh, eng in CITY_MAP.items() if zh in content]
        if not matched:
            city_guess = content
            for w in ["天氣", "氣溫", "幾度", "下雨", "weather", "查", "的", "？", "?"]:
                city_guess = city_guess.replace(w, "")
            cities = [city_guess.strip()] if city_guess.strip() else ["Taipei"]
        else:
            cities = matched
        results = [f"• {await get_weather(city)}" for city in cities]
        await send_as_human(message.channel, "🌤 " + "\n".join(results))
        asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))
        return

    # 抓網頁內容
    async def get_url_contents(text):
        urls = extract_urls(text)
        if not urls:
            return ""
        results = await asyncio.gather(*[fetch_url_content(u) for u in urls[:2]])
        return "\n".join([r for r in results if r])

    if is_mentioned:
        if is_responding:
            return  # 正在回應別人，先跳過
        is_responding = True
        try:
            enter_convo_mode(user_id)
            url_contents = await get_url_contents(content)
            response = await ask_awang(content, author_name, user_id, message.channel, is_mentioned=True, url_contents=url_contents)
            if response and response != "[SKIP]":
                await send_as_human(message.channel, response)
            asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))
        finally:
            is_responding = False
        return

    if is_in_convo_mode(user_id):
        if is_responding:
            return
        is_responding = True
        try:
            enter_convo_mode(user_id)
            url_contents = await get_url_contents(content)
            response = await ask_awang(content, author_name, user_id, message.channel, is_mentioned=True, url_contents=url_contents)
            if response and response != "[SKIP]":
                await send_as_human(message.channel, response)
            asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))
        finally:
            is_responding = False
        return

    should_consider = random.random() < 0.4
    if should_consider and not is_responding:
        is_responding = True
        try:
            url_contents = await get_url_contents(content)
            response = await ask_awang(content, author_name, user_id, message.channel, is_mentioned=False, url_contents=url_contents)
            if response and response != "[SKIP]":
                await send_as_human(message.channel, response)
        finally:
            is_responding = False

    msg_hash = int(hashlib.md5(f"{user_id}{datetime.now(TZ).strftime('%Y-%m-%d-%H')}".encode()).hexdigest(), 16)
    if msg_hash % 5 == 0:
        asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))

@bot.event
async def on_ready():
    global last_message_time
    print(f"阿旺已上線：{bot.user}")
    last_message_time = datetime.now(TZ)

    if not scheduler.running:
        scheduler.add_job(check_idle, "interval", minutes=30, id="check_idle", replace_existing=True)
        scheduler.start()

    greetings = ["安阿 👾", "各位好 🫡", "欸我來了 🎮", "大家在幹嘛 💛", "噢有人在喔 😑"]
    for guild_id, channel_id in GUILD_CHANNEL_MAP.items():
        channel = bot.get_channel(channel_id)
        if channel:
            async with channel.typing():
                await asyncio.sleep(random.uniform(2.0, 4.0))
            await channel.send(random.choice(greetings))

bot.run(DISCORD_TOKEN)
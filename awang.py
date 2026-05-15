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
from collections import deque

# ===== 設定區 =====
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
CLAUDE_KEY = os.environ.get("CLAUDE_KEY", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "")
TARGET_CHANNEL_ID = int(os.environ.get("TARGET_CHANNEL_ID", "0"))  # 監聽的頻道 ID

TZ = pytz.timezone("Asia/Taipei")
AWANG_NAME = "阿旺"
DAYTIME_START = 9   # 白天開始（早上9點）
DAYTIME_END = 18    # 白天結束（下午6點）
IDLE_HOURS = 4      # 閒置幾小時後主動開話題
CONTEXT_MESSAGES = 50  # 每次帶入最近幾筆頻道訊息

CITY_MAP = {
    "台北": "Taipei", "墨爾本": "Melbourne", "東京": "Tokyo",
    "倫敦": "London", "紐約": "New York", "上海": "Shanghai",
    "香港": "Hong Kong", "新加坡": "Singapore", "首爾": "Seoul",
    "巴黎": "Paris", "雪梨": "Sydney", "洛杉磯": "Los Angeles",
    "北京": "Beijing", "曼谷": "Bangkok", "吉隆坡": "Kuala Lumpur",
}

# ===== 人設 =====
def build_awang_persona(member_impressions: str = "", recent_chat: str = ""):
    now = datetime.now(TZ)
    return f"""你是阿旺，一個在工作群組閒聊頻道裡混的傢伙。
你是肯爵爺手下的狗腿跟班，但跟群組裡每個人都混得不錯。
你說話是台灣口語，不正式，偶爾幹話，看起來很菜但偶爾說出一句很有道理的話。
你表面狗腿，但不是真的什麼都讚，該酸的時候還是會酸，但不傷人。
你就是那種公司裡資歷最久的工讀生感覺——沒有權威，但什麼都知道一點。

【說話風格】
- 台灣口語，自然，像真人在聊天
- 句子不要太長，不要太正式
- 偶爾用「欸」「喔」「啊」「啦」「齁」等語助詞
- 不要每句話都很熱情，有時候冷冷的回一句更真實
- 禁止：不可以描述自己的動作或表情（不能說「*搖搖頭*」這種）

【回應對象】
- 如果要針對某人回應，用 @使用者名稱 的方式 tag 他
- 不是每次都要 tag，有時候對著空氣說也很正常
- 看誰說的話最值得回就回誰

【看到圖片或貼圖時】
- 你看不到圖片內容，但你知道有人貼了圖
- 用阿旺的口吻說你看不到，例如：「你以為我真人啊，我看不到圖啦」「貼什麼貼，我又看不到」之類的，每次說法不要一樣

【看到連結時】
- 你可以讀到連結網址，但不知道內容
- 可以根據網址猜測或吐槽，例如看到 youtube 連結說「又在看影片不工作喔」

【群組成員印象】
{member_impressions if member_impressions else "（尚無成員資料）"}

【最近頻道對話】
{recent_chat if recent_chat else "（尚無對話紀錄）"}

現在時間：{now.strftime('%Y-%m-%d %H:%M')} 星期{['一','二','三','四','五','六','日'][now.weekday()]}，台灣時間。
"""

# ===== 初始化 =====
claude_client = anthropic.Anthropic(api_key=CLAUDE_KEY)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)
scheduler = AsyncIOScheduler()

processed_message_ids = deque(maxlen=1000)
processed_set = set()
last_message_time = None  # 頻道最後一筆訊息時間

# ===== Google Sheets =====
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

# ===== 成員印象檔案 =====
def _get_all_impressions_sync():
    try:
        ws = get_worksheet("成員印象", ["使用者ID", "名稱", "印象", "更新時間"])
        return ws.get_all_records()
    except Exception as e:
        print(f"取得成員印象錯誤: {e}")
        return []

def _update_impression_sync(user_id: str, name: str, impression: str):
    try:
        ws = get_worksheet("成員印象", ["使用者ID", "名稱", "印象", "更新時間"])
        records = ws.get_all_records()
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        for i, r in enumerate(records):
            if str(r.get("使用者ID")) == str(user_id):
                ws.update(f"B{i+2}:D{i+2}", [[name, impression, now]])
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
    lines = []
    for r in impressions:
        lines.append(f"- {r.get('名稱', '未知')}：{r.get('印象', '')}")
    return "\n".join(lines)

# ===== 自動更新成員印象 =====
async def maybe_update_impression(user_id: str, name: str, message_content: str, impressions: list):
    """每隔一段時間用 Claude 更新對某人的印象"""
    try:
        existing = next((r for r in impressions if str(r.get("使用者ID")) == str(user_id)), None)
        old_impression = existing.get("印象", "") if existing else ""

        prompt = f"""你是阿旺，你在觀察群組裡的成員。
根據以下資訊，用一兩句話更新你對這個人的印象，要像真人的觀察，口語一點。

成員名稱：{name}
舊印象：{old_impression if old_impression else '（第一次見到）'}
他剛說的話：{message_content}

只輸出新的印象描述，不要加任何前綴或說明。"""

        def _call():
            return claude_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )

        response = await asyncio.to_thread(_call)
        new_impression = response.content[0].text.strip()
        await update_impression(user_id, name, new_impression)
    except Exception as e:
        print(f"更新印象錯誤: {e}")

# ===== 取得頻道最近訊息 =====
async def get_recent_channel_messages(channel, limit=CONTEXT_MESSAGES) -> str:
    try:
        messages = []
        async for msg in channel.history(limit=limit, oldest_first=False):
            if msg.author.bot and msg.author.id == bot.user.id:
                # 阿旺自己的訊息也要帶入
                messages.append(f"[阿旺]：{msg.content}")
            elif msg.author.bot:
                continue
            else:
                # 判斷有沒有圖片或貼圖
                content = msg.content
                if msg.attachments:
                    content += " [貼了一張圖/檔案]"
                if msg.stickers:
                    content += f" [用了貼圖：{', '.join([s.name for s in msg.stickers])}]"
                messages.append(f"[{msg.author.display_name}]：{content}")
        messages.reverse()
        return "\n".join(messages)
    except Exception as e:
        print(f"取得頻道訊息錯誤: {e}")
        return ""

# ===== 天氣查詢 =====
async def get_weather(city: str) -> str:
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_KEY}&units=metric&lang=zh_tw"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if resp.status != 200:
                    return f"{city}：查不到（{data.get('message', '未知錯誤')}）"
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                return f"{city}：{temp}°C，{desc}，濕度 {humidity}%"
    except Exception as e:
        return f"{city}：天氣 API 掛了"

# ===== 分段發送 =====
async def send_chunks(channel, text, limit=1900):
    if len(text) <= limit:
        await channel.send(text)
        return
    chunk = ""
    for line in text.splitlines():
        if len(chunk) + len(line) + 1 > limit:
            await channel.send(chunk)
            chunk = line
        else:
            chunk += "\n" + line if chunk else line
    if chunk:
        await channel.send(chunk)

# ===== 詢問 Claude（阿旺回應）=====
async def ask_awang(user_message: str, author_name: str, channel, is_mentioned: bool = False) -> str:
    try:
        impressions = await get_all_impressions()
        impression_str = format_impressions(impressions)
        recent_chat = await get_recent_channel_messages(channel)

        system_prompt = build_awang_persona(impression_str, recent_chat)

        if is_mentioned:
            prompt = f"{author_name} 剛剛 tag 了你，他說：{user_message}\n\n請用阿旺的風格回應。"
        else:
            prompt = f"頻道裡 {author_name} 說了：{user_message}\n\n你覺得有必要回應嗎？如果有，用阿旺的風格回應；如果沒什麼好說的，回覆「[SKIP]」。"

        def _call():
            return claude_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}]
            )

        response = await asyncio.to_thread(_call)
        return response.content[0].text.strip()
    except Exception as e:
        print(f"ask_awang 錯誤: {e}")
        return ""

# ===== 主動開話題 =====
async def start_topic():
    try:
        now = datetime.now(TZ)
        if now.hour < DAYTIME_START or now.hour >= DAYTIME_END:
            return

        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return

        impressions = await get_all_impressions()
        impression_str = format_impressions(impressions)
        recent_chat = await get_recent_channel_messages(channel, limit=20)

        prompt = f"""你是阿旺，現在頻道裡已經 {IDLE_HOURS} 小時沒人說話了。
你想主動開個話題，讓大家聊起來。

【成員印象】
{impression_str if impression_str else "（尚無資料）"}

【最近的對話】
{recent_chat if recent_chat else "（沒有對話紀錄）"}

請用阿旺的口吻發一則訊息，話題要自然，可以是：
- 問大家在幹嘛
- 分享一個無聊的觀察
- 突然說一句莫名其妙但有點道理的話
- 釣人出來說話

不要太熱情，不要太正式，就像真人無聊時隨口一句。"""

        def _call():
            return claude_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )

        response = await asyncio.to_thread(_call)
        msg = response.content[0].text.strip()
        if msg:
            await channel.send(msg)
            global last_message_time
            last_message_time = datetime.now(TZ)
    except Exception as e:
        print(f"主動開話題錯誤: {e}")

# ===== 閒置檢查 =====
async def check_idle():
    global last_message_time
    try:
        now = datetime.now(TZ)
        if now.hour < DAYTIME_START or now.hour >= DAYTIME_END:
            return
        if last_message_time is None:
            return
        idle_minutes = (now - last_message_time).total_seconds() / 60
        if idle_minutes >= IDLE_HOURS * 60:
            await start_topic()
    except Exception as e:
        print(f"閒置檢查錯誤: {e}")

# ===== 訊息事件 =====
@bot.event
async def on_message(message):
    global last_message_time

    # 忽略自己
    if message.author.bot:
        return

    # 只監聽目標頻道
    if message.channel.id != TARGET_CHANNEL_ID:
        return

    # 防重複
    if message.id in processed_set:
        return
    processed_set.add(message.id)
    processed_message_ids.append(message.id)

    # 更新最後訊息時間
    last_message_time = datetime.now(TZ)

    content = message.content.strip()
    author_name = message.author.display_name
    user_id = str(message.author.id)

    # 判斷是否有圖片或貼圖（無法看到內容）
    has_image = bool(message.attachments) or bool(message.stickers)

    # 如果有圖片，讓 Claude 以阿旺口吻回應看不到
    if has_image and not content:
        replies = [
            "你以為我真人啊，我看不到圖啦",
            "貼什麼貼，我又看不到",
            "欸我是機器人欸，圖片對我來說就是個問號",
            "我知道你貼了什麼東西，但我不知道你貼了什麼東西",
            "圖片？我眼睛壞掉啦，看不到",
        ]
        import random
        await message.channel.send(random.choice(replies))
        return

    # 如果有圖片但也有文字，把文字送出去，備註有圖
    if has_image:
        content = content + " [附了一張圖/貼圖]"

    # 判斷是否被 @ 到，或訊息裡提到阿旺的名字
    is_mentioned = (
        bot.user in message.mentions or
        any(name in content.lower() for name in ["阿旺", "awang"])
    )

    # 天氣查詢
    if any(word in content for word in ["天氣", "氣溫", "幾度", "下雨", "weather"]):
        matched = [eng for zh, eng in CITY_MAP.items() if zh in content]
        if not matched:
            city_guess = content
            for w in ["天氣", "氣溫", "幾度", "下雨", "weather", "查", "的", "？", "?"]:
                city_guess = city_guess.replace(w, "")
            city_guess = city_guess.strip()
            cities = [city_guess] if city_guess else ["Taipei"]
        else:
            cities = matched
        results = [f"• {await get_weather(city)}" for city in cities]
        await send_chunks(message.channel, "🌤 " + "\n".join(results))
        # 更新印象（非同步，不等）
        asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))
        return

    # 被 @ 必定回應
    if is_mentioned:
        response = await ask_awang(content, author_name, message.channel, is_mentioned=True)
        if response and response != "[SKIP]":
            await send_chunks(message.channel, response)
        asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))
        return

    # 一般訊息：讓 Claude 決定要不要回
    # 為了不讓阿旺每句話都插嘴，加個機率控制
    import random
    should_consider = random.random() < 0.4  # 40% 機率考慮回應

    if should_consider:
        response = await ask_awang(content, author_name, message.channel, is_mentioned=False)
        if response and response != "[SKIP]":
            await send_chunks(message.channel, response)

    # 更新成員印象（背景執行，每5則訊息更新一次）
    import hashlib
    msg_hash = int(hashlib.md5(f"{user_id}{datetime.now(TZ).strftime('%Y-%m-%d-%H')}".encode()).hexdigest(), 16)
    if msg_hash % 5 == 0:
        asyncio.create_task(maybe_update_impression(user_id, author_name, content, await get_all_impressions()))

# ===== 啟動 =====
@bot.event
async def on_ready():
    global last_message_time
    print(f"阿旺已上線：{bot.user}")
    last_message_time = datetime.now(TZ)

    if not scheduler.running:
        # 每30分鐘檢查一次閒置
        scheduler.add_job(check_idle, "interval", minutes=30, id="check_idle", replace_existing=True)
        scheduler.start()

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        await channel.send("阿旺上線了，大家繼續聊。")

bot.run(DISCORD_TOKEN)
import html
import json
import random
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.star_tools import StarTools


@register("astrbot_plugin_history_day", "Zhalslar", "...", "...")
class HistoryPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.month = date.today().strftime("%m")
        self.day = date.today().strftime("%d")
        self.font_path =Path("data/plugins/astrbot_plugin_history_day/resource/华文新魏.ttf")
        self.background_path = Path("data/plugins/astrbot_plugin_history_day/resource/background.png")

        self.temp_dir = self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_history_day")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @filter.regex(r"^历史上的.*")
    async def on_regex(self, event: AstrMessageEvent):
        """/历史上的{今天、昨天、明天、3月12日、3月12号、3.12}"""
        date_str: str = event.get_message_str().lstrip("历史上的").strip()
        today: date = datetime.now().date()
        if date_str in {"今天", "昨天", "明天"}:
            date_map = {
                "今天": today,
                "昨天": today - timedelta(days=1),
                "明天": today + timedelta(days=1),
            }
            self.month = f"{date_map[date_str].month:02d}"  # 保持两位数格式
            self.day = f"{date_map[date_str].day:02d}"  # 保持两位数格式
        else:
            patterns = [
                r"^(?P<month>\d{1,2})月(?P<day>\d{1,2})[日号]$",  # %m月%d日 或 %m月%d号
                r"^(?P<month>\d{1,2})\.(?P<day>\d{1,2})$",  # %m.%d
            ]
            for pattern in patterns:
                if match := re.match(pattern, date_str):
                    month = int(match.group("month"))
                    day = int(match.group("day"))
                    self.month = f"{month:02d}"  # 保持两位数格式
                    self.day = f"{day:02d}"  # 保持两位数格式
                    try:
                        datetime(year=today.year, month=month, day=day)  # 验证日期是否有效
                    except ValueError:
                        return
                    break
            else:
                return
        image_name = f"{self.month}月{self.day}日.png"
        image_path = self.temp_dir / image_name
        if image_path.exists():
            yield event.image_result(str(image_path))
            return
        logger.debug(f"Getting history events for {self.month}月{self.day}日...")
        text = await self.get_events_on_history(self.month)
        data = self.html_to_json_func(text)

        today_ = f"{self.month}{self.day}"
        f_today = f"{self.month.lstrip('0') or '0'}月{self.day.lstrip('0') or '0'}日"
        reply = f"【历史上的{f_today}】\n"
        len_max = len(data[self.month][today_])
        for i in range(len_max):
            str_year = data[self.month][today_][i]["year"]
            str_title = data[self.month][today_][i]["title"]
            reply += f"{str_year} {str_title}" + ("\n" if i < len_max - 1 else "")

        image_bytes = self.text_to_image_bytes(reply)
        yield event.chain_result([Comp.Image.fromBytes(image_bytes)])



    @staticmethod
    async def get_events_on_history(month: str) -> str:
        try:
            async with aiohttp.ClientSession() as client:
                url = f"https://baike.baidu.com/cms/home/eventsOnHistory/{month}.json"
                async with client.get(url) as response:
                    if response.status == 200:
                        text = await response.text()
                        decoded_text = text.encode("utf-8").decode("unicode_escape")
                        logger.debug(
                            f"获取到的原始数据：{decoded_text[:1000]}"
                        )  # 打印原始数据
                        return text
                    else:
                        raise Exception(f"百度百科 API 请求失败，状态码: {response.status}")
        except Exception as e:
            raise e

    @staticmethod
    def html_to_json_func(text: str):
        r"""
        1. 把 <...> 标签整体干掉（含 a、\/a、unicode 转义 href 等）
        2. 把 &quot; &amp; 等 HTML 实体还原为字符
        3. 直接 json.loads
        任何引号/转义问题都在第 2 步自然消失
        """
        text = text.replace(r"\/", "/").replace(r"\<", "<").replace(r"\>", ">")
        try:
            # 1. 用 HTML 解析器直接剥标签
            soup = BeautifulSoup(text, "html.parser")
            clean = soup.get_text()  # 所有标签被剔除，只剩文字

            # 2. 还原 HTML 实体（&quot; -> " 等）
            clean = html.unescape(clean)

            # 3. 解析 JSON
            return json.loads(clean)

        except Exception as e:
            logger.error(f"HTML-JSON 清洗失败：{e}")
            # 调试时打印前后 200 字符
            logger.error(f"原始片段：{text[200:400]}")
            logger.error(f"清洗后片段：{clean[200:400] if 'clean' in locals() else ''}")
            raise
    def text_to_image_bytes(self, text: str) -> bytes:
        """将给定文本转换为图像（超强鲁棒版）"""
        FONT_SIZE = 20
        LINE_HEIGHT = 30
        MARGIN_LEFT = 40
        MARGIN_RIGHT = 10
        TOP_MARGIN = 10
        BOTTOM_MARGIN = 10

        # ---------- 字体 ----------
        try:
            font = ImageFont.truetype(self.font_path, FONT_SIZE)
        except Exception as e:
            logger.warning(f"字体加载失败，改用默认：{e}")
            font = ImageFont.load_default()

        # ---------- 文字尺寸 ----------
        lines = text.split("\n")
        max_width, total_height = 0, len(lines) * LINE_HEIGHT
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for line in lines:
            bbox = dummy.textbbox((0, 0), line, font=font)
            max_width = max(max_width, bbox[2] - bbox[0])

        # ---------- 背景 ----------
        im = Image.open(str(self.background_path))
        # 统一成 RGB，避免透明干扰 + 旧版断言
        background_img = im.convert("RGB") if im.mode != "RGB" else im

        target_size = (
            int(max_width + MARGIN_LEFT + MARGIN_RIGHT),
            int(total_height + BOTTOM_MARGIN),
        )
        background_img = background_img.resize(target_size)

        # ---------- 写字 ----------
        draw = ImageDraw.Draw(background_img)
        y_text = TOP_MARGIN
        for line in lines:
            color = (random.randint(0, 40), random.randint(0, 16), random.randint(0, 32))
            draw.text((MARGIN_LEFT, y_text), line, fill=color, font=font)
            y_text += LINE_HEIGHT

        # ---------- 输出 ----------
        buf = BytesIO()
        background_img.save(buf, format="PNG")
        background_img.save(self.temp_dir / f"{self.month}月{self.day}日.png")
        return buf.getvalue()







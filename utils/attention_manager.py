"""

注意力机制管理器模块 - Enhanced Version
负责管理AI对多个用户的注意力和情绪态度，实现更自然的对话焦点

核心功能：
1. 多用户注意力追踪 - 同时记录多个用户的注意力分数
2. 渐进式注意力调整 - 平滑的概率变化，避免跳变
3. 指数衰减机制 - 注意力随时间自然衰减
4. 情绪系统 - 对不同用户维护情绪态度，影响回复倾向
5. 完全会话隔离 - 每个聊天独立的注意力和情绪数据

升级说明：
- v1.0.2: 初始注意力机制（单用户）
- Enhanced: 多用户追踪 + 情绪系统 + 渐进式调整

作者: Him666233
版本: v1.1.2

"""

import time

import asyncio

import math

import json

import os

from pathlib import Path

from typing import Dict, Any, Optional, List

from astrbot.api.all import *

from .cooldown_manager import CooldownManager

# 详细日志开关（与 main.py 同款方式：单独用 if 控制）
DEBUG_MODE: bool = False


class AttentionManager:
    """

    增强版注意力机制管理器（支持持久化）

    主要功能：
    1. 多用户注意力图谱 - 同时追踪多个用户的注意力分数（0-1）
    2. 情绪态度系统 - 对每个用户维护情绪值（-1到1）
    3. 渐进式调整 - 注意力和情绪平滑变化
    4. 指数衰减 - 随时间自然衰减，不突然清零
    5. 会话完全隔离 - 每个chat_key独立数据
    6. 持久化存储 - 数据保存到 data/plugin_data/chat_plus/attention_data.json

    扩展接口：
    - update_emotion() - 手动更新用户情绪
    - get_user_profile() - 获取用户完整档案
    - register_interaction() - 记录自定义交互事件

    """

    # 多用户注意力图谱

    # 格式: {

    #   "chat_key": {

    #     "user_123": {

    #       "attention_score": 0.8,  # 注意力分数 0-1

    #       "emotion": 0.5,          # 情绪值 -1(负面)到1(正面)

    #       "last_interaction": timestamp,

    #       "interaction_count": 5,

    #       "last_message_preview": "最后一条消息的预览"

    #     }

    #   }

    # }

    _attention_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    _lock = asyncio.Lock()  # 异步锁

    _storage_path: Optional[Path] = None  # 持久化存储路径

    _initialized: bool = False

    # 🌊 群聊活跃度图谱（用于注意力溢出机制）

    # 格式: {

    #   "chat_key": {

    #     "activity_score": 0.8,        # 当前活跃度（基于最高注意力用户）

    #     "last_bot_reply": timestamp,  # AI最后回复时间

    #     "peak_user_id": "user_123",   # 最高注意力用户ID

    #     "peak_user_name": "用户A",    # 最高注意力用户昵称

    #     "peak_attention": 0.8         # 最高注意力分数

    #   }

    # }

    _conversation_activity_map: Dict[str, Dict[str, Any]] = {}

    # 配置参数（可通过配置文件调整）

    MAX_TRACKED_USERS = 10  # 每个聊天最多追踪的用户数

    ATTENTION_DECAY_HALFLIFE = 300  # 注意力半衰期（秒）

    EMOTION_DECAY_HALFLIFE = 600  # 情绪半衰期（秒）

    MIN_ATTENTION_SCORE = 0.0  # 最小注意力分数

    MAX_ATTENTION_SCORE = 1.0  # 最大注意力分数

    AUTO_SAVE_INTERVAL = 60  # 自动保存间隔（秒）

    _last_save_time: float = 0  # 上次保存时间

    # 情感检测配置（v1.1.2新增）

    ENABLE_EMOTION_DETECTION = False  # 是否启用情感检测

    EMOTION_KEYWORDS: Dict[str, List[str]] = {}  # 情感关键词

    ENABLE_NEGATION = True  # 是否启用否定词检测

    NEGATION_WORDS: List[str] = []  # 否定词列表

    NEGATION_CHECK_RANGE = 5  # 否定词检查范围

    POSITIVE_EMOTION_BOOST = 0.1  # 正面消息额外提升

    NEGATIVE_EMOTION_DECREASE = 0.15  # 负面消息降低幅度

    # 🌊 注意力溢出机制配置（v1.1.3新增）

    ENABLE_SPILLOVER = True  # 是否启用注意力溢出

    SPILLOVER_RATIO = 0.35  # 溢出比例（相对于最高注意力用户）

    SPILLOVER_DECAY_HALFLIFE = 90  # 溢出效果衰减半衰期（秒）

    SPILLOVER_MIN_TRIGGER = 0.4  # 触发溢出的最低注意力阈值

    # 🔄 对话疲劳机制配置（v1.2.1新增）
    ENABLE_CONVERSATION_FATIGUE = False  # 是否启用对话疲劳检测
    CONSECUTIVE_REPLY_RESET_THRESHOLD = 300  # 连续对话重置阈值（秒），超过此时间未互动则重置连续轮次
    FATIGUE_THRESHOLD_LIGHT = 3  # 轻度疲劳阈值（连续回复次数）
    FATIGUE_THRESHOLD_MEDIUM = 5  # 中度疲劳阈值
    FATIGUE_THRESHOLD_HEAVY = 8  # 重度疲劳阈值
    FATIGUE_PROBABILITY_DECREASE_LIGHT = 0.1  # 轻度疲劳概率降低幅度
    FATIGUE_PROBABILITY_DECREASE_MEDIUM = 0.2  # 中度疲劳概率降低幅度
    FATIGUE_PROBABILITY_DECREASE_HEAVY = 0.35  # 重度疲劳概率降低幅度

    # 🔒 疲劳注意力封锁机制（v1.2.3新增，临时存储，不持久化）
    # 格式: {
    #   "chat_key": {
    #     "user_123": {
    #       "blocked_at": timestamp,      # 封锁开始时间
    #       "fatigue_level": "medium",    # 触发封锁时的疲劳等级
    #     }
    #   }
    # }
    _fatigue_attention_block: Dict[str, Dict[str, Dict[str, Any]]] = {}

    @staticmethod
    def initialize(
        data_dir: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """

        初始化注意力管理器（设置存储路径并加载数据）



        Args:

            data_dir: 数据目录路径（由 StarTools.get_data_dir() 提供）

            config: 插件配置字典（用于加载情感检测配置）

        """

        if AttentionManager._initialized:
            return

        if not data_dir:
            # 如果未提供data_dir，禁用持久化功能

            logger.error(
                "[注意力机制] 未提供data_dir参数，持久化功能将被禁用。"
                "请确保通过 StarTools.get_data_dir() 获取数据目录。"
            )

            AttentionManager._storage_path = None

            AttentionManager._initialized = True

            return

        # 设置存储路径

        AttentionManager._storage_path = Path(data_dir) / "attention_data.json"

        # 加载已有数据

        AttentionManager._load_from_disk()

        # 加载情感检测和溢出配置

        if config:
            AttentionManager._load_emotion_detection_config(config)

            AttentionManager._load_spillover_config(config)

            AttentionManager._load_fatigue_config(config)

        AttentionManager._initialized = True

        if DEBUG_MODE:
            logger.info(
                f"[注意力机制] 持久化存储已初始化: {AttentionManager._storage_path}"
            )

            if AttentionManager.ENABLE_EMOTION_DETECTION:
                logger.info(
                    f"[注意力机制] 情感检测已启用: 正面关键词{len(AttentionManager.EMOTION_KEYWORDS.get('正面', []))}个, "
                    f"负面关键词{len(AttentionManager.EMOTION_KEYWORDS.get('负面', []))}个"
                )

            if AttentionManager.ENABLE_SPILLOVER:
                logger.info(
                    f"[注意力机制] 🌊 溢出机制已启用: 比例={AttentionManager.SPILLOVER_RATIO:.0%}, "
                    f"半衰期={AttentionManager.SPILLOVER_DECAY_HALFLIFE}秒, "
                    f"触发阈值={AttentionManager.SPILLOVER_MIN_TRIGGER}"
                )

            if AttentionManager.ENABLE_CONVERSATION_FATIGUE:
                logger.info(
                    f"[注意力机制] 🔄 对话疲劳机制已启用: "
                    f"轻度阈值={AttentionManager.FATIGUE_THRESHOLD_LIGHT}轮, "
                    f"中度阈值={AttentionManager.FATIGUE_THRESHOLD_MEDIUM}轮, "
                    f"重度阈值={AttentionManager.FATIGUE_THRESHOLD_HEAVY}轮"
                )

    @staticmethod
    def _load_emotion_detection_config(config: Dict[str, Any]) -> None:
        """

        加载情感检测配置



        说明：配置由 main.py 统一提取后传入，此处直接使用传入的值，

        不再提供默认值（避免 AstrBot 平台多次读取配置的问题）



        Args:

            config: 插件配置字典（由 main.py 统一提取）

        """

        # 是否启用情感检测

        AttentionManager.ENABLE_EMOTION_DETECTION = config[
            "enable_attention_emotion_detection"
        ]

        if not AttentionManager.ENABLE_EMOTION_DETECTION:
            return

        # 加载情感关键词

        emotion_keywords_raw = config["attention_emotion_keywords"]

        if isinstance(emotion_keywords_raw, str) and emotion_keywords_raw.strip():
            try:
                AttentionManager.EMOTION_KEYWORDS = json.loads(emotion_keywords_raw)

            except json.JSONDecodeError as e:
                logger.warning(
                    f"[注意力机制-情感检测] 关键词JSON解析失败: {e}，使用默认配置"
                )

                AttentionManager.EMOTION_KEYWORDS = {
                    "正面": ["谢谢", "感谢", "太好了", "棒", "赞"],
                    "负面": ["傻", "蠢", "笨", "垃圾", "讨厌"],
                }

        elif isinstance(emotion_keywords_raw, dict):
            AttentionManager.EMOTION_KEYWORDS = emotion_keywords_raw

        else:
            AttentionManager.EMOTION_KEYWORDS = {
                "正面": ["谢谢", "感谢", "太好了", "棒", "赞"],
                "负面": ["傻", "蠢", "笨", "垃圾", "讨厌"],
            }

        # 否定词相关配置（直接使用传入的值）

        AttentionManager.ENABLE_NEGATION = config["attention_enable_negation"]

        AttentionManager.NEGATION_WORDS = config["attention_negation_words"]

        AttentionManager.NEGATION_CHECK_RANGE = config["attention_negation_check_range"]

        # 情绪变化幅度（直接使用传入的值）

        AttentionManager.POSITIVE_EMOTION_BOOST = config[
            "attention_positive_emotion_boost"
        ]

        AttentionManager.NEGATIVE_EMOTION_DECREASE = config[
            "attention_negative_emotion_decrease"
        ]

    @staticmethod
    def _load_spillover_config(config: Dict[str, Any]) -> None:
        """

        加载注意力溢出机制配置



        说明：配置由 main.py 统一提取后传入，此处直接使用传入的值，

        不再提供默认值（避免 AstrBot 平台多次读取配置的问题）



        Args:

            config: 插件配置字典（由 main.py 统一提取）

        """

        # 是否启用溢出机制（直接使用传入的值）

        AttentionManager.ENABLE_SPILLOVER = config["enable_attention_spillover"]

        # 溢出比例

        AttentionManager.SPILLOVER_RATIO = config["attention_spillover_ratio"]

        # 溢出衰减半衰期

        AttentionManager.SPILLOVER_DECAY_HALFLIFE = config[
            "attention_spillover_decay_halflife"
        ]

        # 触发溢出的最低注意力阈值

        AttentionManager.SPILLOVER_MIN_TRIGGER = config[
            "attention_spillover_min_trigger"
        ]

    @staticmethod
    def _load_fatigue_config(config: Dict[str, Any]) -> None:
        """
        加载对话疲劳机制配置

        说明：配置由 main.py 统一提取并验证后传入，此处直接使用传入的值
        边界检查和逻辑验证已在 main.py 中完成

        Args:
            config: 插件配置字典（由 main.py 统一提取，已完成边界检查）
        """
        # 是否启用对话疲劳机制
        AttentionManager.ENABLE_CONVERSATION_FATIGUE = config.get(
            "enable_conversation_fatigue", False
        )

        # 连续对话重置阈值（秒）- 已在main.py中验证
        AttentionManager.CONSECUTIVE_REPLY_RESET_THRESHOLD = config.get(
            "fatigue_reset_threshold", 300
        )

        # 疲劳阈值 - 已在main.py中验证递增关系
        AttentionManager.FATIGUE_THRESHOLD_LIGHT = config.get(
            "fatigue_threshold_light", 3
        )
        AttentionManager.FATIGUE_THRESHOLD_MEDIUM = config.get(
            "fatigue_threshold_medium", 5
        )
        AttentionManager.FATIGUE_THRESHOLD_HEAVY = config.get(
            "fatigue_threshold_heavy", 8
        )

        # 疲劳概率降低幅度 - 已在main.py中验证范围和递增关系
        AttentionManager.FATIGUE_PROBABILITY_DECREASE_LIGHT = config.get(
            "fatigue_probability_decrease_light", 0.1
        )
        AttentionManager.FATIGUE_PROBABILITY_DECREASE_MEDIUM = config.get(
            "fatigue_probability_decrease_medium", 0.2
        )
        AttentionManager.FATIGUE_PROBABILITY_DECREASE_HEAVY = config.get(
            "fatigue_probability_decrease_heavy", 0.35
        )

    @staticmethod
    def _load_from_disk() -> None:
        """从磁盘加载注意力数据"""

        if (
            not AttentionManager._storage_path
            or not AttentionManager._storage_path.exists()
        ):
            if DEBUG_MODE:
                logger.info("[注意力机制] 无历史数据文件，从空白开始")

            return

        try:
            with open(AttentionManager._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

                AttentionManager._attention_map = data

                if DEBUG_MODE:
                    logger.info(f"[注意力机制] 已加载 {len(data)} 个会话的注意力数据")

        except Exception as e:
            logger.error(f"[注意力机制] 加载数据失败: {e}，将从空白开始")

            AttentionManager._attention_map = {}

    @staticmethod
    def _save_to_disk(force: bool = False) -> None:
        """

        保存注意力数据到磁盘



        Args:

            force: 是否强制保存（跳过时间检查）

        """

        if not AttentionManager._storage_path:
            return

        # 检查是否需要保存（避免频繁写磁盘）

        current_time = time.time()

        if (
            not force
            and (current_time - AttentionManager._last_save_time)
            < AttentionManager.AUTO_SAVE_INTERVAL
        ):
            return

        try:
            # 确保目录存在

            AttentionManager._storage_path.parent.mkdir(parents=True, exist_ok=True)

            # 保存数据

            with open(AttentionManager._storage_path, "w", encoding="utf-8") as f:
                json.dump(
                    AttentionManager._attention_map, f, ensure_ascii=False, indent=2
                )

            AttentionManager._last_save_time = current_time

            if DEBUG_MODE:
                logger.info(
                    f"[注意力机制] 数据已保存到磁盘 ({len(AttentionManager._attention_map)} 个会话)"
                )

        except Exception as e:
            logger.error(f"[注意力机制] 保存数据失败: {e}")

    @staticmethod
    async def _auto_save_if_needed() -> None:
        """自动保存（如果距离上次保存超过阈值）"""

        AttentionManager._save_to_disk(force=False)

    @staticmethod
    def get_chat_key(platform_name: str, is_private: bool, chat_id: str) -> str:
        """

        获取聊天的唯一标识（确保会话隔离）



        Args:

            platform_name: 平台名称（如aiocqhttp, gewechat等）

            is_private: 是否私聊

            chat_id: 聊天ID（群号或用户ID）



        Returns:

            唯一标识键

        """

        chat_type = "private" if is_private else "group"

        return f"{platform_name}_{chat_type}_{chat_id}"

    @staticmethod
    def _calculate_decay(elapsed_time: float, halflife: float) -> float:
        """

        计算指数衰减系数



        使用公式: decay = 0.5^(elapsed_time / halflife)



        Args:

            elapsed_time: 经过的时间（秒）

            halflife: 半衰期（秒）



        Returns:

            衰减系数（0-1）

        """

        if elapsed_time <= 0:
            return 1.0

        if halflife <= 0:
            return 1.0

        return math.pow(0.5, elapsed_time / halflife)

    @staticmethod
    async def _init_user_profile(user_id: str, user_name: str) -> Dict[str, Any]:
        """

        初始化用户档案



        Args:

            user_id: 用户ID

            user_name: 用户名字



        Returns:

            初始化的用户档案字典

        """

        return {
            "user_id": user_id,
            "user_name": user_name,
            "attention_score": 0.0,  # 初始注意力为0
            "emotion": 0.0,  # 初始情绪中性
            "last_interaction": time.time(),
            "interaction_count": 0,
            "last_message_preview": "",
            "consecutive_replies": 0,  # 🆕 连续对话轮次（AI连续回复该用户的次数）
            "last_reply_time": 0,  # 🆕 上次AI回复该用户的时间
        }

    @staticmethod
    async def _apply_attention_decay(
        profile: Dict[str, Any], current_time: float
    ) -> None:
        """

        应用注意力和情绪的时间衰减



        Args:

            profile: 用户档案

            current_time: 当前时间戳

        """

        elapsed = current_time - profile.get("last_interaction", current_time)

        # 注意力衰减

        attention_decay = AttentionManager._calculate_decay(
            elapsed, AttentionManager.ATTENTION_DECAY_HALFLIFE
        )

        profile["attention_score"] *= attention_decay

        # 情绪衰减（向0中性值）

        emotion_decay = AttentionManager._calculate_decay(
            elapsed, AttentionManager.EMOTION_DECAY_HALFLIFE
        )

        profile["emotion"] *= emotion_decay

    @staticmethod
    def _has_negation_before(text: str, keyword_pos: int) -> bool:
        """

        检查关键词前是否有否定词（照搬自MoodTracker）



        Args:

            text: 完整文本

            keyword_pos: 关键词在文本中的位置



        Returns:

            如果检测到否定词返回True

        """

        # 提取关键词前的上下文

        start_pos = max(0, keyword_pos - AttentionManager.NEGATION_CHECK_RANGE)

        context_before = text[start_pos:keyword_pos]

        # 检查是否包含否定词

        for neg_word in AttentionManager.NEGATION_WORDS:
            if neg_word in context_before:
                return True

        return False

    @staticmethod
    def _detect_emotion_from_message(message_text: str) -> Optional[str]:
        """

        从消息文本中检测情感（正面/负面/中性）



        Args:

            message_text: 要分析的消息文本



        Returns:

            "正面"、"负面" 或 None（中性）

        """

        if not AttentionManager.ENABLE_EMOTION_DETECTION:
            return None

        if not message_text:
            return None

        # 统计正面和负面关键词的得分

        emotion_scores = {"正面": 0, "负面": 0}

        for emotion_type, keywords in AttentionManager.EMOTION_KEYWORDS.items():
            if emotion_type not in ["正面", "负面"]:
                continue

            score = 0

            for keyword in keywords:
                # 查找所有该关键词的出现位置

                start = 0

                while True:
                    pos = message_text.find(keyword, start)

                    if pos == -1:
                        break

                    # 如果启用了否定词检测，检查前面是否有否定词

                    if (
                        AttentionManager.ENABLE_NEGATION
                        and AttentionManager._has_negation_before(message_text, pos)
                    ):
                        # 检测到否定词，跳过这个关键词

                        if DEBUG_MODE:
                            logger.info(
                                f"[注意力机制-情感检测] 检测到否定词，忽略关键词 '{keyword}' "
                                f"(位置: {pos})"
                            )

                    else:
                        # 没有否定词，正常计分

                        score += 1

                    start = pos + 1

            if score > 0:
                emotion_scores[emotion_type] = score

        # 如果没有检测到任何情感关键词，返回None（中性）

        if emotion_scores["正面"] == 0 and emotion_scores["负面"] == 0:
            return None

        # 返回得分最高的情感类型

        if emotion_scores["正面"] > emotion_scores["负面"]:
            if DEBUG_MODE:
                logger.info(
                    f"[注意力机制-情感检测] 检测到正面消息（正面:{emotion_scores['正面']}, 负面:{emotion_scores['负面']}）"
                )

            return "正面"

        elif emotion_scores["负面"] > emotion_scores["正面"]:
            if DEBUG_MODE:
                logger.info(
                    f"[注意力机制-情感检测] 检测到负面消息（正面:{emotion_scores['正面']}, 负面:{emotion_scores['负面']}）"
                )

            return "负面"

        else:
            # 得分相同，视为中性

            return None

    @staticmethod
    async def _cleanup_inactive_users(
        chat_users: Dict[str, Dict[str, Any]], current_time: float
    ) -> int:
        """

        清理长时间未互动且注意力极低的用户



        清理条件：

        1. 注意力分数 < 0.05 (几乎为0)

        2. 超过 30分钟 未互动



        Args:

            chat_users: 用户字典

            current_time: 当前时间戳



        Returns:

            清理的用户数量

        """

        INACTIVE_THRESHOLD = 1800  # 30分钟

        ATTENTION_THRESHOLD = 0.05  # 注意力阈值

        to_remove = []

        for user_id, profile in chat_users.items():
            elapsed = current_time - profile.get("last_interaction", current_time)

            attention = profile.get("attention_score", 0.0)

            # 满足清理条件：长时间未互动 且 注意力极低

            if elapsed > INACTIVE_THRESHOLD and attention < ATTENTION_THRESHOLD:
                to_remove.append(
                    (user_id, profile.get("user_name", "unknown"), attention, elapsed)
                )

        # 执行清理

        removed_count = 0

        for user_id, user_name, attention, elapsed in to_remove:
            del chat_users[user_id]

            removed_count += 1

            logger.info(
                f"[注意力机制-清理] 移除不活跃用户: {user_name}(ID:{user_id}), "
                f"注意力={attention:.3f}, 未互动{elapsed / 60:.1f}分钟"
            )

        return removed_count

    @staticmethod
    async def record_replied_user(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: str,
        user_name: str,
        message_preview: str = "",
        message_text: str = "",
        attention_boost_step: float = 0.4,
        attention_decrease_step: float = 0.1,
        emotion_boost_step: float = 0.1,
    ) -> None:
        """

        记录AI回复的目标用户（增强版）



        在AI发送回复后调用，更新用户的注意力分数和情绪



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 被回复的用户ID

            user_name: 被回复的用户名字

            message_preview: 消息预览（可选）

            message_text: 消息原文（用于情感检测，v1.1.2新增）

            attention_boost_step: 被回复用户注意力增加幅度（默认0.4）

            attention_decrease_step: 其他用户注意力减少幅度（默认0.1）

            emotion_boost_step: 被回复用户情绪增加幅度（默认0.1）

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        async with AttentionManager._lock:
            # 初始化chat_key

            if chat_key not in AttentionManager._attention_map:
                AttentionManager._attention_map[chat_key] = {}

            chat_users = AttentionManager._attention_map[chat_key]

            # 获取或创建用户档案

            if user_id not in chat_users:
                chat_users[user_id] = await AttentionManager._init_user_profile(
                    user_id, user_name
                )

            profile = chat_users[user_id]

            # 应用衰减（更新前先衰减）

            await AttentionManager._apply_attention_decay(profile, current_time)

            # 提升注意力（渐进式，使用配置的增加幅度）

            # 检查用户是否处于等待/冷却列表中 (Requirements 1.3, 2.3)
            # 如果用户在等待列表中，则本次不提升注意力
            skip_attention_increase = False
            skip_reason = ""
            
            try:
                # 注意：这里不能使用 await，因为已经在 _lock 内部
                # 只需要直接检查等待状态，避免潜在死锁
                if CooldownManager._initialized:
                    if chat_key in CooldownManager._cooldown_map:
                        if user_id in CooldownManager._cooldown_map[chat_key]:
                            skip_attention_increase = True
                            skip_reason = "冷却列表"
                            if DEBUG_MODE:
                                logger.info(
                                    f"[注意力-冷却] 用户 {user_name}(ID:{user_id}) 在等待列表中，跳过注意力提升"
                                )
            except ImportError:
                pass  # CooldownManager not available, proceed normally
            except Exception as e:
                logger.warning(f"[注意力-冷却] 检查冷却状态时发生异常: {e}")

            # 🔒 检查用户是否处于疲劳注意力封锁状态
            if not skip_attention_increase and AttentionManager.ENABLE_CONVERSATION_FATIGUE:
                if AttentionManager._is_fatigue_attention_blocked(chat_key, user_id):
                    skip_attention_increase = True
                    skip_reason = "疲劳封锁"
                    if DEBUG_MODE:
                        logger.info(
                            f"[疲劳封锁] 用户 {user_name}(ID:{user_id}) 处于疲劳封锁状态，跳过注意力提升"
                        )

            old_attention = profile["attention_score"]

            if not skip_attention_increase:
                profile["attention_score"] = min(
                    profile["attention_score"] + attention_boost_step,
                    AttentionManager.MAX_ATTENTION_SCORE,
                )

            else:
                # 用户在等待列表或疲劳封锁中，本次不提升注意力，但仍然记录交互
                logger.info(
                    f"[注意力-{skip_reason}] 用户 {user_name}(ID:{user_id}) 处于{skip_reason}状态，注意力保持不变: {old_attention:.2f}"
                )

            # 情感检测并调整情绪（v1.1.2新增）

            detected_emotion = AttentionManager._detect_emotion_from_message(
                message_text
            )

            old_emotion = profile["emotion"]

            if detected_emotion == "正面":
                # 正面消息：基础提升 + 额外奖励

                emotion_change = (
                    emotion_boost_step + AttentionManager.POSITIVE_EMOTION_BOOST
                )

                profile["emotion"] = min(profile["emotion"] + emotion_change, 1.0)

                logger.info(
                    f"[注意力机制-情感] 正面消息，情绪提升: {old_emotion:.2f} → {profile['emotion']:.2f} (+{emotion_change:.2f})"
                )

            elif detected_emotion == "负面":
                # 负面消息：降低情绪值

                profile["emotion"] = max(
                    profile["emotion"] - AttentionManager.NEGATIVE_EMOTION_DECREASE,
                    -1.0,
                )

                logger.info(
                    f"[注意力机制-情感] 负面消息，情绪降低: {old_emotion:.2f} → {profile['emotion']:.2f} (-{AttentionManager.NEGATIVE_EMOTION_DECREASE:.2f})"
                )

            else:
                # 中性消息或未启用检测：正常提升（默认行为）

                profile["emotion"] = min(profile["emotion"] + emotion_boost_step, 1.0)

            # 更新其他信息

            profile["last_interaction"] = current_time

            profile["interaction_count"] = profile.get("interaction_count", 0) + 1

            profile["user_name"] = user_name  # 更新名字（可能改了昵称）

            if message_preview:
                profile["last_message_preview"] = message_preview[:50]

            # 🆕 更新连续对话轮次（用于对话疲劳检测）
            last_reply_time = profile.get("last_reply_time", 0)
            consecutive_reset_threshold = AttentionManager.CONSECUTIVE_REPLY_RESET_THRESHOLD
            
            if current_time - last_reply_time < consecutive_reset_threshold:
                # 在阈值时间内再次回复，累加连续轮次
                profile["consecutive_replies"] = profile.get("consecutive_replies", 0) + 1
            else:
                # 超过阈值时间，重置连续轮次为1（当前这次回复）
                profile["consecutive_replies"] = 1
                # 🔒 超过阈值时间，同时解除疲劳封锁（如果有）
                if AttentionManager.ENABLE_CONVERSATION_FATIGUE:
                    await AttentionManager._release_fatigue_attention_block(chat_key, user_id)
            
            profile["last_reply_time"] = current_time
            
            # 🔒 检查是否进入疲劳状态，如果是则添加封锁
            if AttentionManager.ENABLE_CONVERSATION_FATIGUE:
                consecutive = profile["consecutive_replies"]
                fatigue_level = "none"
                if consecutive >= AttentionManager.FATIGUE_THRESHOLD_HEAVY:
                    fatigue_level = "heavy"
                elif consecutive >= AttentionManager.FATIGUE_THRESHOLD_MEDIUM:
                    fatigue_level = "medium"
                elif consecutive >= AttentionManager.FATIGUE_THRESHOLD_LIGHT:
                    fatigue_level = "light"
                
                # 只有进入疲劳状态（非none）才添加封锁
                if fatigue_level != "none":
                    # 检查是否已经被封锁，避免重复添加
                    if not AttentionManager._is_fatigue_attention_blocked(chat_key, user_id):
                        await AttentionManager._add_fatigue_attention_block(chat_key, user_id, fatigue_level)
            
            if DEBUG_MODE:
                logger.info(
                    f"[对话疲劳] 用户 {user_name}(ID:{user_id}) 连续对话轮次: {profile['consecutive_replies']}"
                )

            # 降低其他用户的注意力（使用配置的减少幅度）
            for other_user_id, other_profile in chat_users.items():
                if other_user_id != user_id:
                    await AttentionManager._apply_attention_decay(
                        other_profile, current_time
                    )

                    other_profile["attention_score"] = max(
                        other_profile["attention_score"] - attention_decrease_step,
                        AttentionManager.MIN_ATTENTION_SCORE,
                    )

            # 智能清理：移除注意力极低且长时间未互动的用户

            await AttentionManager._cleanup_inactive_users(chat_users, current_time)

            # 如果还是超过限制，按优先级移除

            if len(chat_users) > AttentionManager.MAX_TRACKED_USERS:
                # 综合排序：注意力分数和最后互动时间

                # 注意力越低、时间越久远 → 优先级越低

                sorted_users = sorted(
                    chat_users.items(),
                    key=lambda x: (
                        x[1]["attention_score"] + 0.0001,  # 避免除零
                        x[1]["last_interaction"],
                    ),
                )

                # 移除最低优先级的用户

                to_remove_count = len(chat_users) - AttentionManager.MAX_TRACKED_USERS

                for i in range(to_remove_count):
                    removed_user_id = sorted_users[i][0]

                    removed_name = chat_users[removed_user_id].get(
                        "user_name", "unknown"
                    )

                    del chat_users[removed_user_id]

                    if DEBUG_MODE:
                        logger.info(
                            f"[注意力机制] 移除低优先级用户: {removed_name}(ID:{removed_user_id}), "
                            f"注意力={sorted_users[i][1]['attention_score']:.3f}"
                        )

            logger.info(
                f"[注意力机制-增强] 会话 {chat_key} - 回复 {user_name}(ID:{user_id}), "
                f"注意力 {old_attention:.2f}→{profile['attention_score']:.2f}, "
                f"情绪 {profile['emotion']:.2f}, "
                f"互动次数 {profile['interaction_count']}"
            )

            # 🌊 更新群聊活跃度（用于注意力溢出机制）

            if AttentionManager.ENABLE_SPILLOVER:
                await AttentionManager._update_conversation_activity(
                    chat_key,
                    user_id,
                    user_name,
                    profile["attention_score"],
                    current_time,
                )

            # 自动保存数据（如果距离上次保存超过阈值）

            await AttentionManager._auto_save_if_needed()

    @staticmethod
    async def get_adjusted_probability(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        current_user_id: str,
        current_user_name: str,
        current_probability: float,
        attention_increased_probability: float,
        attention_decreased_probability: float,
        attention_duration: int,
        enabled: bool,
        poke_boost_reference: float = 0.0,
    ) -> float:
        """

        根据注意力机制和情绪系统调整概率（增强版）



        考虑因素：

        1. 用户的注意力分数（渐进式调整）

        2. 对该用户的情绪态度（正面提升，负面降低）

        3. 时间衰减（自然衰减，不突然清零）

        4. 多用户平衡（综合考虑多个用户）

        5. 戳一戳智能增值（根据情绪和注意力智能缩放）



        兼容性说明：

        - 保持与旧配置兼容（attention_increased/decreased_probability）

        - 但改为渐进式调整，而非直接替换



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            current_user_id: 当前消息发送者ID

            current_user_name: 当前消息发送者名字

            current_probability: 当前概率（未调整前）

            attention_increased_probability: （兼容参数）最大提升概率

            attention_decreased_probability: （兼容参数）最低降低概率

            attention_duration: （兼容参数）用于判断是否清理旧数据

            enabled: 是否启用注意力机制

            poke_boost_reference: 戳一戳概率增值参考值（0表示无戳一戳）



        Returns:

            调整后的概率值（保证在 [0, 1] 范围内）

        """

        # 如果未启用注意力机制，但有戳一戳增值，仍然应用增值

        if not enabled:
            if poke_boost_reference > 0:
                # 简化模式：无注意力机制时，使用固定的缩放因子

                # 假设中性情绪（0.5）和中等注意力（0.5）

                default_factor = 0.5

                poke_boost = poke_boost_reference * default_factor

                adjusted = current_probability + poke_boost

                adjusted = max(0.0, min(0.98, adjusted))

                if DEBUG_MODE:
                    logger.info(
                        f"[戳一戳增值-简化模式] 用户 {current_user_name}: "
                        f"概率 {current_probability:.2f} → {adjusted:.2f} "
                        f"(增值={poke_boost:.2f}, 参考值={poke_boost_reference:.2f})"
                    )

                return adjusted

            return max(0.0, min(1.0, current_probability))
        # === 输入参数边界检测 ===

        # 确保所有概率参数都在 [0, 1] 范围内

        current_probability = max(0.0, min(1.0, current_probability))

        attention_increased_probability = max(
            0.0, min(1.0, attention_increased_probability)
        )

        attention_decreased_probability = max(
            0.0, min(1.0, attention_decreased_probability)
        )

        # 确保逻辑关系正确：increased >= decreased

        if attention_increased_probability < attention_decreased_probability:
            logger.warning(
                f"[注意力机制-边界检测] 配置异常: increased({attention_increased_probability:.2f}) < "
                f"decreased({attention_decreased_probability:.2f})，已自动修正"
            )

            attention_increased_probability, attention_decreased_probability = (
                attention_decreased_probability,
                attention_increased_probability,
            )

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        # 🧊 冷却机制检查 (Requirements 1.3)
        # 如果用户在冷却列表中，跳过注意力增加，直接返回原始概率
        try:
            if CooldownManager._initialized:
                is_in_cooldown = await CooldownManager.is_in_cooldown(
                    chat_key, current_user_id
                )
                if is_in_cooldown:
                    # 用户在冷却列表中，不增加概率
                    logger.info(
                        f"[注意力-冷却] ❄️ 用户 {current_user_name}(ID:{current_user_id}) "
                        f"在冷却列表中，跳过注意力增加，使用原概率: {current_probability:.2f}"
                    )
                    return max(0.0, min(1.0, current_probability))
        except ImportError:
            pass  # CooldownManager not available, proceed normally
        except Exception as e:
            logger.warning(f"[注意力-冷却] 检查冷却状态时发生异常: {e}", exc_info=True)

        async with AttentionManager._lock:
            # 如果该聊天没有记录，检查是否有戳一戳增值

            if chat_key not in AttentionManager._attention_map:
                if poke_boost_reference > 0:
                    # 简化模式：无注意力档案时，使用固定的缩放因子

                    default_factor = 0.5

                    poke_boost = poke_boost_reference * default_factor

                    adjusted = current_probability + poke_boost

                    adjusted = max(0.0, min(0.98, adjusted))

                    logger.info(
                        f"[戳一戳增值-无档案] 会话 {chat_key} 用户 {current_user_name}: "
                        f"概率 {current_probability:.2f} → {adjusted:.2f} "
                        f"(增值={poke_boost:.2f}, 参考值={poke_boost_reference:.2f})"
                    )

                    return adjusted

                if DEBUG_MODE:
                    logger.info(
                        f"[注意力机制-增强] 会话 {chat_key} - 无历史记录，使用原概率"
                    )

                return current_probability

            chat_users = AttentionManager._attention_map[chat_key]

            # 如果当前用户没有档案，检查是否有溢出加成或戳一戳增值

            if current_user_id not in chat_users:
                adjusted = current_probability

                # 🌊 优先应用注意力溢出加成

                if AttentionManager.ENABLE_SPILLOVER:
                    spillover_boost = await AttentionManager._get_spillover_boost(
                        chat_key,
                        current_time,
                        attention_increased_probability,
                        current_probability,
                    )

                    if spillover_boost > 0:
                        adjusted = current_probability + spillover_boost

                        adjusted = max(0.0, min(0.95, adjusted))

                        logger.info(
                            f"[注意力溢出] 🌊 用户 {current_user_name} 无档案但获得溢出加成: "
                            f"概率 {current_probability:.2f} → {adjusted:.2f} (+{spillover_boost:.2f})"
                        )
                # 叠加戳一戳增值

                if poke_boost_reference > 0:
                    default_factor = 0.5

                    poke_boost = poke_boost_reference * default_factor

                    adjusted = adjusted + poke_boost

                    adjusted = max(0.0, min(0.98, adjusted))

                    logger.info(
                        f"[戳一戳增值-无档案] 用户 {current_user_name}: "
                        f"概率 → {adjusted:.2f} "
                        f"(戳一戳增值={poke_boost:.2f})"
                    )

                if abs(adjusted - current_probability) > 1e-9:
                    return adjusted

                if DEBUG_MODE:
                    logger.info(
                        f"[注意力机制-增强] 用户 {current_user_name} 无档案，使用原概率"
                    )

                return current_probability

            profile = chat_users[current_user_id]

            # 应用时间衰减

            await AttentionManager._apply_attention_decay(profile, current_time)

            # 清理长时间未互动的用户（超过 attention_duration * 3）

            cleanup_threshold = current_time - (attention_duration * 3)

            users_to_remove = [
                uid
                for uid, prof in chat_users.items()
                if prof.get("last_interaction", 0) < cleanup_threshold
            ]

            if users_to_remove:
                for uid in users_to_remove:
                    del chat_users[uid]

                    if DEBUG_MODE:
                        logger.info(f"[注意力机制-增强] 清理长时间未互动用户: {uid}")

                # 清理后保存

                await AttentionManager._auto_save_if_needed()

            # 获取注意力分数和情绪

            attention_score = profile.get("attention_score", 0.0)

            emotion = profile.get("emotion", 0.0)

            last_interaction = profile.get("last_interaction", current_time)

            elapsed = current_time - last_interaction

            # === 戳一戳智能增值处理 ===

            # 在标准注意力机制之外，额外应用戳一戳增值

            poke_boost_applied = 0.0

            if poke_boost_reference > 0:
                # 智能缩放因子（根据情绪和注意力）

                # emotion范围: -1(极负面)到+1(极正面)

                # attention_score范围: 0(无注意)到1(高注意)

                # 情绪因子：负面情绪大幅削弱增值，正面情绪允许更多增值

                # emotion=-1 -> emotion_factor=0.1 (仅10%增值)

                # emotion=0  -> emotion_factor=0.5 (50%增值)

                # emotion=+1 -> emotion_factor=1.0 (100%增值)

                emotion_factor = max(0.1, min(1.0, 0.5 + emotion * 0.5))

                # 注意力因子：注意力低时减少增值，注意力高时允许更多增值

                # attention=0 -> attention_factor=0.3 (仅30%增值)

                # attention=0.5 -> attention_factor=0.65 (65%增值)

                # attention=1 -> attention_factor=1.0 (100%增值)

                attention_factor = max(0.3, min(1.0, 0.3 + attention_score * 0.7))

                # 综合缩放因子（情绪权重70%，注意力权重30%）

                # 这样可以确保即使注意力高，情绪负面时仍会大幅减少增值

                combined_factor = emotion_factor * 0.7 + attention_factor * 0.3

                # 计算实际增值（参考值 * 综合因子）

                poke_boost_applied = poke_boost_reference * combined_factor

                if DEBUG_MODE or poke_boost_applied > 0.01:
                    logger.info(
                        f"[戳一戳智能增值] 用户 {current_user_name}: "
                        f"情绪={emotion:+.2f}→因子={emotion_factor:.2f}, "
                        f"注意力={attention_score:.2f}→因子={attention_factor:.2f}, "
                        f"综合因子={combined_factor:.2f}, "
                        f"参考值={poke_boost_reference:.2f}, "
                        f"实际增值={poke_boost_applied:.2f}"
                    )

            # === 渐进式概率调整算法 ===

            # 基础调整：根据注意力分数

            # attention_score 范围 0-1

            # - 0.0: 无注意力 → 使用原概率或略低

            # - 0.5: 中等注意力 → 适度提升

            # - 1.0: 高注意力 → 显著提升

            if attention_score > 0.1:  # 有一定注意力
                # 计算提升幅度（渐进式）

                # 使用配置的 attention_increased_probability 作为参考最大值

                max_boost = attention_increased_probability - current_probability

                actual_boost = max_boost * attention_score

                adjusted_probability = current_probability + actual_boost
                # 情绪修正（正面情绪进一步提升，负面情绪降低）

                # emotion 范围确保在 [-1, 1]，影响因子在 [0.7, 1.3]

                emotion = max(-1.0, min(1.0, emotion))  # 边界检测

                emotion_factor = 1.0 + (emotion * 0.3)  # emotion范围-1到1，影响±30%

                adjusted_probability *= emotion_factor
                # 应用戳一戳增值（在注意力和情绪调整之后）

                if poke_boost_applied > 0:
                    adjusted_probability += poke_boost_applied

                # === 严格的边界限制（三重保障）===

                # 1. 首先限制不超过 0.98（防止 100% 回复）

                adjusted_probability = min(adjusted_probability, 0.98)

                # 2. 然后限制不低于 attention_decreased_probability

                adjusted_probability = max(
                    adjusted_probability, attention_decreased_probability
                )

                # 3. 最终强制限制在 [0, 1] 范围（防止任何异常情况）

                adjusted_probability = max(0.0, min(1.0, adjusted_probability))

                poke_msg = (
                    f", 戳一戳增值={poke_boost_applied:.2f}"
                    if poke_boost_applied > 0
                    else ""
                )

                logger.info(
                    f"[注意力机制-增强] 🎯 {current_user_name}(ID:{current_user_id}), "
                    f"注意力={attention_score:.2f}, 情绪={emotion:+.2f}, "
                    f"概率 {current_probability:.2f} → {adjusted_probability:.2f} "
                    f"(互动次数:{profile.get('interaction_count', 0)}, "
                    f"距上次:{elapsed:.0f}秒{poke_msg})"
                )

                return adjusted_probability

            else:
                # 注意力很低（<0.1），略微降低概率

                adjusted_probability = max(
                    current_probability * 0.8,  # 降低20%
                    attention_decreased_probability,
                )

                # 即使注意力低，也应用戳一戳增值（但会被大幅削弱）

                if poke_boost_applied > 0:
                    adjusted_probability += poke_boost_applied

                # === 最终边界检测（确保在 [0, 1] 范围内）===

                adjusted_probability = max(0.0, min(1.0, adjusted_probability))

                poke_msg = (
                    f", 戳一戳增值={poke_boost_applied:.2f}"
                    if poke_boost_applied > 0
                    else ""
                )

                logger.info(
                    f"[注意力机制-增强] 👤 {current_user_name}(ID:{current_user_id}), "
                    f"注意力低({attention_score:.2f}), "
                    f"概率 {current_probability:.2f} → {adjusted_probability:.2f}{poke_msg}"
                )

                return adjusted_probability

    @staticmethod
    async def clear_attention(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """

        清除注意力状态



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 可选，指定用户ID则只清除该用户，否则清除整个会话

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        async with AttentionManager._lock:
            if chat_key in AttentionManager._attention_map:
                if user_id:
                    # 清除特定用户

                    if user_id in AttentionManager._attention_map[chat_key]:
                        del AttentionManager._attention_map[chat_key][user_id]

                        logger.info(
                            f"[注意力机制-增强] 会话 {chat_key} 用户 {user_id} 注意力已清除"
                        )

                else:
                    # 清除整个会话

                    del AttentionManager._attention_map[chat_key]

                    logger.info(
                        f"[注意力机制-增强] 会话 {chat_key} 所有注意力状态已清除"
                    )

    @staticmethod
    async def get_attention_info(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """

        获取注意力信息（用于调试和监控）



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 可选，指定用户ID则只返回该用户，否则返回所有用户



        Returns:

            注意力信息字典，如果没有记录则返回None

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                return None

            chat_users = AttentionManager._attention_map[chat_key]

            if user_id:
                # 返回特定用户

                return chat_users.get(user_id, None)

            else:
                # 返回所有用户（深拷贝）

                return {uid: profile.copy() for uid, profile in chat_users.items()}

    # ========== 扩展接口（供未来功能使用） ==========

    @staticmethod
    async def update_emotion(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: str,
        emotion_delta: float,
        user_name: str = "",
    ) -> None:
        """

        手动更新用户情绪值（扩展接口）



        可用于根据消息内容分析情绪，或手动调整情绪



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 用户ID

            emotion_delta: 情绪变化量（-1到1）

            user_name: 用户名（可选）

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                AttentionManager._attention_map[chat_key] = {}

            chat_users = AttentionManager._attention_map[chat_key]

            if user_id not in chat_users:
                chat_users[user_id] = await AttentionManager._init_user_profile(
                    user_id, user_name
                )

            profile = chat_users[user_id]

            # 应用衰减

            await AttentionManager._apply_attention_decay(profile, current_time)

            # 更新情绪

            old_emotion = profile["emotion"]

            profile["emotion"] = max(-1.0, min(1.0, profile["emotion"] + emotion_delta))

            logger.info(
                f"[注意力机制-扩展] 更新用户 {user_id} 情绪: "
                f"{old_emotion:.2f} → {profile['emotion']:.2f} (Δ{emotion_delta:+.2f})"
            )

    @staticmethod
    async def get_user_profile(
        platform_name: str, is_private: bool, chat_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """

        获取用户完整档案（扩展接口）



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 用户ID



        Returns:

            用户档案字典，不存在返回None

        """

        return await AttentionManager.get_attention_info(
            platform_name, is_private, chat_id, user_id
        )

    @staticmethod
    async def register_interaction(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: str,
        user_name: str,
        attention_delta: float = 0.0,
        emotion_delta: float = 0.0,
        message_preview: str = "",
    ) -> None:
        """

        记录自定义交互事件（扩展接口）



        可用于记录非回复类型的交互（如点赞、转发等）



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 用户ID

            user_name: 用户名

            attention_delta: 注意力变化量

            emotion_delta: 情绪变化量

            message_preview: 消息预览

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                AttentionManager._attention_map[chat_key] = {}

            chat_users = AttentionManager._attention_map[chat_key]

            if user_id not in chat_users:
                chat_users[user_id] = await AttentionManager._init_user_profile(
                    user_id, user_name
                )

            profile = chat_users[user_id]

            # 应用衰减

            await AttentionManager._apply_attention_decay(profile, current_time)

            # 更新注意力

            if abs(attention_delta) > 1e-9:
                profile["attention_score"] = max(
                    AttentionManager.MIN_ATTENTION_SCORE,
                    min(
                        AttentionManager.MAX_ATTENTION_SCORE,
                        profile["attention_score"] + attention_delta,
                    ),
                )

            # 更新情绪

            if abs(emotion_delta) > 1e-9:
                profile["emotion"] = max(
                    -1.0, min(1.0, profile["emotion"] + emotion_delta)
                )

            # 更新其他信息

            profile["last_interaction"] = current_time

            if message_preview:
                profile["last_message_preview"] = message_preview[:50]

            logger.info(
                f"[注意力机制-扩展] 记录交互: {user_name}(ID:{user_id}), "
                f"注意力Δ{attention_delta:+.2f}, 情绪Δ{emotion_delta:+.2f}"
            )

    @staticmethod
    async def get_top_attention_users(
        platform_name: str, is_private: bool, chat_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """

        获取注意力最高的用户列表（扩展接口）



        可用于分析当前对话焦点



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            limit: 返回数量限制



        Returns:

            用户档案列表，按注意力分数降序排序

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                return []

            chat_users = AttentionManager._attention_map[chat_key]

            # 应用衰减并排序

            user_list = []

            for user_id, profile in chat_users.items():
                await AttentionManager._apply_attention_decay(profile, current_time)

                user_list.append(profile.copy())

            # 按注意力分数降序排序

            user_list.sort(key=lambda x: x.get("attention_score", 0.0), reverse=True)

            return user_list[:limit]

    @staticmethod
    async def should_skip_attention_increase(
        chat_key: str,
        user_id: str,
    ) -> bool:
        """

        判断是否应跳过注意力增加：当用户处于等待/冷却列表时，不提升注意力。



        这是等待/冷却机制的一部分，用于避免 AI 过度回复正在排队等待的用户。



        Args:

            chat_key: 会话唯一标识

            user_id: 用户ID



        Returns:

            True 表示应跳过注意力增加（用户在等待列表中），否则 False



        Requirements: 1.3

        """

        # Check if user is in cooldown list

        is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)

        if is_in_cooldown and DEBUG_MODE:
            logger.info(f"[注意力-冷却] 用户 {user_id} 在等待列表中，跳过注意力提升")

        return is_in_cooldown

    @staticmethod
    async def decrease_attention_on_no_reply(
        platform_name: str,
        is_private: bool,
        chat_id: str,
        user_id: str,
        user_name: str,
        attention_decrease_step: float = 0.15,
        min_attention_threshold: float = 0.3,
    ) -> None:
        """

        当AI读空气判断不回复时降低对该用户的注意力



        功能说明：

        - 如果用户频繁发消息但AI判断都不应回复，说明用户在跟别人聊天

        - 此时应该降低对该用户的注意力，避免AI过度关注

        - 只有当前注意力高于阈值时才进行衰减，避免过度惩罚



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID

            user_id: 用户ID

            user_name: 用户名字

            attention_decrease_step: 注意力减少幅度（默认0.15）

            min_attention_threshold: 最小注意力阈值，低于此值不再衰减（默认0.3）

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        old_attention = None  # 用于冷却机制检查

        async with AttentionManager._lock:
            # 初始化chat_key

            if chat_key not in AttentionManager._attention_map:
                if DEBUG_MODE:
                    logger.info(f"[注意力衰减] 会话 {chat_key} 无注意力记录，跳过衰减")

                return

            chat_users = AttentionManager._attention_map[chat_key]

            # 检查用户是否存在

            if user_id not in chat_users:
                if DEBUG_MODE:
                    logger.info(
                        f"[注意力衰减] 用户 {user_name}(ID:{user_id}) 无注意力记录，跳过衰减"
                    )

                return

            profile = chat_users[user_id]

            # 应用时间衰减（先应用自然衰减）

            await AttentionManager._apply_attention_decay(profile, current_time)

            # 获取当前注意力分数

            current_attention = profile.get("attention_score", 0.0)

            # 只有注意力高于阈值时才进行额外衰减

            if current_attention < min_attention_threshold:
                if DEBUG_MODE:
                    logger.info(
                        f"[注意力衰减] {user_name}(ID:{user_id}) 注意力已较低 "
                        f"({current_attention:.2f} < {min_attention_threshold}), 跳过衰减"
                    )

                return

            # 执行注意力衰减

            old_attention = current_attention

            new_attention = max(
                current_attention - attention_decrease_step,
                AttentionManager.MIN_ATTENTION_SCORE,
            )

            profile["attention_score"] = new_attention

            # 更新最后交互时间（记录这次衰减操作）

            profile["last_interaction"] = current_time

            logger.info(
                f"[注意力衰减] 🔽 {user_name}(ID:{user_id}) AI判断不回复，注意力下降: "
                f"{old_attention:.2f} → {new_attention:.2f} (-{attention_decrease_step:.2f}), "
                f"互动次数: {profile.get('interaction_count', 0)}"
            )

            # 自动保存数据

            await AttentionManager._auto_save_if_needed()

        # Trigger cooldown mechanism (Requirements 1.1, 1.2)
        # After decreasing attention, if attention is still above cooldown threshold, add user to cooldown list
        # Note: This is outside the lock to avoid potential deadlock with CooldownManager's lock
        if old_attention is None:
            return  # 没有执行衰减操作，跳过冷却触发

        try:
            # Only trigger if CooldownManager is initialized (cooldown feature enabled)
            if not CooldownManager._initialized:
                logger.info(
                    f"[注意力冷却] ⚠️ CooldownManager未初始化，跳过冷却触发 "
                    f"(用户: {user_name}, 注意力: {old_attention:.2f})"
                )
                return

            # Check if cooldown should be triggered (attention above cooldown threshold)
            threshold = CooldownManager.COOLDOWN_TRIGGER_THRESHOLD
            logger.info(
                f"[注意力冷却] 检查冷却触发: {user_name}(ID:{user_id}), "
                f"注意力={old_attention:.2f}, 阈值={threshold}"
            )

            if old_attention > threshold:
                # Add user to cooldown list
                added = await CooldownManager.add_to_cooldown(
                    chat_key, user_id, user_name, reason="decision_ai_no_reply"
                )
                if added:
                    logger.info(
                        f"[注意力冷却] ❄️ {user_name}(ID:{user_id}) 已加入冷却列表, "
                        f"原注意力: {old_attention:.2f}, 阈值: {threshold}"
                    )
                else:
                    logger.info(
                        f"[注意力冷却] {user_name}(ID:{user_id}) 已在冷却列表中，跳过添加"
                    )
            else:
                logger.info(
                    f"[注意力冷却] {user_name}(ID:{user_id}) 注意力 {old_attention:.2f} "
                    f"未超过阈值 {threshold}，不触发冷却"
                )
        except ImportError as e:
            logger.warning(f"[注意力冷却] CooldownManager导入失败: {e}")
        except Exception as e:
            logger.warning(f"[注意力冷却] 触发冷却时发生异常: {e}", exc_info=True)

    # ========== 🌊 注意力溢出机制相关方法 ==========

    @staticmethod
    async def _update_conversation_activity(
        chat_key: str,
        user_id: str,
        user_name: str,
        attention_score: float,
        current_time: float,
    ) -> None:
        """

        更新群聊活跃度（在AI回复时调用）



        核心理念：当AI与某用户热烈对话时，会产生一种“对话活跃氛围”。

        这种氛围会溢出到群里其他用户，让AI也能注意到他们的插话。



        Args:

            chat_key: 聊天唯一标识

            user_id: 被回复的用户ID

            user_name: 被回复的用户名字

            attention_score: 被回复用户当前的注意力分数

            current_time: 当前时间戳

        """

        # 注意：调用此方法时已经在 _lock 锁内，不需要再次加锁

        # 只有当注意力超过触发阈值时才更新活跃度

        if attention_score < AttentionManager.SPILLOVER_MIN_TRIGGER:
            if DEBUG_MODE:
                logger.info(
                    f"[注意力溢出] 用户 {user_name} 注意力 {attention_score:.2f} "
                    f"< 阈值 {AttentionManager.SPILLOVER_MIN_TRIGGER}，不更新活跃度"
                )

            return

        # 更新或创建活跃度记录

        if chat_key not in AttentionManager._conversation_activity_map:
            AttentionManager._conversation_activity_map[chat_key] = {}

        activity = AttentionManager._conversation_activity_map[chat_key]

        old_score = activity.get("activity_score", 0.0)

        # 更新活跃度（取当前被回复用户的注意力分数）

        activity["activity_score"] = attention_score

        activity["last_bot_reply"] = current_time

        activity["peak_user_id"] = user_id

        activity["peak_user_name"] = user_name

        activity["peak_attention"] = attention_score

        logger.info(
            f"[注意力溢出] 🌊 更新群聊活跃度: {chat_key}, "
            f"活跃度 {old_score:.2f} → {attention_score:.2f}, "
            f"焦点用户: {user_name}"
        )

    @staticmethod
    async def _get_spillover_boost(
        chat_key: str,
        current_time: float,
        attention_increased_probability: float,
        current_probability: float,
    ) -> float:
        """

        计算注意力溢出加成（为无档案或低注意力用户提供概率提升）



        工作原理：

        1. 获取群聊当前活跃度

        2. 应用时间衰减（活跃度随时间减弱）

        3. 根据溢出比例计算加成值

        4. 返回加成值（可叠加到用户的基础概率上）



        场景示例：

        - 用户A和AI正在对话（A的注意力=0.8）

        - 用户B突然插话（B没有注意力档案，初始概率=0.1）

        - 溢出加成 = 0.8 × 0.35 × (0.9 - 0.1) = 0.224

        - B的概率提升为 0.1 + 0.224 = 0.324，更可能触发回复



        Args:

            chat_key: 聊天唯一标识

            current_time: 当前时间戳

            attention_increased_probability: 最大概率参考值

            current_probability: 用户当前基础概率



        Returns:

            溢出加成值（0表示无加成）

        """

        # 注意：调用此方法时已经在 _lock 锁内，不需要再次加锁

        # 检查是否有活跃度记录

        if chat_key not in AttentionManager._conversation_activity_map:
            return 0.0

        activity = AttentionManager._conversation_activity_map[chat_key]

        last_reply = activity.get("last_bot_reply", 0)

        base_activity = activity.get("activity_score", 0.0)

        # 检查活跃度是否超过触发阈值

        if base_activity < AttentionManager.SPILLOVER_MIN_TRIGGER:
            return 0.0

        # 计算时间衰减

        elapsed = current_time - last_reply

        if elapsed < 0:
            elapsed = 0

        # 使用指数衰减

        decay = AttentionManager._calculate_decay(
            elapsed, AttentionManager.SPILLOVER_DECAY_HALFLIFE
        )

        decayed_activity = base_activity * decay

        # 如果衰减后活跃度过低，不提供加成

        if decayed_activity < AttentionManager.SPILLOVER_MIN_TRIGGER * 0.5:
            if DEBUG_MODE:
                logger.info(
                    f"[注意力溢出] 活跃度已衰减过低: {base_activity:.2f} → {decayed_activity:.2f}，无加成"
                )

            return 0.0

        # 计算溢出加成

        # 公式: 溢出加成 = 衰减后活跃度 × 溢出比例 × (最大概率参考值 - 当前概率)

        probability_room = max(0, attention_increased_probability - current_probability)

        spillover_boost = (
            decayed_activity * AttentionManager.SPILLOVER_RATIO * probability_room
        )

        if DEBUG_MODE:
            peak_user = activity.get("peak_user_name", "未知")

            logger.info(
                f"[注意力溢出] 计算加成: 基础活跃度={base_activity:.2f}, "
                f"衰减系数={decay:.2f}, 衰减后活跃度={decayed_activity:.2f}, "
                f"溢出比例={AttentionManager.SPILLOVER_RATIO}, "
                f"概率空间={probability_room:.2f}, 加成={spillover_boost:.3f}, "
                f"焦点用户={peak_user}"
            )

        return spillover_boost

    @staticmethod
    async def get_conversation_activity_info(
        platform_name: str, is_private: bool, chat_id: str
    ) -> Optional[Dict[str, Any]]:
        """

        获取群聊活跃度信息（用于调试和监控）



        Args:

            platform_name: 平台名称

            is_private: 是否私聊

            chat_id: 聊天ID



        Returns:

            活跃度信息字典，如果没有记录则返回None

        """

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        current_time = time.time()

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._conversation_activity_map:
                return None

            activity = AttentionManager._conversation_activity_map[chat_key].copy()

            # 计算当前衰减后的活跃度

            last_reply = activity.get("last_bot_reply", 0)

            elapsed = current_time - last_reply

            decay = AttentionManager._calculate_decay(
                elapsed, AttentionManager.SPILLOVER_DECAY_HALFLIFE
            )

            activity["decayed_activity_score"] = (
                activity.get("activity_score", 0) * decay
            )

            activity["elapsed_seconds"] = elapsed

            activity["decay_factor"] = decay

            return activity


    @staticmethod
    async def get_conversation_fatigue_info(
        platform_name: str, is_private: bool, chat_id: str, user_id: str
    ) -> Dict[str, Any]:
        """
        获取用户的对话疲劳信息

        Args:
            platform_name: 平台名称
            is_private: 是否私聊
            chat_id: 聊天ID
            user_id: 用户ID

        Returns:
            对话疲劳信息字典，包含：
            - consecutive_replies: 连续对话轮次
            - fatigue_level: 疲劳等级 (none/light/medium/heavy)
            - probability_decrease: 建议的概率降低幅度
            - enabled: 是否启用对话疲劳机制
        """
        result = {
            "consecutive_replies": 0,
            "fatigue_level": "none",
            "probability_decrease": 0.0,
            "enabled": AttentionManager.ENABLE_CONVERSATION_FATIGUE,
        }

        if not AttentionManager.ENABLE_CONVERSATION_FATIGUE:
            return result

        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                return result

            chat_users = AttentionManager._attention_map[chat_key]

            if user_id not in chat_users:
                return result

            profile = chat_users[user_id]
            consecutive = profile.get("consecutive_replies", 0)
            result["consecutive_replies"] = consecutive

            # 判断疲劳等级
            if consecutive >= AttentionManager.FATIGUE_THRESHOLD_HEAVY:
                result["fatigue_level"] = "heavy"
                result["probability_decrease"] = AttentionManager.FATIGUE_PROBABILITY_DECREASE_HEAVY
            elif consecutive >= AttentionManager.FATIGUE_THRESHOLD_MEDIUM:
                result["fatigue_level"] = "medium"
                result["probability_decrease"] = AttentionManager.FATIGUE_PROBABILITY_DECREASE_MEDIUM
            elif consecutive >= AttentionManager.FATIGUE_THRESHOLD_LIGHT:
                result["fatigue_level"] = "light"
                result["probability_decrease"] = AttentionManager.FATIGUE_PROBABILITY_DECREASE_LIGHT

            return result

    @staticmethod
    async def reset_consecutive_replies(
        platform_name: str, is_private: bool, chat_id: str, user_id: str
    ) -> bool:
        """
        重置用户的连续对话轮次（当用户主动@或使用关键词触发时调用）
        
        同时重置 last_reply_time，让重置阈值的倒计时从头开始

        Args:
            platform_name: 平台名称
            is_private: 是否私聊
            chat_id: 聊天ID
            user_id: 用户ID

        Returns:
            是否成功重置
        """
        chat_key = AttentionManager.get_chat_key(platform_name, is_private, chat_id)

        async with AttentionManager._lock:
            if chat_key not in AttentionManager._attention_map:
                return False

            chat_users = AttentionManager._attention_map[chat_key]

            if user_id not in chat_users:
                return False

            profile = chat_users[user_id]
            old_consecutive = profile.get("consecutive_replies", 0)
            profile["consecutive_replies"] = 0
            # 同时重置 last_reply_time，让倒计时从头开始
            # 这样后续的 record_replied_user 会把 consecutive_replies 设为 1
            profile["last_reply_time"] = 0

            if DEBUG_MODE and old_consecutive > 0:
                user_name = profile.get("user_name", "未知")
                logger.info(
                    f"[对话疲劳] 重置用户 {user_name}(ID:{user_id}) 的连续对话轮次: {old_consecutive} → 0，"
                    f"同时重置倒计时"
                )

            # 🔒 同时解除疲劳注意力封锁
            await AttentionManager._release_fatigue_attention_block(chat_key, user_id)

            return True

    # ========== 🔒 疲劳注意力封锁机制（v1.2.3新增） ==========

    @staticmethod
    async def _add_fatigue_attention_block(
        chat_key: str, user_id: str, fatigue_level: str
    ) -> bool:
        """
        将用户添加到疲劳注意力封锁列表（内部方法，需在_lock内调用或单独加锁）
        
        当用户进入疲劳状态时调用，封锁其注意力增长
        
        Args:
            chat_key: 会话标识
            user_id: 用户ID
            fatigue_level: 疲劳等级
            
        Returns:
            是否成功添加
        """
        # 检查用户是否在注意力列表中
        if chat_key not in AttentionManager._attention_map:
            return False
        if user_id not in AttentionManager._attention_map[chat_key]:
            return False
        
        # 初始化会话的封锁列表
        if chat_key not in AttentionManager._fatigue_attention_block:
            AttentionManager._fatigue_attention_block[chat_key] = {}
        
        # 检查是否超过最大追踪用户数
        if len(AttentionManager._fatigue_attention_block[chat_key]) >= AttentionManager.MAX_TRACKED_USERS:
            # 清理最旧的封锁记录
            oldest_user = min(
                AttentionManager._fatigue_attention_block[chat_key].items(),
                key=lambda x: x[1].get("blocked_at", 0)
            )
            del AttentionManager._fatigue_attention_block[chat_key][oldest_user[0]]
            if DEBUG_MODE:
                logger.info(f"[疲劳封锁] 清理最旧封锁记录: {oldest_user[0]}")
        
        # 添加封锁记录
        AttentionManager._fatigue_attention_block[chat_key][user_id] = {
            "blocked_at": time.time(),
            "fatigue_level": fatigue_level,
        }
        
        user_name = AttentionManager._attention_map[chat_key][user_id].get("user_name", "未知")
        logger.info(
            f"[疲劳封锁] 🔒 用户 {user_name}(ID:{user_id}) 进入疲劳状态({fatigue_level})，"
            f"注意力增长已封锁"
        )
        
        return True

    @staticmethod
    async def _release_fatigue_attention_block(chat_key: str, user_id: str) -> bool:
        """
        解除用户的疲劳注意力封锁（内部方法）
        
        Args:
            chat_key: 会话标识
            user_id: 用户ID
            
        Returns:
            是否成功解除（如果用户不在封锁列表中返回False）
        """
        if chat_key not in AttentionManager._fatigue_attention_block:
            return False
        if user_id not in AttentionManager._fatigue_attention_block[chat_key]:
            return False
        
        # 获取用户名用于日志
        user_name = "未知"
        if chat_key in AttentionManager._attention_map:
            if user_id in AttentionManager._attention_map[chat_key]:
                user_name = AttentionManager._attention_map[chat_key][user_id].get("user_name", "未知")
        
        old_info = AttentionManager._fatigue_attention_block[chat_key].pop(user_id)
        
        # 清理空的会话记录
        if not AttentionManager._fatigue_attention_block[chat_key]:
            del AttentionManager._fatigue_attention_block[chat_key]
        
        logger.info(
            f"[疲劳封锁] 🔓 用户 {user_name}(ID:{user_id}) 疲劳封锁已解除 "
            f"(原等级: {old_info.get('fatigue_level', 'unknown')})"
        )
        
        return True

    @staticmethod
    def _is_fatigue_attention_blocked(chat_key: str, user_id: str) -> bool:
        """
        检查用户是否处于疲劳注意力封锁状态（同步方法，可在_lock内调用）
        
        Args:
            chat_key: 会话标识
            user_id: 用户ID
            
        Returns:
            是否被封锁
        """
        if chat_key not in AttentionManager._fatigue_attention_block:
            return False
        if user_id not in AttentionManager._fatigue_attention_block[chat_key]:
            return False
        
        # 检查是否超过重置阈值时间（自动解除）
        block_info = AttentionManager._fatigue_attention_block[chat_key][user_id]
        blocked_at = block_info.get("blocked_at", 0)
        current_time = time.time()
        
        if current_time - blocked_at >= AttentionManager.CONSECUTIVE_REPLY_RESET_THRESHOLD:
            # 超过重置阈值，自动解除封锁
            # 注意：这里不能直接删除，因为可能在迭代中，标记为需要清理
            return False
        
        return True

    @staticmethod
    async def _check_and_cleanup_expired_blocks(chat_key: str) -> None:
        """
        检查并清理过期的疲劳封锁记录（内部方法）
        
        Args:
            chat_key: 会话标识
        """
        if chat_key not in AttentionManager._fatigue_attention_block:
            return
        
        current_time = time.time()
        expired_users = []
        
        for user_id, block_info in AttentionManager._fatigue_attention_block[chat_key].items():
            blocked_at = block_info.get("blocked_at", 0)
            if current_time - blocked_at >= AttentionManager.CONSECUTIVE_REPLY_RESET_THRESHOLD:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            await AttentionManager._release_fatigue_attention_block(chat_key, user_id)
            if DEBUG_MODE:
                logger.info(f"[疲劳封锁] 自动解除过期封锁: {user_id}")


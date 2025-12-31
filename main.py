"""
群聊增强插件 - Group Chat Plus
基于AI读空气的群聊增强插件，让bot更懂氛围

核心功能：
1. AI读空气判断 - 智能决定是否回复消息
2. 动态概率调整 - 回复后提高触发概率，促进连续对话
3. 图片识别支持 - 可将图片转为文字描述
4. 上下文记忆 - 自动管理聊天历史
5. 记忆植入 - 集成长期记忆系统
6. 工具提醒 - 提示AI可用的功能
7. @消息快速响应 - 跳过概率判断直接回复
8. 智能缓存 - 避免对话上下文丢失
9. 官方历史同步 - 自动保存到系统对话记录
10. @提及智能识别 - 正确理解@别人的消息（v1.0.3新增）
11. 发送者识别增强 - 根据触发方式添加系统提示，帮助AI正确识别发送者（v1.0.4新增）
12. 🆕 主动对话功能 - AI会在沉默后主动发起新话题（v1.1.0新增）
13. 🆕 回复后戳一戳 - AI回复后根据概率戳一戳发送者，模拟真人互动（v1.1.0新增）
14. 🆕 关键词智能模式 - 可选择关键词触发时保留AI判断，更灵活（v1.1.2新增）

缓存工作原理：
- 通过初筛的消息先放入缓存
- AI不回复时保存到自定义存储，保留上下文
- AI回复时一次性转存到官方系统并清空缓存
- 自动清理超过30分钟的旧消息，最多保留10条

使用提示：
- 只在群聊生效，私聊消息不处理
- enabled_groups留空=全部群启用，填群号=仅指定群启用
- @消息会跳过所有判断直接回复

作者: Him666233
版本: v1.1.2

v1.1.2 更新内容：
- 🆕 关键词智能模式 - 新增配置选项，开启后触发关键词时只跳过概率筛选，但保留AI读空气判断
- 📝 允许用户自主选择关键词触发的处理方式：完全强制回复 or AI智能判断

v1.1.0 更新内容：
- 🆕 主动对话功能 - AI会在长时间沉默后主动发起新话题
- 🆕 临时概率提升 - AI主动发言后短暂提升回复概率，模拟真人"等待回应"行为
- 🆕 时间段控制 - 可设置禁用时段（如深夜），支持平滑过渡
- 🆕 用户活跃度检测 - 避免在死群突然说话
- 🆕 连续失败保护 - 主动发言无人理会自动进入冷却
- 🆕 特殊提示词处理 - 主动对话提示词保留到历史，让AI理解上下文
- 🆕 回复后戳一戳 - AI回复后根据概率戳一戳发送者（仅QQ+aiocqhttp）

v1.0.9 更新内容：
- 新增戳一戳消息处理功能（仅支持QQ平台+aiocqhttp）
- 支持三种模式：ignore(忽略)、bot_only(仅戳机器人)、all(所有戳一戳)
- 添加戳一戳系统提示词，帮助AI正确理解戳一戳场景
- 在保存历史时自动过滤戳一戳提示词
"""

import random
import time
import copy
import sys
import hashlib
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import List, Optional
from collections import OrderedDict
import aiohttp
from astrbot.api import logger


from astrbot.api.all import *
from astrbot.api.event import filter
from astrbot.core.star.star_tools import StarTools

# 导入消息组件类型
from astrbot.core.message.components import Plain, Poke, At, AtAll
from astrbot.core.message.message_event_result import MessageChain

# 导入 ProviderRequest 类型用于类型判断
from astrbot.core.provider.entities import ProviderRequest

# 导入 aiocqhttp 相关类型
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)

# 导入所有工具模块
from .utils import (
    ProbabilityManager,
    MessageProcessor,
    ImageHandler,
    ContextManager,
    DecisionAI,
    ReplyHandler,
    MemoryInjector,
    ToolsReminder,
    KeywordChecker,
    MessageCleaner,
    AttentionManager,
    ProactiveChatManager,  # 🆕 v1.1.0: 主动对话管理器
    TypoGenerator,  # v1.0.2: 打字错误生成器
    MoodTracker,  # v1.0.2: 情绪追踪系统
    FrequencyAdjuster,  # v1.0.2: 频率动态调整器
    TypingSimulator,  # v1.0.2: 回复延迟模拟器
    TimePeriodManager,  # v1.1.0: 时间段管理器
    HumanizeModeManager,  # 🆕 v1.2.0: 拟人增强模式管理器
    CooldownManager,  # 🆕 v1.2.0: 注意力冷却机制管理器
    PlatformLTMHelper,  # 🆕 v1.2.0: 平台 LTM 辅助（获取平台图片描述）
)
from .utils.content_filter import ContentFilterManager  # 🆕 v1.2.0: AI回复内容过滤器


@register(
    "chat_plus",
    "Him666233",
    "一个以AI读空气为主的群聊聊天效果增强插件",
    "v1.1.2",
    "https://github.com/Him666233/astrbot_plugin_group_chat_plus",
)
class ChatPlus(Star):
    """
    群聊增强插件主类

    采用事件监听而非消息拦截，确保与其他插件兼容
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化插件

        Args:
            context: AstrBot的Context对象，包含各种API
            config: 插件配置
        """
        super().__init__(context)
        self.context = context
        self.config = config

        # ========== 🔧 配置参数集中提取区块 ==========
        # 说明：为避免 AstrBot 平台多次读取配置可能导致的问题，
        # 所有配置参数在此处一次性提取到实例变量中，后续代码直接使用这些变量
        # =============================================

        # === 基础配置 ===
        self.enable_group_chat = config.get("enable_group_chat", True)  # 群聊功能总开关
        self.debug_mode = config.get("enable_debug_log", False)  # 调试日志开关
        self.enabled_groups = config.get("enabled_groups", [])  # 启用的群组列表

        # === 概率相关配置 ===
        self.initial_probability = config.get(
            "initial_probability", 0.3
        )  # 初始读空气概率
        self.after_reply_probability = config.get(
            "after_reply_probability", 0.8
        )  # 回复后概率
        self.probability_duration = config.get(
            "probability_duration", 120
        )  # 概率提升持续时间

        # === 决策AI配置 ===
        self.decision_ai_provider_id = config.get(
            "decision_ai_provider_id", ""
        )  # 读空气AI提供商ID
        self.decision_ai_extra_prompt = config.get(
            "decision_ai_extra_prompt", ""
        )  # 读空气AI额外提示词
        self.decision_ai_timeout = config.get(
            "decision_ai_timeout", 30
        )  # 读空气AI超时时间
        self.decision_ai_prompt_mode = config.get(
            "decision_ai_prompt_mode", "append"
        )  # 读空气AI提示词模式

        # === 回复AI配置 ===
        self.reply_ai_extra_prompt = config.get(
            "reply_ai_extra_prompt", ""
        )  # 回复AI额外提示词
        self.reply_ai_prompt_mode = config.get(
            "reply_ai_prompt_mode", "append"
        )  # 回复AI提示词模式

        # === 消息格式配置 ===
        self.include_timestamp = config.get("include_timestamp", True)  # 包含时间戳
        self.include_sender_info = config.get(
            "include_sender_info", True
        )  # 包含发送者信息
        # 🔧 修复：确保 max_context_messages 是整数类型
        _max_context_raw = config.get("max_context_messages", -1)
        try:
            self.max_context_messages = int(_max_context_raw) if _max_context_raw is not None else -1
        except (ValueError, TypeError):
            logger.warning(f"⚠️ max_context_messages 配置值 '{_max_context_raw}' 无法转换为整数，使用默认值 -1")
            self.max_context_messages = -1

        # === 📦 消息缓存配置 ===
        # 缓存最大条数（保护上限50条）
        CACHE_MAX_COUNT_LIMIT = 50  # 系统保护上限
        _cache_max_count_raw = config.get("pending_cache_max_count", 10)
        try:
            _cache_max_count = int(_cache_max_count_raw) if _cache_max_count_raw is not None else 10
        except (ValueError, TypeError):
            logger.warning(f"⚠️ pending_cache_max_count 配置值 '{_cache_max_count_raw}' 无法转换为整数，使用默认值 10")
            _cache_max_count = 10
        # 应用保护上限
        if _cache_max_count > CACHE_MAX_COUNT_LIMIT:
            logger.warning(f"⚠️ pending_cache_max_count 配置值 {_cache_max_count} 超过系统保护上限 {CACHE_MAX_COUNT_LIMIT}，已自动调整为 {CACHE_MAX_COUNT_LIMIT}")
            _cache_max_count = CACHE_MAX_COUNT_LIMIT
        elif _cache_max_count < 1:
            logger.warning(f"⚠️ pending_cache_max_count 配置值 {_cache_max_count} 小于1，已自动调整为 1")
            _cache_max_count = 1
        self.pending_cache_max_count = _cache_max_count

        # 缓存过期时间（保护上限7200秒=2小时）
        CACHE_TTL_LIMIT = 7200  # 系统保护上限（秒）
        _cache_ttl_raw = config.get("pending_cache_ttl_seconds", 1800)
        try:
            _cache_ttl = int(_cache_ttl_raw) if _cache_ttl_raw is not None else 1800
        except (ValueError, TypeError):
            logger.warning(f"⚠️ pending_cache_ttl_seconds 配置值 '{_cache_ttl_raw}' 无法转换为整数，使用默认值 1800")
            _cache_ttl = 1800
        # 应用保护上限
        if _cache_ttl > CACHE_TTL_LIMIT:
            logger.warning(f"⚠️ pending_cache_ttl_seconds 配置值 {_cache_ttl} 超过系统保护上限 {CACHE_TTL_LIMIT}秒，已自动调整为 {CACHE_TTL_LIMIT}秒")
            _cache_ttl = CACHE_TTL_LIMIT
        elif _cache_ttl < 60:
            logger.warning(f"⚠️ pending_cache_ttl_seconds 配置值 {_cache_ttl} 小于60秒，已自动调整为 60秒")
            _cache_ttl = 60
        self.pending_cache_ttl_seconds = _cache_ttl

        # === 图片处理配置 ===
        self.enable_image_processing = config.get(
            "enable_image_processing", False
        )  # 启用图片处理
        self.image_to_text_scope = config.get(
            "image_to_text_scope", "mention_only"
        )  # 图片转文字范围
        self.image_to_text_provider_id = config.get(
            "image_to_text_provider_id", ""
        )  # 图片转文字AI提供商
        self.image_to_text_prompt = config.get(
            "image_to_text_prompt", "请详细描述这张图片的内容"
        )  # 图片转文字提示词
        self.image_to_text_timeout = config.get(
            "image_to_text_timeout", 60
        )  # 图片转文字超时时间

        # === 🖼️ 平台图片描述提取配置 ===
        self.platform_image_caption_max_wait = config.get(
            "platform_image_caption_max_wait", 2.0
        )  # 平台图片描述最大等待时间(秒)
        self.platform_image_caption_retry_interval = config.get(
            "platform_image_caption_retry_interval", 50
        )  # 平台图片描述重试间隔(毫秒)
        self.platform_image_caption_fast_check_count = config.get(
            "platform_image_caption_fast_check_count", 5
        )  # 平台图片描述快速检查次数
        self.probability_filter_cache_delay = config.get(
            "probability_filter_cache_delay", 50
        )  # 概率过滤缓存延迟(毫秒)

        # === 记忆植入配置 ===
        self.enable_memory_injection = config.get(
            "enable_memory_injection", False
        )  # 启用记忆植入
        self.memory_plugin_mode = config.get(
            "memory_plugin_mode", "legacy"
        )  # 记忆插件模式
        self.memory_insertion_timing = config.get(
            "memory_insertion_timing", "post_decision"
        )  # 记忆插入时机
        self.livingmemory_top_k = config.get(
            "livingmemory_top_k", 5
        )  # LivingMemory召回数量

        # === 工具提醒配置 ===
        self.enable_tools_reminder = config.get(
            "enable_tools_reminder", False
        )  # 启用工具提醒

        # === 关键词配置 ===
        self.trigger_keywords = config.get("trigger_keywords", [])  # 触发关键词列表
        self.blacklist_keywords = config.get(
            "blacklist_keywords", []
        )  # 黑名单关键词列表
        self.keyword_smart_mode = config.get(
            "keyword_smart_mode", False
        )  # 关键词智能模式

        # === 用户黑名单配置 ===
        self.enable_user_blacklist = config.get(
            "enable_user_blacklist", False
        )  # 启用用户黑名单
        self.blacklist_user_ids = config.get(
            "blacklist_user_ids", []
        )  # 黑名单用户ID列表

        # === 指令过滤配置 ===
        self.enable_command_filter = config.get(
            "enable_command_filter", True
        )  # 启用指令过滤
        self.command_prefixes = config.get(
            "command_prefixes", ["/", "!", "#"]
        )  # 指令前缀列表
        self.enable_full_command_detection = config.get(
            "enable_full_command_detection", False
        )  # 启用完整指令检测
        self.full_command_list = config.get(
            "full_command_list", ["new", "help", "reset"]
        )  # 完整指令列表
        self.enable_command_prefix_match = config.get(
            "enable_command_prefix_match", False
        )  # 启用指令前缀匹配
        self.command_prefix_match_list = config.get(
            "command_prefix_match_list", []
        )  # 指令前缀匹配列表

        # === 重置指令白名单配置 ===
        self.plugin_gcp_reset_allowed_user_ids = config.get(
            "plugin_gcp_reset_allowed_user_ids", []
        )
        self.plugin_gcp_reset_here_allowed_user_ids = config.get(
            "plugin_gcp_reset_here_allowed_user_ids", []
        )

        # === @消息处理配置 ===
        self.enable_ignore_at_others = config.get(
            "enable_ignore_at_others", False
        )  # 启用忽略@他人
        self.ignore_at_others_mode = config.get(
            "ignore_at_others_mode", "strict"
        )  # @他人忽略模式
        self.enable_ignore_at_all = config.get(
            "enable_ignore_at_all", False
        )  # 启用忽略@全体成员

        # === 戳一戳配置 ===
        self.poke_message_mode = config.get(
            "poke_message_mode", "bot_only"
        )  # 戳一戳消息处理模式
        self.poke_bot_skip_probability = config.get(
            "poke_bot_skip_probability", True
        )  # 戳机器人跳过概率
        self.poke_bot_probability_boost_reference = config.get(
            "poke_bot_probability_boost_reference", 0.3
        )  # 戳一戳概率增值参考
        self.poke_reverse_on_poke_probability_raw = config.get(
            "poke_reverse_on_poke_probability", 0.0
        )  # 反戳概率原始值
        self.enable_poke_after_reply = config.get(
            "enable_poke_after_reply", False
        )  # 启用回复后戳一戳
        self.poke_after_reply_probability = config.get(
            "poke_after_reply_probability", 0.15
        )  # 回复后戳一戳概率
        self.poke_after_reply_delay = config.get(
            "poke_after_reply_delay", 0.5
        )  # 回复后戳一戳延迟
        self.enable_poke_trace_prompt = config.get(
            "enable_poke_trace_prompt", False
        )  # 启用戳过对方追踪
        self.poke_trace_max_tracked_users = config.get(
            "poke_trace_max_tracked_users", 5
        )  # 戳过对方最大追踪人数
        self.poke_trace_ttl_seconds = config.get(
            "poke_trace_ttl_seconds", 300
        )  # 戳过对方提示有效期
        self.poke_enabled_groups = config.get(
            "poke_enabled_groups", []
        )  # 戳一戳功能群聊白名单

        # === 注意力机制配置 ===
        self.enable_attention_mechanism = config.get(
            "enable_attention_mechanism", False
        )  # 启用注意力机制
        self.attention_increased_probability = config.get(
            "attention_increased_probability", 0.9
        )  # 注意力提升参考值
        self.attention_decreased_probability = config.get(
            "attention_decreased_probability", 0.1
        )  # 注意力降低参考值
        self.attention_duration = config.get(
            "attention_duration", 120
        )  # 注意力数据清理周期
        self.attention_max_tracked_users = config.get(
            "attention_max_tracked_users", 10
        )  # 最大追踪用户数
        self.attention_decay_halflife = config.get(
            "attention_decay_halflife", 300
        )  # 注意力衰减半衰期
        self.emotion_decay_halflife = config.get(
            "emotion_decay_halflife", 600
        )  # 情绪衰减半衰期
        self.attention_decrease_on_no_reply_step = config.get(
            "attention_decrease_on_no_reply_step", 0.15
        )  # 不回复时注意力衰减
        self.attention_decrease_threshold = config.get(
            "attention_decrease_threshold", 0.3
        )  # 注意力衰减阈值
        self.attention_boost_step = config.get(
            "attention_boost_step", 0.4
        )  # 被回复用户注意力增加幅度
        self.attention_decrease_step = config.get(
            "attention_decrease_step", 0.1
        )  # 其他用户注意力减少幅度
        self.emotion_boost_step = config.get(
            "emotion_boost_step", 0.1
        )  # 被回复用户情绪增加幅度
        # 注意力情感检测配置
        self.enable_attention_emotion_detection = config.get(
            "enable_attention_emotion_detection", False
        )  # 启用注意力情感检测
        self.attention_emotion_keywords = config.get(
            "attention_emotion_keywords",
            '{"正面": ["谢谢", "感谢", "太好了", "棒", "赞"], "负面": ["傻", "蠢", "笨", "垃圾", "讨厌"]}',
        )  # 注意力情感关键词
        self.attention_enable_negation = config.get(
            "attention_enable_negation", True
        )  # 注意力机制启用否定词检测
        self.attention_negation_words = config.get(
            "attention_negation_words",
            ["不", "没", "别", "非", "无", "未", "勿", "莫", "不是", "没有"],
        )  # 注意力否定词列表
        self.attention_negation_check_range = config.get(
            "attention_negation_check_range", 5
        )  # 注意力否定词检查范围
        self.attention_positive_emotion_boost = config.get(
            "attention_positive_emotion_boost", 0.1
        )  # 正面消息情绪额外提升
        self.attention_negative_emotion_decrease = config.get(
            "attention_negative_emotion_decrease", 0.15
        )  # 负面消息情绪降低幅度
        # 注意力溢出机制配置
        self.enable_attention_spillover = config.get(
            "enable_attention_spillover", True
        )  # 启用注意力溢出
        self.attention_spillover_ratio = config.get(
            "attention_spillover_ratio", 0.35
        )  # 注意力溢出比例
        self.attention_spillover_decay_halflife = config.get(
            "attention_spillover_decay_halflife", 90
        )  # 溢出效果衰减半衰期
        self.attention_spillover_min_trigger = config.get(
            "attention_spillover_min_trigger", 0.4
        )  # 触发溢出的最低注意力阈值

        # === 注意力冷却机制配置 ===
        self.enable_attention_cooldown = config.get(
            "enable_attention_cooldown", True
        )  # 启用注意力冷却
        self.cooldown_max_duration = config.get(
            "cooldown_max_duration", 600
        )  # 冷却最大持续时间
        self.cooldown_trigger_threshold = config.get(
            "cooldown_trigger_threshold", 0.3
        )  # 触发冷却的注意力阈值
        self.cooldown_attention_decrease = config.get(
            "cooldown_attention_decrease", 0.2
        )  # 冷却时额外降低的注意力值

        # === 🆕 对话疲劳机制配置 ===
        self.enable_conversation_fatigue = config.get(
            "enable_conversation_fatigue", False
        )  # 启用对话疲劳机制
        self.fatigue_reset_threshold = max(60, config.get(
            "fatigue_reset_threshold", 300
        ))  # 连续对话重置阈值（秒），最小60秒
        self.fatigue_threshold_light = max(1, config.get(
            "fatigue_threshold_light", 3
        ))  # 轻度疲劳阈值，最小1轮
        self.fatigue_threshold_medium = max(self.fatigue_threshold_light + 1, config.get(
            "fatigue_threshold_medium", 5
        ))  # 中度疲劳阈值，必须大于轻度
        self.fatigue_threshold_heavy = max(self.fatigue_threshold_medium + 1, config.get(
            "fatigue_threshold_heavy", 8
        ))  # 重度疲劳阈值，必须大于中度
        self.fatigue_probability_decrease_light = max(0.0, min(1.0, config.get(
            "fatigue_probability_decrease_light", 0.1
        )))  # 轻度疲劳概率降低幅度，限制在[0,1]
        self.fatigue_probability_decrease_medium = max(0.0, min(1.0, config.get(
            "fatigue_probability_decrease_medium", 0.2
        )))  # 中度疲劳概率降低幅度，限制在[0,1]
        self.fatigue_probability_decrease_heavy = max(0.0, min(1.0, config.get(
            "fatigue_probability_decrease_heavy", 0.35
        )))  # 重度疲劳概率降低幅度，限制在[0,1]
        self.fatigue_closing_probability = max(0.0, min(1.0, config.get(
            "fatigue_closing_probability", 0.3
        )))  # 疲劳收尾话语概率，限制在[0,1]
        
        # 验证概率降低幅度的递增关系
        if self.fatigue_probability_decrease_light > self.fatigue_probability_decrease_medium:
            logger.warning(
                f"[对话疲劳] 配置异常: 轻度概率降低({self.fatigue_probability_decrease_light}) > "
                f"中度({self.fatigue_probability_decrease_medium})，已自动修正"
            )
            self.fatigue_probability_decrease_light, self.fatigue_probability_decrease_medium = (
                self.fatigue_probability_decrease_medium, self.fatigue_probability_decrease_light
            )
        if self.fatigue_probability_decrease_medium > self.fatigue_probability_decrease_heavy:
            logger.warning(
                f"[对话疲劳] 配置异常: 中度概率降低({self.fatigue_probability_decrease_medium}) > "
                f"重度({self.fatigue_probability_decrease_heavy})，已自动修正"
            )
            self.fatigue_probability_decrease_medium, self.fatigue_probability_decrease_heavy = (
                self.fatigue_probability_decrease_heavy, self.fatigue_probability_decrease_medium
            )

        # === 拟人增强模式配置 ===
        self.enable_humanize_mode = config.get(
            "enable_humanize_mode", False
        )  # 启用拟人增强模式
        self.humanize_silent_mode_threshold = config.get(
            "humanize_silent_mode_threshold", 3
        )
        self.humanize_silent_max_duration = config.get(
            "humanize_silent_max_duration", 600
        )
        self.humanize_silent_max_messages = config.get(
            "humanize_silent_max_messages", 8
        )
        self.humanize_enable_dynamic_threshold = config.get(
            "humanize_enable_dynamic_threshold", True
        )
        self.humanize_base_message_threshold = config.get(
            "humanize_base_message_threshold", 1
        )
        self.humanize_max_message_threshold = config.get(
            "humanize_max_message_threshold", 3
        )
        self.humanize_include_decision_history = config.get(
            "humanize_include_decision_history", True
        )
        self.humanize_interest_keywords = config.get("humanize_interest_keywords", [])
        self.humanize_interest_boost_probability = config.get(
            "humanize_interest_boost_probability", 0.3
        )

        # === 打字错误生成器配置 ===
        self.enable_typo_generator = config.get(
            "enable_typo_generator", True
        )  # 启用打字错误生成器
        self.typo_error_rate = config.get("typo_error_rate", 0.02)  # 打字错误概率
        self.typo_homophones = config.get(
            "typo_homophones",
            '{"的": ["得", "地"], "得": ["的", "地"], "地": ["的", "得"]}',
        )  # 同音字映射表
        self.typo_min_text_length = config.get(
            "typo_min_text_length", 5
        )  # 添加错字的最小文本长度
        self.typo_min_chinese_chars = config.get(
            "typo_min_chinese_chars", 3
        )  # 添加错字的最小汉字数量
        self.typo_min_message_length = config.get(
            "typo_min_message_length", 10
        )  # 触发错字判断的最小消息长度
        self.typo_min_count = config.get("typo_min_count", 0)  # 每条消息最少添加错字数
        self.typo_max_count = config.get("typo_max_count", 2)  # 每条消息最多添加错字数

        # === 情绪追踪系统配置 ===
        self.enable_mood_system = config.get("enable_mood_system", True)  # 启用情绪系统
        self.negation_words = config.get(
            "negation_words",
            [
                "不",
                "没",
                "别",
                "非",
                "无",
                "未",
                "勿",
                "莫",
                "不是",
                "没有",
                "别再",
                "一点也不",
                "根本不",
                "从不",
                "绝不",
                "毫不",
            ],
        )  # 否定词列表
        self.negation_check_range = config.get(
            "negation_check_range", 5
        )  # 否定词检查范围
        self.mood_keywords = config.get(
            "mood_keywords",
            '{"开心": ["哈哈", "笑", "😂", "😄", "👍"], "难过": ["难过", "伤心", "哭", "😢", "😭"]}',
        )  # 情绪关键词配置
        self.mood_decay_time = config.get("mood_decay_time", 300)  # 情绪衰减时间
        self.mood_cleanup_threshold = config.get(
            "mood_cleanup_threshold", 3600
        )  # 情绪记录清理阈值
        self.mood_cleanup_interval = config.get(
            "mood_cleanup_interval", 600
        )  # 情绪记录清理检查间隔

        # === 频率动态调整配置 ===
        self.enable_frequency_adjuster = config.get(
            "enable_frequency_adjuster", True
        )  # 启用频率调整
        self.frequency_check_interval = config.get(
            "frequency_check_interval", 180
        )  # 频率检查间隔
        self.frequency_min_message_count = config.get(
            "frequency_min_message_count", 8
        )  # 最小消息数
        self.frequency_analysis_message_count = config.get(
            "frequency_analysis_message_count", 15
        )  # 分析消息数
        self.frequency_analysis_timeout = config.get(
            "frequency_analysis_timeout", 20
        )  # 分析超时
        self.frequency_adjust_duration = config.get(
            "frequency_adjust_duration", 360
        )  # 调整持续时间
        self.frequency_decrease_factor = config.get(
            "frequency_decrease_factor", 0.85
        )  # 降低系数
        self.frequency_increase_factor = config.get(
            "frequency_increase_factor", 1.15
        )  # 提升系数
        self.frequency_min_probability = config.get(
            "frequency_min_probability", 0.05
        )  # 最小概率
        self.frequency_max_probability = config.get(
            "frequency_max_probability", 0.95
        )  # 最大概率

        # === 回复延迟模拟配置 ===
        self.enable_typing_simulator = config.get(
            "enable_typing_simulator", True
        )  # 启用回复延迟
        self.typing_speed = config.get("typing_speed", 15.0)  # 打字速度
        self.typing_max_delay = config.get("typing_max_delay", 3.0)  # 最大延迟

        # === 主动对话配置 ===
        self.enable_proactive_chat = config.get(
            "enable_proactive_chat", False
        )  # 启用主动对话
        self.proactive_enabled_groups = config.get(
            "proactive_enabled_groups", []
        )  # 主动对话启用群组
        self.proactive_silence_threshold = config.get(
            "proactive_silence_threshold", 600
        )  # 沉默阈值
        self.proactive_probability = config.get(
            "proactive_probability", 0.3
        )  # 主动对话概率
        self.proactive_check_interval = config.get(
            "proactive_check_interval", 60
        )  # 检查间隔
        self.proactive_require_user_activity = config.get(
            "proactive_require_user_activity", True
        )  # 需要用户活跃
        self.proactive_min_user_messages = config.get(
            "proactive_min_user_messages", 3
        )  # 最少用户消息数
        self.proactive_user_activity_window = config.get(
            "proactive_user_activity_window", 300
        )  # 用户活跃时间窗口
        self.proactive_max_consecutive_failures = config.get(
            "proactive_max_consecutive_failures", 3
        )  # 最大连续失败次数
        self.proactive_failure_sequence_probability = config.get(
            "proactive_failure_sequence_probability", -1.0
        )  # 连续失败尝试计入概率
        self.proactive_failure_threshold_perturbation = config.get(
            "proactive_failure_threshold_perturbation", 0.0
        )  # 连续失败冷却阈值扰动因子
        self.proactive_cooldown_duration = config.get(
            "proactive_cooldown_duration", 1800
        )  # 失败后冷却时间
        self.proactive_temp_boost_probability = config.get(
            "proactive_temp_boost_probability", 0.5
        )  # 临时概率提升
        self.proactive_temp_boost_duration = config.get(
            "proactive_temp_boost_duration", 120
        )  # 临时提升持续时间
        self.proactive_enable_quiet_time = config.get(
            "proactive_enable_quiet_time", False
        )  # 启用禁用时段
        self.proactive_quiet_start = config.get(
            "proactive_quiet_start", "23:00"
        )  # 禁用时段开始
        self.proactive_quiet_end = config.get(
            "proactive_quiet_end", "07:00"
        )  # 禁用时段结束
        self.proactive_transition_minutes = config.get(
            "proactive_transition_minutes", 30
        )  # 过渡时长
        self.proactive_prompt = config.get("proactive_prompt", "")  # 主动对话提示词
        self.proactive_retry_prompt = config.get(
            "proactive_retry_prompt", ""
        )  # 主动对话重试提示词
        self.proactive_generation_timeout_warning = config.get(
            "proactive_generation_timeout_warning", 15
        )  # 主动对话生成超时警告阈值
        # 注意力感知主动对话配置
        self.proactive_use_attention = config.get(
            "proactive_use_attention", True
        )  # 启用注意力感知主动对话
        self.proactive_attention_reference_probability = config.get(
            "proactive_attention_reference_probability", 0.7
        )  # 参考注意力排行榜的概率
        self.proactive_attention_rank_weights = config.get(
            "proactive_attention_rank_weights", "1:55,2:25,3:12,4:8"
        )  # 排名选中权重分配
        self.proactive_attention_max_selected_users = config.get(
            "proactive_attention_max_selected_users", 2
        )  # 每次最多关注用户数
        self.proactive_focus_last_user_probability = config.get(
            "proactive_focus_last_user_probability", 0.6
        )  # 对话延续性提示概率
        self.proactive_reply_context_prompt = config.get(
            "proactive_reply_context_prompt", ""
        )  # 读空气AI主动对话回复上下文提示词
        # 自适应主动对话配置
        self.enable_adaptive_proactive = config.get(
            "enable_adaptive_proactive", True
        )  # 启用自适应主动对话
        self.interaction_score_min = config.get(
            "interaction_score_min", 10
        )  # 评分最小值
        self.interaction_score_max = config.get(
            "interaction_score_max", 100
        )  # 评分最大值
        self.score_increase_on_success = config.get(
            "score_increase_on_success", 15
        )  # 成功加分
        self.score_decrease_on_fail = config.get(
            "score_decrease_on_fail", 8
        )  # 失败扣分
        self.score_quick_reply_bonus = config.get(
            "score_quick_reply_bonus", 5
        )  # 快速回复额外加分
        self.score_multi_user_bonus = config.get(
            "score_multi_user_bonus", 10
        )  # 多人回复额外加分
        self.score_streak_bonus = config.get("score_streak_bonus", 5)  # 连续成功奖励
        self.score_revival_bonus = config.get("score_revival_bonus", 20)  # 低分复苏奖励
        self.interaction_score_decay_rate = config.get(
            "interaction_score_decay_rate", 2
        )  # 评分每日衰减值
        # 吐槽系统配置
        self.enable_complaint_system = config.get(
            "enable_complaint_system", True
        )  # 启用吐槽系统
        self.complaint_trigger_threshold = config.get(
            "complaint_trigger_threshold", 2
        )  # 触发吐槽的最低累积失败次数
        self.complaint_level_light = config.get(
            "complaint_level_light", 2
        )  # 轻度吐槽触发次数
        self.complaint_level_medium = config.get(
            "complaint_level_medium", 3
        )  # 明显吐槽触发次数
        self.complaint_level_strong = config.get(
            "complaint_level_strong", 4
        )  # 强烈吐槽触发次数
        self.complaint_probability_light = config.get(
            "complaint_probability_light", 0.3
        )  # 轻度吐槽触发概率
        self.complaint_probability_medium = config.get(
            "complaint_probability_medium", 0.6
        )  # 明显吐槽触发概率
        self.complaint_probability_strong = config.get(
            "complaint_probability_strong", 0.8
        )  # 强烈吐槽触发概率
        self.complaint_decay_on_success = config.get(
            "complaint_decay_on_success", 2
        )  # 成功互动时的失败次数衰减量
        self.complaint_decay_check_interval = config.get(
            "complaint_decay_check_interval", 21600
        )  # 时间衰减检查间隔
        self.complaint_decay_no_failure_threshold = config.get(
            "complaint_decay_no_failure_threshold", 43200
        )  # 无失败时间阈值
        self.complaint_decay_amount = config.get(
            "complaint_decay_amount", 1
        )  # 时间衰减数量
        self.complaint_max_accumulation = config.get(
            "complaint_max_accumulation", 15
        )  # 累积失败次数上限

        # === 动态时间段概率调整配置 ===
        self.enable_dynamic_reply_probability = config.get(
            "enable_dynamic_reply_probability", False
        )  # 启用普通回复动态调整
        self.reply_time_periods = config.get(
            "reply_time_periods", "[]"
        )  # 普通回复时间段配置
        self.reply_time_transition_minutes = config.get(
            "reply_time_transition_minutes", 30
        )  # 过渡时长
        self.reply_time_min_factor = config.get(
            "reply_time_min_factor", 0.1
        )  # 最小系数
        self.reply_time_max_factor = config.get(
            "reply_time_max_factor", 2.0
        )  # 最大系数
        self.reply_time_use_smooth_curve = config.get(
            "reply_time_use_smooth_curve", True
        )  # 使用平滑曲线
        self.enable_dynamic_proactive_probability = config.get(
            "enable_dynamic_proactive_probability", False
        )  # 启用主动对话动态调整
        self.proactive_time_periods = config.get(
            "proactive_time_periods", "[]"
        )  # 主动对话时间段配置
        self.proactive_time_transition_minutes = config.get(
            "proactive_time_transition_minutes", 45
        )  # 主动对话过渡时长
        self.proactive_time_min_factor = config.get(
            "proactive_time_min_factor", 0.0
        )  # 主动对话最小系数
        self.proactive_time_max_factor = config.get(
            "proactive_time_max_factor", 2.0
        )  # 主动对话最大系数
        self.proactive_time_use_smooth_curve = config.get(
            "proactive_time_use_smooth_curve", True
        )  # 主动对话使用平滑曲线

        # === 概率硬性限制配置 ===
        self.enable_probability_hard_limit = config.get(
            "enable_probability_hard_limit", False
        )  # 启用概率硬性限制
        self.probability_min_limit = config.get(
            "probability_min_limit", 0.05
        )  # 概率最小值限制
        self.probability_max_limit = config.get(
            "probability_max_limit", 0.8
        )  # 概率最大值限制

        # === AI回复内容过滤配置 ===
        self.enable_output_content_filter = config.get(
            "enable_output_content_filter", False
        )  # 启用输出内容过滤
        self.output_content_filter_rules = config.get(
            "output_content_filter_rules", []
        )  # 输出过滤规则
        self.enable_save_content_filter = config.get(
            "enable_save_content_filter", False
        )  # 启用保存内容过滤
        self.save_content_filter_rules = config.get(
            "save_content_filter_rules", []
        )  # 保存过滤规则

        # === 超时警告配置 ===
        self.reply_timeout_warning_threshold = config.get(
            "reply_timeout_warning_threshold", 120
        )  # 消息处理超时警告阈值
        self.reply_generation_timeout_warning = config.get(
            "reply_generation_timeout_warning", 60
        )  # 回复生成超时警告阈值
        self.concurrent_wait_max_loops = config.get(
            "concurrent_wait_max_loops", 10
        )  # 并发等待最大循环次数
        self.concurrent_wait_interval = config.get(
            "concurrent_wait_interval", 1.0
        )  # 并发等待间隔
        self.typing_delay_timeout_warning = config.get(
            "typing_delay_timeout_warning", 5
        )  # 打字延迟超时警告

        # === 否定词检测配置 ===
        self.enable_negation_detection = config.get(
            "enable_negation_detection", True
        )  # 启用否定词检测

        # === AI重复消息拦截配置 ===
        # 🔒 系统硬上限常量（防止内存泄漏）
        self._DUPLICATE_CHECK_COUNT_LIMIT = 50  # 检查条数硬上限
        self._DUPLICATE_CACHE_SIZE_LIMIT = 100  # 缓存大小硬上限
        self._DUPLICATE_TIME_LIMIT_MAX = 7200  # 时效硬上限（2小时）
        
        self.enable_duplicate_filter = config.get(
            "enable_duplicate_filter", True
        )  # 启用AI重复消息拦截
        # 🔒 应用硬上限保护
        _raw_check_count = config.get("duplicate_filter_check_count", 5)
        self.duplicate_filter_check_count = min(
            max(1, _raw_check_count), self._DUPLICATE_CHECK_COUNT_LIMIT
        )  # 重复检测参考消息条数（1-50）
        self.enable_duplicate_time_limit = config.get(
            "enable_duplicate_time_limit", True
        )  # 启用重复检测时效性判断
        # 🔒 应用硬上限保护
        _raw_time_limit = config.get("duplicate_filter_time_limit", 1800)
        self.duplicate_filter_time_limit = min(
            max(60, _raw_time_limit), self._DUPLICATE_TIME_LIMIT_MAX
        )  # 重复检测时效(秒)（60-7200）

        # === 私信功能开关（暂未实现，仅提取） ===
        self.enable_private_chat = config.get(
            "enable_private_chat", False
        )  # 私信功能开关

        # ========== 配置参数集中提取区块结束 ==========

        # Dashboard 配置与重启 URL
        self.dbc = self.context.get_config().get("dashboard", {})
        self.host = self.dbc.get("host", "127.0.0.1")
        self.port = self.dbc.get("port", 6185)
        if os.environ.get("DASHBOARD_PORT"):
            self.port = int(os.environ.get("DASHBOARD_PORT"))
        if self.host == "0.0.0.0":
            self.host = "127.0.0.1"
        self.restart_url = f"http://{self.host}:{self.port}/api/stat/restart-core"

        # 统一设置详细日志开关到本插件的 utils 包及其子模块（使用相对导入，避免命名冲突）
        try:
            import importlib
            import pkgutil

            utils_pkg_name = f"{__package__}.utils" if __package__ else "utils"
            utils_pkg = importlib.import_module(utils_pkg_name)

            # 根级别开关
            if hasattr(utils_pkg, "set_debug_mode"):
                utils_pkg.set_debug_mode(self.debug_mode)
            elif hasattr(utils_pkg, "DEBUG_MODE"):
                setattr(utils_pkg, "DEBUG_MODE", self.debug_mode)

            # 批量同步子模块的 DEBUG_MODE（如存在）
            for mod_info in pkgutil.iter_modules(utils_pkg.__path__):
                mod_name = f"{utils_pkg_name}.{mod_info.name}"
                try:
                    mod = importlib.import_module(mod_name)
                    if hasattr(mod, "DEBUG_MODE"):
                        setattr(mod, "DEBUG_MODE", self.debug_mode)
                except Exception:
                    pass
        except Exception:
            pass

        # 初始化上下文管理器（使用插件专属数据目录）
        # 注意：StarTools.get_data_dir() 会自动检测插件名称
        data_dir = StarTools.get_data_dir()
        ContextManager.init(str(data_dir))

        # 🆕 v1.1.0: 初始化概率管理器（用于动态时间段调整）
        # 构建概率管理器配置字典（使用已提取的实例变量）
        probability_config = {
            "enable_dynamic_reply_probability": self.enable_dynamic_reply_probability,
            "reply_time_periods": self.reply_time_periods,
            "reply_time_transition_minutes": self.reply_time_transition_minutes,
            "reply_time_min_factor": self.reply_time_min_factor,
            "reply_time_max_factor": self.reply_time_max_factor,
            "reply_time_use_smooth_curve": self.reply_time_use_smooth_curve,
            "enable_probability_hard_limit": self.enable_probability_hard_limit,
            "probability_min_limit": self.probability_min_limit,
            "probability_max_limit": self.probability_max_limit,
        }
        ProbabilityManager.initialize(probability_config)

        # 🆕 v1.2.0: 初始化拟人增强模式管理器
        self.humanize_mode_enabled = self.enable_humanize_mode
        if self.humanize_mode_enabled:
            # 构建拟人增强模式的配置（使用已提取的实例变量）
            humanize_config = {
                "silent_mode_threshold": self.humanize_silent_mode_threshold,
                "silent_mode_max_duration": self.humanize_silent_max_duration,
                "silent_mode_max_messages": self.humanize_silent_max_messages,
                "enable_dynamic_threshold": self.humanize_enable_dynamic_threshold,
                "base_message_threshold": self.humanize_base_message_threshold,
                "max_message_threshold": self.humanize_max_message_threshold,
                "include_decision_history_in_prompt": self.humanize_include_decision_history,
                "interest_keywords": self.humanize_interest_keywords,
                "interest_boost_probability": self.humanize_interest_boost_probability,
            }
            HumanizeModeManager.initialize(humanize_config)
            logger.info("🎭 拟人增强模式已启用")

        # 初始化消息缓存（用于保存"通过筛选但未回复"的消息）
        # 格式: {chat_id: [{"role": "user", "content": "消息内容", "timestamp": 时间戳}]}
        self.pending_messages_cache = {}

        # 标记本插件正在处理的消息（用于after_message_sent筛选）
        # 🔧 修复：使用message_id作为键，避免同一会话中多条消息并发时标记冲突
        # 格式: {message_id: chat_id}
        self.processing_sessions = {}
        
        # 🔧 并发保护：存储消息缓存快照，供 after_message_sent 使用
        # 格式: {message_id: cached_message_dict}
        self._message_cache_snapshots = {}
        
        # 🆕 主动对话正在处理的会话标记（用于普通对话和主动对话之间的并发保护）
        # 格式: {chat_id: timestamp}，记录主动对话开始处理的时间
        # 普通对话在清空缓存前会检查此标记，避免与主动对话冲突
        self.proactive_processing_sessions = {}

        # 标记被识别为指令的消息（用于跨处理器通信）
        # 格式: {message_id: timestamp}，定期清理超过10秒的旧记录
        self.command_messages = {}

        # 🆕 最近发送的回复缓存（用于去重检查）
        # 格式: {chat_id: [{"content": "回复内容", "timestamp": 时间戳}]}
        # 最多保留最近5条回复，超过30分钟的自动清理
        self.recent_replies_cache = {}
        self.raw_reply_cache = {}
        
        # 🔧 重复消息拦截标记（用于 after_message_sent 判断是否跳过AI消息保存）
        # 格式: {message_id: True}
        # 当消息被重复检测拦截时，添加到此字典，after_message_sent 会跳过AI消息保存但继续保存用户消息
        self._duplicate_blocked_messages = {}

        # ========== v1.0.2 新增功能初始化 ==========

        # 1. 打字错误生成器
        self.typo_enabled = self.enable_typo_generator
        if self.typo_enabled:
            # 构建打字错误生成器配置字典（使用已提取的实例变量）
            typo_config = {
                "typo_homophones": self.typo_homophones,
                "typo_min_text_length": self.typo_min_text_length,
                "typo_min_chinese_chars": self.typo_min_chinese_chars,
                "typo_min_message_length": self.typo_min_message_length,
                "typo_min_count": self.typo_min_count,
                "typo_max_count": self.typo_max_count,
            }
            self.typo_generator = TypoGenerator(
                error_rate=self.typo_error_rate, config=typo_config
            )
        else:
            self.typo_generator = None

        # 2. 情绪追踪系统
        self.mood_enabled = self.enable_mood_system
        if self.mood_enabled:
            # 构建情绪追踪系统配置字典（使用已提取的实例变量）
            mood_config = {
                "enable_negation_detection": self.enable_negation_detection,
                "negation_words": self.negation_words,
                "negation_check_range": self.negation_check_range,
                "mood_keywords": self.mood_keywords,
                "mood_decay_time": self.mood_decay_time,
                "mood_cleanup_threshold": self.mood_cleanup_threshold,
                "mood_cleanup_interval": self.mood_cleanup_interval,
            }
            self.mood_tracker = MoodTracker(mood_config)
        else:
            self.mood_tracker = None

        # 3. 频率动态调整器
        self.frequency_adjuster_enabled = self.enable_frequency_adjuster
        if self.frequency_adjuster_enabled:
            # 构建频率调整器配置字典（使用已提取的实例变量）
            frequency_config = {
                "frequency_min_message_count": self.frequency_min_message_count,
                "frequency_decrease_factor": self.frequency_decrease_factor,
                "frequency_increase_factor": self.frequency_increase_factor,
                "frequency_min_probability": self.frequency_min_probability,
                "frequency_max_probability": self.frequency_max_probability,
                "frequency_analysis_message_count": self.frequency_analysis_message_count,
                "frequency_analysis_timeout": self.frequency_analysis_timeout,
                "frequency_adjust_duration": self.frequency_adjust_duration,
                # 动态时间段配置（频率调整器也需要）
                "enable_dynamic_reply_probability": self.enable_dynamic_reply_probability,
                "reply_time_periods": self.reply_time_periods,
                "reply_time_transition_minutes": self.reply_time_transition_minutes,
                "reply_time_min_factor": self.reply_time_min_factor,
                "reply_time_max_factor": self.reply_time_max_factor,
                "reply_time_use_smooth_curve": self.reply_time_use_smooth_curve,
            }
            self.frequency_adjuster = FrequencyAdjuster(context, frequency_config)
            # 设置检查间隔（使用已提取的实例变量）
            FrequencyAdjuster.CHECK_INTERVAL = self.frequency_check_interval
        else:
            self.frequency_adjuster = None

        # 4. 回复延迟模拟器
        self.typing_simulator_enabled = self.enable_typing_simulator
        if self.typing_simulator_enabled:
            self.typing_simulator = TypingSimulator(
                typing_speed=self.typing_speed,
                max_delay=self.typing_max_delay,
            )
        else:
            self.typing_simulator = None

        # ========== 注意力机制增强配置 ==========
        # 构建注意力管理器配置字典（使用已提取的实例变量）
        attention_config = {
            "enable_attention_emotion_detection": self.enable_attention_emotion_detection,
            "attention_emotion_keywords": self.attention_emotion_keywords,
            "attention_enable_negation": self.attention_enable_negation,
            "attention_negation_words": self.attention_negation_words,
            "attention_negation_check_range": self.attention_negation_check_range,
            "attention_positive_emotion_boost": self.attention_positive_emotion_boost,
            "attention_negative_emotion_decrease": self.attention_negative_emotion_decrease,
            "enable_attention_spillover": self.enable_attention_spillover,
            "attention_spillover_ratio": self.attention_spillover_ratio,
            "attention_spillover_decay_halflife": self.attention_spillover_decay_halflife,
            "attention_spillover_min_trigger": self.attention_spillover_min_trigger,
            # 🆕 对话疲劳机制配置
            "enable_conversation_fatigue": self.enable_conversation_fatigue,
            "fatigue_reset_threshold": self.fatigue_reset_threshold,
            "fatigue_threshold_light": self.fatigue_threshold_light,
            "fatigue_threshold_medium": self.fatigue_threshold_medium,
            "fatigue_threshold_heavy": self.fatigue_threshold_heavy,
            "fatigue_probability_decrease_light": self.fatigue_probability_decrease_light,
            "fatigue_probability_decrease_medium": self.fatigue_probability_decrease_medium,
            "fatigue_probability_decrease_heavy": self.fatigue_probability_decrease_heavy,
        }
        # 初始化注意力管理器（持久化存储和情感检测配置
        AttentionManager.initialize(str(data_dir), attention_config)

        # 应用自定义配置到AttentionManager（使用已提取的实例变量）
        attention_enabled = self.enable_attention_mechanism
        if attention_enabled:
            # 设置最大追踪用户数
            AttentionManager.MAX_TRACKED_USERS = self.attention_max_tracked_users
            # 设置注意力衰减半衰期
            AttentionManager.ATTENTION_DECAY_HALFLIFE = self.attention_decay_halflife
            # 设置情绪衰减半衰期
            AttentionManager.EMOTION_DECAY_HALFLIFE = self.emotion_decay_halflife

        # ========== 🆕 v1.2.1 注意力冷却机制初始化 ==========
        # 构建冷却管理器配置字典（使用已提取的实例变量）
        cooldown_config = {
            "cooldown_max_duration": self.cooldown_max_duration,
            "cooldown_trigger_threshold": self.cooldown_trigger_threshold,
            "cooldown_attention_decrease": self.cooldown_attention_decrease,
        }
        # 初始化冷却管理器（持久化存储和配置参数）
        self.cooldown_enabled = self.enable_attention_cooldown
        if self.cooldown_enabled and attention_enabled:
            CooldownManager.initialize(str(data_dir), cooldown_config)
            logger.info("🧊 注意力冷却机制已初始化")
        elif self.cooldown_enabled and not attention_enabled:
            logger.info("⚠️ 注意力冷却机制需要启用注意力机制才能生效")
            self.cooldown_enabled = False

        # ========== 🆕 v1.1.0 主动对话功能初始化 ==========
        self.proactive_enabled = self.enable_proactive_chat
        if self.proactive_enabled:
            # 初始化主动对话管理器（持久化存储）
            ProactiveChatManager.initialize(str(data_dir))
            logger.info("主动对话管理器已初始化")

        # 🆕 v1.2.0: 初始化主动对话回复用户追踪器（无论主动对话是否启用都需要初始化）
        self._proactive_reply_users = {}

        # ========== 🆕 回复后戳一戳功能初始化 ==========
        self.poke_after_reply_enabled = self.enable_poke_after_reply
        if self.poke_after_reply_enabled:
            # 使用已提取的实例变量（poke_after_reply_probability 和 poke_after_reply_delay 已在配置提取区块中设置）
            logger.info("回复后戳一戳功能已启用（仅支持QQ平台+aiocqhttp协议）")

        # ========== 🆕 收到戳一戳后反戳配置 ==========
        # 配置为概率值：[0,1]；0=禁用，1=必定反戳并丢弃本插件处理
        raw_reverse_prob = self.poke_reverse_on_poke_probability_raw
        try:
            reverse_prob = float(raw_reverse_prob)
        except (TypeError, ValueError):
            reverse_prob = 0.0
        # 夹紧到[0,1]
        if reverse_prob < 0:
            reverse_prob = 0.0
        if reverse_prob > 1:
            reverse_prob = 1.0
        self.poke_reverse_on_poke_probability = reverse_prob
        if self.poke_reverse_on_poke_probability > 0:
            logger.info(
                f"收到戳一戳后反戳功能启用，概率={self.poke_reverse_on_poke_probability} (原始={raw_reverse_prob})"
            )

        # ========== 🆕 AI戳后追踪提示功能 ==========
        self.poke_trace_enabled = self.enable_poke_trace_prompt
        # poke_trace_max_tracked_users 和 poke_trace_ttl_seconds 已在配置提取区块中设置
        self.poke_trace_records = {}

        # ========== 🆕 戳一戳功能群聊白名单 ==========
        # poke_enabled_groups 已在配置提取区块中设置
        # 转换为字符串列表，确保统一格式
        self.poke_enabled_groups = [str(g) for g in self.poke_enabled_groups]
        if self.poke_enabled_groups:
            logger.info(
                f"戳一戳功能群聊白名单已启用: {self.poke_enabled_groups} (仅这些群启用)"
            )
        else:
            logger.info("戳一戳功能群聊白名单: 未设置 (所有群启用)")

        # ========== 🆕 忽略@全体成员消息功能 ==========
        self.ignore_at_all_enabled = self.enable_ignore_at_all
        if self.ignore_at_all_enabled:
            logger.info("@全体成员消息过滤功能已启用（插件内部额外过滤）")

        # ========== 日志输出 ==========
        logger.info("=" * 50)
        logger.info("群聊增强插件已加载 - v1.1.2")
        logger.info(
            f"🔘 群聊功能总开关: {'✓ 已启用' if self.enable_group_chat else '✗ 已禁用'}"
        )
        logger.info(f"初始读空气概率: {self.initial_probability}")
        logger.info(f"回复后概率: {self.after_reply_probability}")
        logger.info(f"概率提升持续时间: {self.probability_duration}秒")
        logger.info(f"启用的群组: {self.enabled_groups} (留空=全部)")
        logger.info(f"详细日志模式: {'开启' if self.debug_mode else '关闭'}")

        # 注意力机制配置（增强版）
        logger.info(f"增强注意力机制: {'✓ 开启' if attention_enabled else '✗ 关闭'}")
        if attention_enabled:
            logger.info(f"  - 提升参考概率: {self.attention_increased_probability}")
            logger.info(f"  - 降低参考概率: {self.attention_decreased_probability}")
            logger.info(f"  - 数据清理周期: {self.attention_duration}秒")
            logger.info(f"  - 最大追踪用户: {self.attention_max_tracked_users}人")
            logger.info(f"  - 注意力半衰期: {self.attention_decay_halflife}秒")
            logger.info(f"  - 情绪半衰期: {self.emotion_decay_halflife}秒")

        # v1.0.2 新功能状态
        logger.info("\n【v1.0.2 开始的新功能】")
        logger.info(
            f"打字错误生成器: {'✓ 已启用' if self.typo_enabled else '✗ 已禁用'}"
        )
        logger.info(f"情绪追踪系统: {'✓ 已启用' if self.mood_enabled else '✗ 已禁用'}")
        logger.info(
            f"频率动态调整: {'✓ 已启用' if self.frequency_adjuster_enabled else '✗ 已禁用'}"
        )
        if self.frequency_adjuster_enabled:
            logger.info(f"  - 检查间隔: {self.frequency_check_interval} 秒")
            logger.info(f"  - 最小消息数: {self.frequency_min_message_count} 条")
            logger.info(f"  - 分析消息数: {self.frequency_analysis_message_count} 条")
            logger.info(f"  - 分析超时: {self.frequency_analysis_timeout} 秒")
            logger.info(f"  - 调整持续: {self.frequency_adjust_duration} 秒")
            logger.info(
                f"  - 调整系数: 过高↓{self.frequency_decrease_factor}({(1 - self.frequency_decrease_factor) * 100:.0f}%), "
                f"过低↑{self.frequency_increase_factor}({(self.frequency_increase_factor - 1) * 100:.0f}%)"
            )
            logger.info(
                f"  - 概率范围: {self.frequency_min_probability:.2f} - "
                f"{self.frequency_max_probability:.2f}"
            )
        logger.info(
            f"回复延迟模拟: {'✓ 已启用' if self.typing_simulator_enabled else '✗ 已禁用'}"
        )

        # v1.0.7 新功能状态
        logger.info("\n【v1.0.7 新增功能】")
        blacklist_enabled = self.enable_user_blacklist
        blacklist_count = len(self.blacklist_user_ids)
        logger.info(f"用户黑名单: {'✓ 已启用' if blacklist_enabled else '✗ 已禁用'}")
        if blacklist_enabled and blacklist_count > 0:
            logger.info(f"  - 黑名单用户数: {blacklist_count} 人")
        logger.info(
            f"情绪否定词检测: {'✓ 已启用' if self.enable_negation_detection else '✗ 已禁用'}"
        )

        # 🆕 v1.1.0 新功能状态
        logger.info("\n【🆕 v1.1.0 新增功能】")
        logger.info(
            f"主动对话功能: {'✨ 已启用' if self.proactive_enabled else '✗ 已禁用'}"
        )
        if self.proactive_enabled:
            # 白名单配置
            if self.proactive_enabled_groups and len(self.proactive_enabled_groups) > 0:
                logger.info(
                    f"  - 启用群聊白名单: {self.proactive_enabled_groups} (仅这些群启用)"
                )
            else:
                logger.info(f"  - 启用群聊白名单: [] (所有群启用)")

            logger.info(f"  - 沉默阈值: {self.proactive_silence_threshold} 秒")
            logger.info(f"  - 触发概率: {self.proactive_probability}")
            logger.info(f"  - 检查间隔: {self.proactive_check_interval} 秒")
            logger.info(
                f"  - 用户活跃度检测: {'✓' if self.proactive_require_user_activity else '✗'}"
            )
            logger.info(
                f"  - 临时概率提升: {self.proactive_temp_boost_probability} (持续{self.proactive_temp_boost_duration}秒)"
            )
            if self.proactive_enable_quiet_time:
                logger.info(
                    f"  - 禁用时段: {self.proactive_quiet_start}-{self.proactive_quiet_end}"
                )

            # 🆕 v1.2.0 评分系统状态
            logger.info(
                f"  - 智能自适应主动对话: {'✨ 已启用' if self.enable_adaptive_proactive else '✗ 已禁用'}"
            )
            if self.enable_adaptive_proactive:
                logger.info(
                    f"    · 评分范围: {self.interaction_score_min}-{self.interaction_score_max}分"
                )
                logger.info(f"    · 成功互动加分: +{self.score_increase_on_success}分")
                logger.info(f"    · 失败互动扣分: -{self.score_decrease_on_fail}分")

        # 🆕 v1.1.0 新功能状态 - 动态时间段概率调整
        logger.info("\n【🆕 v1.1.0 新增功能 - 动态时间段概率调整】")

        # 模式1：普通回复动态调整
        logger.info(
            f"模式1-普通回复动态调整: {'✨ 已启用' if self.enable_dynamic_reply_probability else '✗ 已禁用'}"
        )
        if self.enable_dynamic_reply_probability:
            try:
                periods = TimePeriodManager.parse_time_periods(self.reply_time_periods)
                logger.info(f"  - 已配置 {len(periods)} 个时间段")
                for period in periods[:3]:  # 只显示前3个
                    name = period.get("name", "未命名")
                    start = period.get("start", "")
                    end = period.get("end", "")
                    factor = period.get("factor", 1.0)
                    logger.info(f"    · {name}: {start}-{end} (系数{factor:.2f})")
                if len(periods) > 3:
                    logger.info(f"    · ...还有{len(periods) - 3}个时间段")
            except Exception as e:
                logger.warning(f"  - 解析时间段配置失败: {e}")

            logger.info(f"  - 过渡时长: {self.reply_time_transition_minutes} 分钟")
            logger.info(
                f"  - 系数范围: {self.reply_time_min_factor:.2f} - {self.reply_time_max_factor:.2f}"
            )
            logger.info(
                f"  - 平滑曲线: {'✓ 启用' if self.reply_time_use_smooth_curve else '✗ 禁用'}"
            )

        # 模式2：主动对话动态调整
        logger.info(
            f"模式2-主动对话动态调整: {'✨ 已启用' if self.enable_dynamic_proactive_probability else '✗ 已禁用'}"
        )
        if self.enable_dynamic_proactive_probability:
            try:
                periods = TimePeriodManager.parse_time_periods(
                    self.proactive_time_periods
                )
                logger.info(f"  - 已配置 {len(periods)} 个时间段")
                for period in periods[:3]:  # 只显示前3个
                    name = period.get("name", "未命名")
                    start = period.get("start", "")
                    end = period.get("end", "")
                    factor = period.get("factor", 1.0)
                    logger.info(f"    · {name}: {start}-{end} (系数{factor:.2f})")
                if len(periods) > 3:
                    logger.info(f"    · ...还有{len(periods) - 3}个时间段")
            except Exception as e:
                logger.warning(f"  - 解析时间段配置失败: {e}")

            logger.info(f"  - 过渡时长: {self.proactive_time_transition_minutes} 分钟")
            logger.info(
                f"  - 系数范围: {self.proactive_time_min_factor:.2f} - {self.proactive_time_max_factor:.2f}"
            )
            logger.info(
                f"  - 平滑曲线: {'✓ 启用' if self.proactive_time_use_smooth_curve else '✗ 禁用'}"
            )

            # 优先级提醒
            if self.proactive_enabled and self.proactive_enable_quiet_time:
                logger.info(f"  - ⚠️ 注意: '禁用时段'优先级高于动态调整")

        logger.info("=" * 50)

        if self.debug_mode:
            logger.info("【调试模式】配置详情:")
            logger.info(f"  - 读空气AI提供商: {self.decision_ai_provider_id or '默认'}")
            logger.info(f"  - 包含时间戳: {self.include_timestamp}")
            logger.info(f"  - 包含发送者信息: {self.include_sender_info}")
            logger.info(f"  - 最大上下文消息数: {self.max_context_messages}")
            logger.info(f"  - 📦 消息缓存最大条数: {self.pending_cache_max_count}")
            logger.info(f"  - 📦 消息缓存过期时间: {self.pending_cache_ttl_seconds}秒")
            logger.info(f"  - 启用图片处理: {self.enable_image_processing}")
            logger.info(f"  - 启用记忆植入: {self.enable_memory_injection}")
            logger.info(f"  - 启用工具提醒: {self.enable_tools_reminder}")

        # ========== 🆕 v1.2.0 AI回复内容过滤器初始化 ==========
        self.content_filter = ContentFilterManager(
            enable_output_filter=self.enable_output_content_filter,
            output_filter_rules=self.output_content_filter_rules,
            enable_save_filter=self.enable_save_content_filter,
            save_filter_rules=self.save_content_filter_rules,
            debug_mode=self.debug_mode,
        )

        # 日志输出内容过滤器状态
        output_filter_enabled = self.enable_output_content_filter
        save_filter_enabled = self.enable_save_content_filter
        if output_filter_enabled or save_filter_enabled:
            logger.info("\n【🆕 v1.2.0 AI回复内容过滤】")
            logger.info(
                f"输出内容过滤: {'✓ 已启用' if output_filter_enabled else '✗ 已禁用'}"
            )
            if output_filter_enabled:
                output_rules = self.output_content_filter_rules
                logger.info(f"  - 过滤规则数: {len(output_rules)} 条")
            logger.info(
                f"保存内容过滤: {'✓ 已启用' if save_filter_enabled else '✗ 已禁用'}"
            )
            if save_filter_enabled:
                save_rules = self.save_content_filter_rules
                logger.info(f"  - 过滤规则数: {len(save_rules)} 条")

    def _build_proactive_config(self) -> dict:
        """
        构建主动对话管理器所需的配置字典（使用已提取的实例变量）

        Returns:
            主动对话配置字典
        """
        return {
            # 吐槽系统配置
            "enable_complaint_system": self.enable_complaint_system,
            "complaint_trigger_threshold": self.complaint_trigger_threshold,
            "complaint_level_light": self.complaint_level_light,
            "complaint_level_medium": self.complaint_level_medium,
            "complaint_level_strong": self.complaint_level_strong,
            "complaint_probability_light": self.complaint_probability_light,
            "complaint_probability_medium": self.complaint_probability_medium,
            "complaint_probability_strong": self.complaint_probability_strong,
            "complaint_max_accumulation": self.complaint_max_accumulation,
            "complaint_decay_on_success": self.complaint_decay_on_success,
            "complaint_decay_check_interval": self.complaint_decay_check_interval,
            "complaint_decay_no_failure_threshold": self.complaint_decay_no_failure_threshold,
            "complaint_decay_amount": self.complaint_decay_amount,
            # 自适应主动对话配置
            "enable_adaptive_proactive": self.enable_adaptive_proactive,
            "interaction_score_min": self.interaction_score_min,
            "interaction_score_max": self.interaction_score_max,
            "score_increase_on_success": self.score_increase_on_success,
            "score_decrease_on_fail": self.score_decrease_on_fail,
            "score_quick_reply_bonus": self.score_quick_reply_bonus,
            "score_multi_user_bonus": self.score_multi_user_bonus,
            "score_streak_bonus": self.score_streak_bonus,
            "score_revival_bonus": self.score_revival_bonus,
            "interaction_score_decay_rate": self.interaction_score_decay_rate,
            # 主动对话基础配置
            "proactive_enabled_groups": self.proactive_enabled_groups,
            "proactive_silence_threshold": self.proactive_silence_threshold,
            "proactive_cooldown_duration": self.proactive_cooldown_duration,
            "proactive_max_consecutive_failures": self.proactive_max_consecutive_failures,
            "proactive_failure_threshold_perturbation": self.proactive_failure_threshold_perturbation,
            "proactive_failure_sequence_probability": self.proactive_failure_sequence_probability,
            "proactive_require_user_activity": self.proactive_require_user_activity,
            "proactive_min_user_messages": self.proactive_min_user_messages,
            "proactive_probability": self.proactive_probability,
            "proactive_user_activity_window": self.proactive_user_activity_window,
            # 时间段控制配置
            "proactive_enable_quiet_time": self.proactive_enable_quiet_time,
            "proactive_quiet_start": self.proactive_quiet_start,
            "proactive_quiet_end": self.proactive_quiet_end,
            "proactive_transition_minutes": self.proactive_transition_minutes,
            "enable_dynamic_proactive_probability": self.enable_dynamic_proactive_probability,
            "proactive_time_periods": self.proactive_time_periods,
            "proactive_time_transition_minutes": self.proactive_time_transition_minutes,
            "proactive_time_min_factor": self.proactive_time_min_factor,
            "proactive_time_max_factor": self.proactive_time_max_factor,
            "proactive_time_use_smooth_curve": self.proactive_time_use_smooth_curve,
            "proactive_check_interval": self.proactive_check_interval,
            "proactive_temp_boost_probability": self.proactive_temp_boost_probability,
            "proactive_temp_boost_duration": self.proactive_temp_boost_duration,
            # 提示词配置
            "proactive_prompt": self.proactive_prompt,
            "proactive_retry_prompt": self.proactive_retry_prompt,
            "proactive_generation_timeout_warning": self.proactive_generation_timeout_warning,
            "proactive_reply_context_prompt": self.proactive_reply_context_prompt,
            # 注意力感知配置
            "enable_attention_mechanism": self.enable_attention_mechanism,
            "proactive_use_attention": self.proactive_use_attention,
            "proactive_attention_reference_probability": self.proactive_attention_reference_probability,
            "proactive_attention_rank_weights": self.proactive_attention_rank_weights,
            "proactive_attention_max_selected_users": self.proactive_attention_max_selected_users,
            "proactive_focus_last_user_probability": self.proactive_focus_last_user_probability,
            # 上下文和消息格式配置
            "max_context_messages": self.max_context_messages,
            "include_timestamp": self.include_timestamp,
            "include_sender_info": self.include_sender_info,
            # 记忆注入配置
            "enable_memory_injection": self.enable_memory_injection,
            "memory_plugin_mode": self.memory_plugin_mode,
            "livingmemory_top_k": self.livingmemory_top_k,
            # 工具提醒配置
            "enable_tools_reminder": self.enable_tools_reminder,
            # 📦 消息缓存配置（用于主动对话读取缓存时过滤过期消息）
            "pending_cache_max_count": self.pending_cache_max_count,
            "pending_cache_ttl_seconds": self.pending_cache_ttl_seconds,
            # 🔄 AI重复消息拦截配置
            "enable_duplicate_filter": self.enable_duplicate_filter,
            "duplicate_filter_check_count": self.duplicate_filter_check_count,
            "enable_duplicate_time_limit": self.enable_duplicate_time_limit,
            "duplicate_filter_time_limit": self.duplicate_filter_time_limit,
            # 🆕 v1.2.0: AI回复内容过滤配置（传递给主动对话管理器）
            "enable_output_content_filter": self.enable_output_content_filter,
            "output_content_filter_rules": self.output_content_filter_rules,
            "enable_save_content_filter": self.enable_save_content_filter,
            "save_content_filter_rules": self.save_content_filter_rules,
        }

    async def initialize(self):
        """
        🆕 v1.1.0: 插件激活时调用

        启动主动对话功能的后台任务
        """
        self.session = aiohttp.ClientSession()
        # 🔘 仅当群聊功能总开关开启时，才启动主动对话后台任务
        if self.enable_group_chat and self.proactive_enabled:
            try:
                # 构建主动对话配置字典（使用已提取的实例变量）
                proactive_config = self._build_proactive_config()
                # 启动主动对话后台任务
                await ProactiveChatManager.start_background_task(
                    self.context,
                    proactive_config,  # 传递配置字典
                    self,  # 传递插件实例（用于发送消息等）
                )
                logger.info("✅ [主动对话] 后台任务已启动")
            except Exception as e:
                logger.error(f"[主动对话] 启动后台任务失败: {e}", exc_info=True)
        elif not self.enable_group_chat and self.proactive_enabled:
            logger.info("⏸️ [主动对话] 群聊功能总开关已关闭，跳过启动主动对话后台任务")

    async def terminate(self):
        """
        🆕 v1.1.0: 插件禁用/重载时调用

        停止主动对话功能的后台任务并保存状态
        """
        if self.proactive_enabled:
            try:
                await ProactiveChatManager.stop_background_task()
                logger.info("⏹️ [主动对话] 后台任务已停止，状态已保存")
            except Exception as e:
                logger.error(f"[主动对话] 停止后台任务失败: {e}", exc_info=True)
        if hasattr(self, "session"):
            await self.session.close()

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        restart_umo = self.config.get("restart_umo")
        platform_id = self.config.get("platform_id")
        restart_start_ts = self.config.get("restart_start_ts")
        if not restart_umo or not platform_id or not restart_start_ts:
            return

        platform = self.context.get_platform_inst(platform_id)
        if not isinstance(platform, AiocqhttpAdapter):
            logger.warning("未找到 aiocqhttp 平台实例，跳过重启提示")
            # 发送错误提示给用户
            try:
                await self.context.send_message(
                    session=restart_umo,
                    message_chain=MessageChain(
                        [
                            Plain(
                                f"⚠️ 重启完成提示发送失败：当前平台不支持重启提示功能（仅支持aiocqhttp平台）"
                            )
                        ]
                    ),
                )
            except Exception as e:
                logger.error(f"发送重启失败提示时出错: {e}")
            # 清理配置
            self.config["restart_umo"] = ""
            self.config["restart_start_ts"] = 0
            self.config.save_config()
            return
        client = platform.get_client()
        if not client:
            logger.warning("未找到 CQHttp 实例，跳过重启提示")
            # 发送错误提示给用户
            try:
                await self.context.send_message(
                    session=restart_umo,
                    message_chain=MessageChain(
                        [Plain(f"⚠️ 重启完成提示发送失败：未找到CQHttp客户端实例")]
                    ),
                )
            except Exception as e:
                logger.error(f"发送重启失败提示时出错: {e}")
            # 清理配置
            self.config["restart_umo"] = ""
            self.config["restart_start_ts"] = 0
            self.config.save_config()
            return

        ws_connected = asyncio.Event()

        @client.on_websocket_connection
        def _(_):
            ws_connected.set()

        try:
            await asyncio.wait_for(ws_connected.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning(
                "等待 aiocqhttp WebSocket 连接超时，可能未能发送重启完成提示。"
            )

        elapsed = time.time() - float(restart_start_ts)

        await self.context.send_message(
            session=restart_umo,
            message_chain=MessageChain(
                [Plain(f"AstrBot重启完成（耗时{elapsed:.2f}秒）")]
            ),
        )

        self.config["restart_umo"] = ""
        self.config["restart_start_ts"] = 0
        self.config.save_config()

    async def _get_auth_token(self):
        """获取认证token"""
        login_url = f"http://{self.host}:{self.port}/api/auth/login"
        login_data = {
            "username": self.dbc["username"],
            "password": self.dbc["password"],
        }
        async with self.session.post(login_url, json=login_data) as response:
            if response.status == 200:
                data = await response.json()
                if data and data.get("status") == "ok" and "data" in data:
                    return data["data"]["token"]
                else:
                    raise Exception(f"登录响应格式错误: {data}")
            else:
                text = await response.text()
                raise Exception(f"登录失败，状态码: {response.status}, 响应: {text}")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize - 1)
    async def command_filter_handler(self, event: AstrMessageEvent):
        """
        指令过滤处理器（高优先级）

        在所有其他处理器之前执行，检测并过滤指令消息。
        如果检测到指令，标记该消息，让本插件的其他处理器跳过。

        优先级: sys.maxsize-1 (超高优先级，确保最先执行)

        注意：使用 NotPokeMessageFilter 在 filter 阶段就过滤掉戳一戳消息，
        确保戳一戳消息不会激活此 handler，从而能正常传播到其他插件。
        """
        try:
            # 🔘 检查群聊功能总开关
            if not self.enable_group_chat:
                return

            # 只处理群消息
            if event.is_private_chat():
                return

            # 检查群组是否启用插件
            if not self._is_enabled(event):
                return

            # 🔧 修复：定期清理过期的指令标记（无论是否检测到新指令，避免内存泄漏）
            current_time = time.time()
            expired_ids = [
                mid
                for mid, timestamp in self.command_messages.items()
                if current_time - timestamp > 10
            ]
            for mid in expired_ids:
                del self.command_messages[mid]

            # 检测是否为指令消息
            if self._is_command_message(event):
                # 生成消息唯一标识（用于跨处理器通信）
                msg_id = self._get_message_id(event)
                self.command_messages[msg_id] = (
                    current_time  # 使用已计算的 current_time
                )

                # 检测到指令，标记后直接返回（不调用 stop_event，让其他插件处理）
                return
        except Exception as e:
            # 捕获所有异常，避免影响其他插件的事件处理
            logger.error(f"[指令过滤] 处理消息时发生错误: {e}", exc_info=True)
            # 出错时直接返回，不影响其他handler的执行
            return

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """
        群消息事件监听

        采用监听模式，不影响其他插件和官方功能

        Args:
            event: 消息事件对象
        """
        try:
            # 🔘 检查群聊功能总开关
            if not self.enable_group_chat:
                return

            # 检查是否被高优先级处理器标记为指令消息
            msg_id = self._get_message_id(event)
            if msg_id in self.command_messages:
                # 这条消息已被识别为指令，跳过处理
                if self.debug_mode:
                    logger.info("消息已被标记为指令，跳过处理")
                return

            # 【🆕】检测是否应该忽略@全体成员消息
            if self._should_ignore_at_all(event):
                # 消息包含@全体成员，根据配置忽略处理
                # 不阻止消息传播，其他插件仍可处理此消息
                if self.debug_mode:
                    logger.info("[@全体成员检测] 消息包含@全体成员，本插件跳过处理")
                return

            # 【v1.0.7】检测用户是否在黑名单中
            if self._is_user_blacklisted(event):
                # 用户在黑名单中，本插件直接跳过处理
                return

            # 【v1.0.9新增】过滤伪造的戳一戳文本标识符
            # 防止用户手动输入"[Poke:poke]"来伪造戳一戳消息
            message_str = event.get_message_str()
            if MessageCleaner.is_only_poke_marker(message_str):
                # 消息只包含"[Poke:poke]"标识符，直接丢弃
                if self.debug_mode:
                    logger.info(
                        "【戳一戳标识符过滤】消息只包含[Poke:poke]标识符，跳过处理"
                    )
                return

            # 【v1.0.9新增】检测是否应该忽略@他人的消息
            if self._should_ignore_at_others(event):
                # 消息中@了其他人（根据配置的模式），本插件跳过处理
                # 不阻止消息传播，其他插件仍可处理此消息
                if self.debug_mode:
                    logger.info("[@他人检测] 消息符合忽略条件，本插件跳过处理")
                return

            # 【v1.0.9新增】检测是否为戳一戳消息
            poke_result = self._check_poke_message(event)
            if poke_result.get("is_poke") and poke_result.get("should_ignore"):
                # 戳一戳消息但根据配置应该忽略，本插件跳过处理
                # 不阻止消息传播，其他插件（如astrbot_plugin_llm_poke）仍可处理此消息
                if self.debug_mode:
                    logger.info("【戳一戳检测】消息符合忽略条件，本插件跳过处理")
                return

            # 处理群消息
            async for result in self._process_message(event):
                yield result
        except Exception as e:
            logger.error(f"处理群消息时发生错误: {e}", exc_info=True)

    async def restart_core(self):
        """
        发送重启请求,重启AstrBot,并记录重启信息
        """
        try:
            token = await self._get_auth_token()
            headers = {"Authorization": f"Bearer {token}"}
            async with self.session.post(self.restart_url, headers=headers) as response:
                if response.status == 200:
                    logger.info("系统重启请求已发送")
                else:
                    logger.error(f"重启请求失败，状态码: {response.status}")
                    raise RuntimeError(f"重启请求失败，状态码: {response.status}")
        except Exception as e:
            logger.error(f"发送重启请求时出错: {e}")
            raise e

    @filter.command("gcp_reset")
    async def gcp_reset(self, event: AstrMessageEvent):
        """
        检测并处理“插件重置指令”，重启AstrBot。

        触发条件：
        - 仅群聊有效（私聊直接忽略）
        - 插件对该群处于启用状态
        - 白名单检查通过（`plugin_gcp_reset_allowed_user_ids` 为空=允许所有用户）

        """
        try:
            # 群聊处理开关未启用则直接忽略
            if not self.enable_group_chat:
                return
            # 只处理群聊（规避私聊误触）
            if event.is_private_chat():
                return
            # 群未启用则直接忽略
            if not self._is_enabled(event):
                return
            # 需要能访问到原始消息链
            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "message"
            ):
                return
            components = event.message_obj.message
            if not components:
                return
            # 必须是“纯文本”消息，防止图片/引用等组件混入而误触
            if not all(isinstance(c, Plain) for c in components):
                return
            # 白名单：为空=允许所有用户；否则仅允许列表内用户
            whitelist = self.plugin_gcp_reset_allowed_user_ids
            allow_all = not whitelist or len(whitelist) == 0
            sender_id = str(event.get_sender_id())
            allowed = allow_all or (str(sender_id) in {str(x) for x in whitelist})
            if not allowed:
                # 不在白名单：按“已处理”返回，防止本条消息继续触发本插件的其他逻辑
                logger.info(
                    "【会话重置】用户 %s 未在白名单中，重置指令被忽略",
                    sender_id,
                )
                return
            # 通过全部校验：执行清理+热重载，并发送提示
            try:
                await self._reset_plugin_data_and_reload()
                # 成功提示
                try:
                    platform_name = event.get_platform_name()
                    chat_id = event.get_group_id()
                    session_str = f"{platform_name}:GroupMessage:{chat_id}"
                    notice = (
                        "【Group Chat Plus】插件重置指令处理结果：成功\n"
                        "已清空本插件缓存即将重启AstrBot。此提示不计入对话历史。"
                    )
                    yield event.plain_result(f"{notice}")
                    logger.info(f"{session_str}: {notice}")

                    self.config["platform_id"] = event.get_platform_id()
                    self.config["restart_umo"] = event.unified_msg_origin
                    self.config["restart_start_ts"] = time.time()
                    self.config.save_config()
                    logger.info(
                        "重启：已记录 platform_id、restart_umo 与 restart_start_ts，准备重启"
                    )
                    try:
                        await self.restart_core()
                    except Exception as e:
                        yield event.plain_result(f"重启失败：{e}")
                        logger.error(f"重启失败：{e}")
                except Exception:
                    pass
            except Exception:
                # 失败提示
                try:
                    platform_name = event.get_platform_name()
                    chat_id = event.get_group_id()
                    session_str = f"{platform_name}:GroupMessage:{chat_id}"
                    notice = (
                        "【Group Chat Plus】插件重置指令处理结果：失败\n"
                        "原因：执行重置时发生内部错误，请查看日志。此提示不计入对话历史。"
                    )
                    yield event.plain_result(f"{notice}")
                    logger.info(f"{session_str}: {notice}")
                except Exception:
                    pass
            return
        except Exception:
            return

    @filter.command("gcp_reset_here")
    async def gcp_reset_here(self, event: AstrMessageEvent):
        """
        检测并处理“会话级重置”指令，重启AstrBot：仅重置当前会话的本插件运行态与本地缓存。
        不影响 AstrBot 官方对话系统的历史，也不影响其他群或会话。

        """
        try:
            # 群聊处理开关未启用则直接忽略
            if not self.enable_group_chat:
                return
            # 仅群聊生效；为避免误触，私聊环境不处理该指令
            if event.is_private_chat():
                return
            # 若该群聊未启用插件，则直接忽略
            if not self._is_enabled(event):
                return
            # 需访问到底层消息结构（原始消息链）以便做"纯文本"判断
            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "message"
            ):
                return
            components = event.message_obj.message
            # 空消息（极少见）直接忽略
            if not components:
                return
            # 必须是“纯文本”消息（仅 Plain 组件），防止图片/引用等造成误触
            if not all(isinstance(c, Plain) for c in components):
                return
            # 白名单判定：空列表=允许所有用户；否则仅允许列表内用户
            whitelist = self.plugin_gcp_reset_here_allowed_user_ids
            allow_all = not whitelist or len(whitelist) == 0
            sender_id = str(event.get_sender_id())
            allowed = allow_all or (str(sender_id) in {str(x) for x in whitelist})
            # 若不被允许，按“已处理”返回，阻止该消息继续触发本插件其它逻辑
            if not allowed:
                logger.info(
                    "【会话重置】用户 %s 未在白名单中，重置指令被忽略",
                    sender_id,
                )
                return
            # 执行当前会话的数据重置并发送提示
            try:
                await self._reset_session_data(event)
                # 成功提示
                try:
                    platform_name = event.get_platform_name()
                    chat_id = event.get_group_id()
                    session_str = f"{platform_name}:GroupMessage:{chat_id}"
                    notice = (
                        "【Group Chat Plus】会话重置指令处理结果：成功\n"
                        "已清理当前会话的本插件缓存与运行态（不影响官方对话历史）,即将重启AstrBot。此提示不计入对话历史。"
                    )
                    yield event.plain_result(f"{notice}")
                    logger.info(f"{session_str}: {notice}")

                    self.config["platform_id"] = event.get_platform_id()
                    self.config["restart_umo"] = event.unified_msg_origin
                    self.config["restart_start_ts"] = time.time()
                    self.config.save_config()
                    logger.info(
                        "重启：已记录 platform_id、restart_umo 与 restart_start_ts，准备重启"
                    )
                    try:
                        await self.restart_core()
                    except Exception as e:
                        yield event.plain_result(f"重启失败：{e}")
                        logger.error(f"重启失败：{e}")
                except Exception:
                    pass
            except Exception:
                # 失败提示
                try:
                    platform_name = event.get_platform_name()
                    chat_id = event.get_group_id()
                    session_str = f"{platform_name}:GroupMessage:{chat_id}"
                    notice = (
                        "【Group Chat Plus】会话重置指令处理结果：失败\n"
                        "原因：执行重置时发生内部错误，请查看日志。此提示不计入对话历史。"
                    )
                    yield event.plain_result(f"{notice}")
                    logger.info(f"{session_str}: {notice}")
                except Exception:
                    pass
            return
        except Exception:
            # 兜底保护：异常时返回 ，不影响其他插件处理
            return

    async def _reset_session_data(self, event: AstrMessageEvent) -> None:
        """
        清理“当前会话”的本插件缓存与派生状态，不触碰 AstrBot 官方对话历史。

        主要包含：
        - 清空与该会话相关的内存缓存（待转存消息、处理中标记、去重缓存、戳一戳追踪等）
        - 重置该会话的概率/注意力/情绪等增强模块状态
        - 删除该会话在本插件数据目录中的持久化上下文文件
        - 持久化保存必要的状态变更
        """
        try:
            # 获取定位当前会话所需的关键维度
            platform_name = event.get_platform_name()
            is_private = event.is_private_chat()
            chat_id = event.get_group_id() if not is_private else event.get_sender_id()

            logger.info(
                "【会话重置】开始: platform=%s, 类型=%s, chat_id=%s",
                platform_name,
                "私聊" if is_private else "群聊",
                chat_id,
            )

            # —— 内存态缓存清理 ——
            try:
                # 待转存的消息缓存（本插件的自定义历史，用于不回复时保留上下文）
                if chat_id in self.pending_messages_cache:
                    cached_count = len(self.pending_messages_cache.get(chat_id, []))
                    del self.pending_messages_cache[chat_id]

                    logger.info(
                        "【会话重置】已清空待转存消息缓存 chat_id=%s, 清理条数=%s",
                        chat_id,
                        cached_count,
                    )
            except Exception:
                logger.warning("【会话重置】清空待转存消息缓存失败", exc_info=True)
            try:
                # 🔧 修复：处理中消息标记现在使用message_id作为键
                # 需要遍历并删除所有与该chat_id相关的条目
                keys_to_remove = [
                    msg_id
                    for msg_id, cid in self.processing_sessions.items()
                    if cid == chat_id
                ]
                for msg_id in keys_to_remove:
                    del self.processing_sessions[msg_id]

                if keys_to_remove:
                    logger.info(
                        "【会话重置】已移除处理中标记 chat_id=%s, 清理条数=%s",
                        chat_id,
                        len(keys_to_remove),
                    )
            except Exception:
                logger.warning("【会话重置】移除处理中标记失败", exc_info=True)
            try:
                # 最近回复缓存（用于去重检查，避免短时间内重复回复同内容）
                if chat_id in self.recent_replies_cache:
                    replies_cleared = len(self.recent_replies_cache.get(chat_id, []))
                    del self.recent_replies_cache[chat_id]

                    logger.info(
                        "【会话重置】已清空最近回复缓存 chat_id=%s, 清理条数=%s",
                        chat_id,
                        replies_cleared,
                    )
            except Exception:
                logger.warning("【会话重置】清空最近回复缓存失败", exc_info=True)
            try:
                # “回复后戳一戳”追踪记录（限定该会话）
                k = str(chat_id)
                if (
                    isinstance(getattr(self, "poke_trace_records", None), dict)
                    and k in self.poke_trace_records
                ):
                    del self.poke_trace_records[k]

                    logger.info("【会话重置】已移除戳一戳追踪记录 chat_id=%s", chat_id)
            except Exception:
                logger.warning("【会话重置】移除戳一戳追踪记录失败", exc_info=True)
            try:
                # 情绪系统：重置该会话的情绪基线
                if hasattr(self, "mood_tracker") and self.mood_tracker:
                    self.mood_tracker.reset_mood(str(chat_id))

                    logger.info("【会话重置】情绪状态已重置 chat_id=%s", chat_id)
            except Exception:
                logger.warning("【会话重置】重置情绪状态失败", exc_info=True)

            # —— 模块状态重置 ——
            try:
                # 概率管理：恢复该会话的触发概率到初始状态

                logger.info("【会话重置】开始重置概率状态 chat_id=%s", chat_id)
                await ProbabilityManager.reset_probability(
                    platform_name, is_private, chat_id
                )

                logger.info("【会话重置】概率状态重置完成 chat_id=%s", chat_id)
            except Exception:
                logger.warning("【会话重置】重置概率状态失败", exc_info=True)
            try:
                # 注意力管理：清空该会话的注意力与情绪权重

                logger.info("【会话重置】开始清空注意力状态 chat_id=%s", chat_id)
                await AttentionManager.clear_attention(
                    platform_name, is_private, chat_id
                )

                logger.info("【会话重置】注意力状态清空完成 chat_id=%s", chat_id)
            except Exception:
                logger.warning("【会话重置】清空注意力状态失败", exc_info=True)
            try:
                # 频率调整器：清理该会话的检查状态
                if hasattr(self, "frequency_adjuster") and self.frequency_adjuster:
                    chat_key = ProbabilityManager.get_chat_key(
                        platform_name, is_private, chat_id
                    )
                    if chat_key in self.frequency_adjuster.check_states:
                        del self.frequency_adjuster.check_states[chat_key]
                        logger.info(
                            "【会话重置】已清空频率检查状态 chat_key=%s",
                            chat_key,
                        )
            except Exception:
                logger.warning("【会话重置】清空频率检查状态失败", exc_info=True)
            try:
                # 主动对话：撤销临时概率提升并清理会话状态
                chat_key = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )
                try:
                    ProactiveChatManager.deactivate_temp_probability_boost(
                        chat_key, "会话重置"
                    )
                except Exception:
                    logger.warning(
                        "【会话重置】撤销临时概率提升失败 chat_key=%s",
                        chat_key,
                        exc_info=True,
                    )
                if (
                    hasattr(ProactiveChatManager, "_chat_states")
                    and chat_key in ProactiveChatManager._chat_states
                ):
                    del ProactiveChatManager._chat_states[chat_key]

                    logger.info(
                        "【会话重置】已移除主动对话状态 chat_key=%s",
                        chat_key,
                    )
                if (
                    hasattr(ProactiveChatManager, "_temp_probability_boost")
                    and chat_key in ProactiveChatManager._temp_probability_boost
                ):
                    del ProactiveChatManager._temp_probability_boost[chat_key]

                    logger.info(
                        "【会话重置】已清空临时概率提升状态 chat_key=%s",
                        chat_key,
                    )
                # 🆕 v1.2.0: 清理主动对话回复用户追踪器
                if (
                    hasattr(self, "_proactive_reply_users")
                    and chat_key in self._proactive_reply_users
                ):
                    del self._proactive_reply_users[chat_key]
                    logger.info(
                        "【会话重置】已清空主动对话回复追踪 chat_key=%s",
                        chat_key,
                    )

                if hasattr(ProactiveChatManager, "_save_states_to_disk"):
                    ProactiveChatManager._save_states_to_disk()

                    logger.info(
                        "【会话重置】主动对话状态已持久化 chat_key=%s", chat_key
                    )
            except Exception:
                logger.warning("【会话重置】清理主动对话状态失败", exc_info=True)

            # 🆕 v1.2.0: 拟人增强模式状态清理
            try:
                if self.humanize_mode_enabled:
                    chat_key = ProbabilityManager.get_chat_key(
                        platform_name, is_private, chat_id
                    )
                    await HumanizeModeManager.reset_state(chat_key)
                    logger.info("【会话重置】已清空拟人增强状态 chat_key=%s", chat_key)
            except Exception:
                logger.warning("【会话重置】清空拟人增强状态失败", exc_info=True)

            # 🆕 v1.2.1: 冷却机制状态清理 (Requirements 5.1)
            try:
                if self.cooldown_enabled:
                    chat_key = ProbabilityManager.get_chat_key(
                        platform_name, is_private, chat_id
                    )
                    cooldown_cleared = await CooldownManager.clear_session_cooldown(
                        chat_key
                    )
                    if cooldown_cleared > 0:
                        logger.info(
                            "【会话重置】已清空冷却状态 chat_key=%s, 清理用户数=%s",
                            chat_key,
                            cooldown_cleared,
                        )
            except Exception:
                logger.warning("【会话重置】清空冷却状态失败", exc_info=True)

            # —— 持久化上下文清理 ——
            try:
                # 删除该会话在本插件用于缓存的上下文文件（非官方历史）
                file_path = ContextManager._get_storage_path(
                    platform_name, is_private, chat_id
                )
                if file_path is None:
                    logger.warning(
                        "【会话重置】无法获取上下文文件路径（base_storage_path 未初始化），尝试手动构建路径"
                    )
                    # 🔧 修复：手动构建路径作为备选方案
                    try:
                        data_dir = StarTools.get_data_dir()
                        if data_dir:
                            chat_type = "private" if is_private else "group"
                            file_path = Path(str(data_dir)) / "chat_history" / platform_name / chat_type / f"{chat_id}.json"
                            logger.info(f"【会话重置】手动构建路径: {file_path}")
                    except Exception as path_err:
                        logger.warning(f"【会话重置】手动构建路径失败: {path_err}")
                        file_path = None

                if file_path and file_path.exists():
                    try:
                        file_path.unlink()
                        logger.info(
                            "【会话重置】已删除会话上下文文件 path=%s",
                            file_path,
                        )
                    except Exception as del_err:
                        logger.warning(
                            "【会话重置】删除会话上下文文件失败 path=%s, error=%s",
                            file_path,
                            del_err,
                            exc_info=True,
                        )
                elif file_path:
                    logger.info(
                        "【会话重置】会话上下文文件不存在，无需删除 path=%s",
                        file_path,
                    )
                else:
                    logger.warning("【会话重置】无法确定上下文文件路径，跳过删除")
            except Exception:
                logger.warning("【会话重置】处理上下文文件失败", exc_info=True)
            try:
                # 将注意力变更落盘，确保重置后的状态被保存
                if hasattr(AttentionManager, "_save_to_disk"):
                    AttentionManager._save_to_disk(force=True)

                    logger.info("【会话重置】注意力状态已持久化 chat_id=%s", chat_id)
            except Exception:
                logger.warning("【会话重置】注意力状态持久化失败", exc_info=True)

            logger.info(
                "【会话重置】完成: platform=%s, chat_id=%s",
                platform_name,
                chat_id,
            )
        except Exception:
            # 兜底保护：任何异常都不传播，避免影响外部流程

            logger.error("【会话重置】执行失败", exc_info=True)
            pass

    async def _reset_plugin_data_and_reload(self) -> None:
        """
        清空本插件的本地缓存与派生数据。

        注意：
        - 不会删除 AstrBot 官方对话系统中的历史（ConversationManager 维护的官方历史保留）
        - 仅清理本插件维护的内存态与数据目录下的本地缓存文件
        - 重载通过 PluginManager.reload('chat_plus') 实现，名称与 @register 一致
        """
        try:
            logger.info("【插件重置】开始: 清理全局缓存并热重载")
            try:
                # 待转正的消息缓存（主动回复模式产生）
                pending_total = sum(
                    len(v) for v in self.pending_messages_cache.values()
                )
                self.pending_messages_cache.clear()

                logger.info(
                    "【插件重置】已清空待转存消息缓存 清理会话=%s, 清理条数=%s",
                    pending_total,
                    len(self.pending_messages_cache),
                )
            except Exception:
                logger.warning("【插件重置】清空待转存消息缓存失败", exc_info=True)
            try:
                # 会话处理中标记
                processing_count = len(self.processing_sessions)
                self.processing_sessions.clear()

                logger.info(
                    "【插件重置】已清空处理中标记 清理会话=%s",
                    processing_count,
                )
            except Exception:
                logger.warning("【插件重置】清空处理中标记失败", exc_info=True)
            try:
                # 指令标记缓存（跨处理器通信用）
                command_count = len(self.command_messages)
                self.command_messages.clear()

                logger.info(
                    "【插件重置】已清空指令标记缓存 清理条数=%s",
                    command_count,
                )
            except Exception:
                logger.warning("【插件重置】清空指令标记缓存失败", exc_info=True)
            try:
                # 最近回复缓存（去重使用）
                replies_total = sum(len(v) for v in self.recent_replies_cache.values())
                self.recent_replies_cache.clear()
                self.raw_reply_cache.clear()

                logger.info(
                    "【插件重置】已清空最近回复缓存 清理会话=%s, 清理条目=%s",
                    replies_total,
                    len(self.recent_replies_cache),
                )
            except Exception:
                logger.warning("【插件重置】清空最近回复缓存失败", exc_info=True)
            try:
                # 戳一戳追踪记录
                self.poke_trace_records = {}

                logger.info("【插件重置】已清空戳一戳追踪记录")
            except Exception:
                logger.warning("【插件重置】清空戳一戳追踪记录失败", exc_info=True)
            try:
                # 情绪追踪：清空内存态
                if hasattr(self, "mood_tracker") and hasattr(
                    self.mood_tracker, "moods"
                ):
                    mood_count = len(self.mood_tracker.moods)
                    self.mood_tracker.moods.clear()

                    logger.info(
                        "【插件重置】已清空情绪状态 清理会话=%s",
                        mood_count,
                    )
            except Exception:
                logger.warning("【插件重置】清空情绪状态失败", exc_info=True)
            try:
                # 主动对话：清空各群聊状态
                chat_state_count = len(
                    getattr(ProactiveChatManager, "_chat_states", {})
                )
                ProactiveChatManager._chat_states.clear()

                logger.info(
                    "【插件重置】已清空主动对话状态 清理会话=%s",
                    chat_state_count,
                )
            except Exception:
                logger.warning("【插件重置】清空主动对话状态失败", exc_info=True)
            try:
                # 主动对话：清空临时概率提升
                if hasattr(ProactiveChatManager, "_temp_probability_boost"):
                    temp_boost_count = len(ProactiveChatManager._temp_probability_boost)
                    ProactiveChatManager._temp_probability_boost.clear()

                    logger.info(
                        "【插件重置】已清空临时概率提升 清理会话=%s",
                        temp_boost_count,
                    )
            except Exception:
                logger.warning("【插件重置】清空临时概率提升失败", exc_info=True)
            try:
                # 🆕 v1.2.0: 清空主动对话回复用户追踪器
                if hasattr(self, "_proactive_reply_users"):
                    reply_tracking_count = len(self._proactive_reply_users)
                    self._proactive_reply_users.clear()

                    logger.info(
                        "【插件重置】已清空主动对话回复追踪 清理会话=%s",
                        reply_tracking_count,
                    )
            except Exception:
                logger.warning("【插件重置】清空主动对话回复追踪失败", exc_info=True)
            try:
                # 注意力数据：清空内存映射
                attention_count = len(getattr(AttentionManager, "_attention_map", {}))
                AttentionManager._attention_map.clear()

                logger.info(
                    "【插件重置】已清空注意力映射 清理会话=%s",
                    attention_count,
                )
            except Exception:
                logger.warning("【插件重置】清空注意力映射失败", exc_info=True)
            try:
                # 概率管理器：清空所有会话的概率状态
                probability_count = len(
                    getattr(ProbabilityManager, "_probability_status", {})
                )
                ProbabilityManager._probability_status.clear()

                logger.info(
                    "【插件重置】已清空概率状态 清理会话=%s",
                    probability_count,
                )
            except Exception:
                logger.warning("【插件重置】清空概率状态失败", exc_info=True)
            try:
                # 频率调整器：清空所有会话的检查状态
                if hasattr(self, "frequency_adjuster") and self.frequency_adjuster:
                    adjuster_count = len(self.frequency_adjuster.check_states)
                    self.frequency_adjuster.check_states.clear()

                    logger.info(
                        "【插件重置】已清空频率检查状态 清理会话=%s",
                        adjuster_count,
                    )
            except Exception:
                logger.warning("【插件重置】清空频率检查状态失败", exc_info=True)
            try:
                # 🆕 v1.2.0: 拟人增强模式：清空所有会话的状态
                if self.humanize_mode_enabled:
                    humanize_count = len(
                        getattr(HumanizeModeManager, "_chat_states", {})
                    )
                    HumanizeModeManager._chat_states.clear()

                    logger.info(
                        "【插件重置】已清空拟人增强状态 清理会话=%s",
                        humanize_count,
                    )
            except Exception:
                logger.warning("【插件重置】清空拟人增强状态失败", exc_info=True)
            try:
                # 🆕 v1.2.1: 冷却机制：清空所有会话的冷却状态 (Requirements 5.2)
                if self.cooldown_enabled:
                    cooldown_cleared = await CooldownManager.clear_all_cooldown()
                    logger.info(
                        "【插件重置】已清空冷却状态 清理用户数=%s",
                        cooldown_cleared,
                    )
            except Exception:
                logger.warning("【插件重置】清空冷却状态失败", exc_info=True)
            try:
                # 删除本插件数据目录下的持久化缓存文件/目录
                data_dir = StarTools.get_data_dir()
                base_path = Path(str(data_dir))
                # 自定义历史缓存（仅本插件使用的本地历史，非官方）
                chat_history_dir = base_path / "chat_history"
                if chat_history_dir.exists():
                    shutil.rmtree(chat_history_dir, ignore_errors=True)

                    logger.info(
                        "【插件重置】已删除自定义历史目录 path=%s",
                        chat_history_dir,
                    )
                # 注意力持久化文件
                att_file = base_path / "attention_data.json"
                if att_file.exists():
                    try:
                        att_file.unlink()

                        logger.info(
                            "【插件重置】已删除注意力持久化文件 path=%s",
                            att_file,
                        )
                    except Exception:
                        logger.warning(
                            "【插件重置】删除注意力持久化文件失败 path=%s",
                            att_file,
                            exc_info=True,
                        )
                # 主动对话状态持久化文件
                pcs_file = base_path / "proactive_chat_states.json"
                if pcs_file.exists():
                    try:
                        pcs_file.unlink()
                    except Exception:
                        pass
                # 🆕 v1.2.1: 冷却机制持久化文件 (Requirements 5.2)
                cooldown_file = base_path / "cooldown_data.json"
                if cooldown_file.exists():
                    try:
                        cooldown_file.unlink()
                        logger.info(
                            "【插件重置】已删除冷却持久化文件 path=%s",
                            cooldown_file,
                        )
                    except Exception:
                        logger.warning(
                            "【插件重置】删除冷却持久化文件失败 path=%s",
                            cooldown_file,
                            exc_info=True,
                        )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"插件重置失败: {e}", exc_info=True)

    async def _perform_initial_checks(self, event: AstrMessageEvent) -> tuple:
        """
        执行初始检查

        Returns:
            (should_continue, platform_name, is_private, chat_id)
            - should_continue: 是否继续处理
            - 其他: 基本信息
        """
        if self.debug_mode:
            logger.info("=" * 60)
            logger.info("【步骤1】开始基础检查")

        # 检查是否启用
        if not self._is_enabled(event):
            if self.debug_mode:
                logger.info("【步骤1】群组未启用插件,跳过处理")
            return False, None, None, None

        # 检查是否是机器人自己的消息
        if MessageProcessor.is_message_from_bot(event):
            if self.debug_mode:
                logger.info("忽略机器人自己的消息")
            return False, None, None, None

        # 获取基本信息
        platform_name = event.get_platform_name()
        is_private = event.is_private_chat()
        chat_id = event.get_group_id() if not is_private else event.get_sender_id()

        if self.debug_mode:
            logger.info(f"【步骤1】基础信息:")
            logger.info(f"  平台: {platform_name}")
            logger.info(f"  类型: {'私聊' if is_private else '群聊'}")
            logger.info(f"  会话ID: {chat_id}")
            logger.info(f"  发送者: {event.get_sender_name()}({event.get_sender_id()})")

        # 黑名单关键词检查
        if self.debug_mode:
            logger.info("【步骤2】检查黑名单关键词")

        blacklist_keywords = self.blacklist_keywords
        if KeywordChecker.check_blacklist_keywords(event, blacklist_keywords):
            if self.debug_mode:
                logger.info("【步骤2】黑名单关键词匹配，丢弃消息")
                logger.info("=" * 60)
            return False, None, None, None

        return True, platform_name, is_private, chat_id

    async def _check_message_triggers(self, event: AstrMessageEvent) -> tuple:
        """
        检查消息触发器（@消息和触发关键词）

        Returns:
            (is_at_message, has_trigger_keyword, matched_trigger_keyword)
            🆕 v1.2.1: 新增返回匹配到的触发关键词
        """
        # 判断是否是@消息
        is_at_message = MessageProcessor.is_at_message(event)

        # 只在debug模式或是@消息时记录
        if self.debug_mode:
            logger.info(
                f"【步骤3】@消息检测: {'是@消息' if is_at_message else '非@消息'}"
            )

        # 触发关键词检查
        if self.debug_mode:
            logger.info("【步骤4】检查触发关键词")

        trigger_keywords = self.trigger_keywords
        # 🆕 v1.2.1: 使用新方法获取匹配到的关键词
        has_trigger_keyword, matched_trigger_keyword = (
            KeywordChecker.check_trigger_keywords_with_match(event, trigger_keywords)
        )

        # 只在检测到关键词时记录
        if has_trigger_keyword:
            if self.debug_mode:
                logger.info(
                    f"【步骤4】检测到触发关键词: {matched_trigger_keyword}，跳过读空气判断"
                )

        return is_at_message, has_trigger_keyword, matched_trigger_keyword

    async def _check_probability_before_processing(
        self,
        event: AstrMessageEvent,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        is_at_message: bool,
        has_trigger_keyword: bool,
        poke_info: dict = None,
    ) -> bool:
        """
        执行概率判断（在图片处理之前）

        Args:
            event: 消息事件对象
            platform_name: 平台名称
            is_private: 是否私聊
            chat_id: 聊天ID
            is_at_message: 是否@消息
            has_trigger_keyword: 是否包含触发关键词
            poke_info: 戳一戳信息（v1.0.9新增）

        Returns:
            True=继续处理, False=丢弃消息
        """
        # 🆕 v1.2.0: 拟人增强模式 - 动态消息阈值检查
        if self.humanize_mode_enabled:
            try:
                chat_key = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )
                # 先增加消息计数
                await HumanizeModeManager.increment_message_count(chat_key)
                # 检查是否应该跳过（基于动态阈值）
                (
                    should_skip,
                    skip_reason,
                    count,
                ) = await HumanizeModeManager.should_skip_for_dynamic_threshold(
                    chat_key=chat_key,
                    is_mentioned=is_at_message or has_trigger_keyword,
                )
                if should_skip:
                    if self.debug_mode:
                        logger.info(
                            f"【步骤5】🎭 拟人增强: 动态阈值未达到，跳过本次判断 ({skip_reason})"
                        )
                    return False
            except Exception as e:
                if self.debug_mode:
                    logger.warning(
                        f"【步骤5】🎭 拟人增强: 动态阈值检查失败，继续正常处理: {e}"
                    )

        # 检查是否应该跳过概率判断（戳机器人的特殊处理）
        skip_probability_for_poke = False
        if poke_info and self.poke_bot_skip_probability:
            # 如果是戳机器人，且开关打开
            # poke_info现在是完整的poke_result结构，需要从内嵌的poke_info中获取is_poke_bot
            inner_poke_info = poke_info.get("poke_info", {})
            if inner_poke_info.get("is_poke_bot"):
                skip_probability_for_poke = True
                if self.debug_mode:
                    logger.info(
                        "【步骤5】戳机器人消息，戳的是机器人，配置允许跳过概率判断。跳过概率筛选，保留读空气判断"
                    )

        # @消息、触发关键词消息、或符合条件的戳一戳消息跳过概率判断
        # v1.1.2: 关键词智能模式下，关键词也会跳过概率判断
        if (
            not is_at_message
            and not has_trigger_keyword
            and not skip_probability_for_poke
        ):
            # 概率判断
            if self.debug_mode:
                logger.info("【步骤5】开始读空气概率判断")

            should_process = await self._check_probability(
                platform_name, is_private, chat_id, event, poke_info=poke_info
            )
            if not should_process:
                if self.debug_mode:
                    logger.info("【步骤5】概率判断失败,丢弃消息")
                    logger.info("=" * 60)
                return False

            logger.info("读空气概率判断: 决定处理此消息")
            if self.debug_mode:
                logger.info("【步骤5】概率判断通过,继续处理")
        else:
            # @消息或触发关键词，跳过概率判断
            if is_at_message:
                if self.debug_mode:
                    logger.info("【步骤5】@消息,跳过概率判断,必定处理")

            if has_trigger_keyword:
                if self.debug_mode:
                    # v1.1.2: 根据智能模式显示不同的日志
                    keyword_smart_mode = self.keyword_smart_mode
                    if keyword_smart_mode:
                        logger.info(
                            "【步骤5】触发关键词消息(智能模式),跳过概率判断,但保留读空气判断"
                        )
                    else:
                        logger.info("【步骤5】触发关键词消息,跳过概率判断,必定处理")

            if skip_probability_for_poke:
                if self.debug_mode:
                    logger.info("【步骤5】戳机器人消息,跳过概率判断,必定处理")

        return True

    async def _check_ai_decision(
        self,
        event: AstrMessageEvent,
        formatted_context: str,
        is_at_message: bool,
        has_trigger_keyword: bool,
        image_urls: Optional[List[str]] = None,
        matched_trigger_keyword: str = "",  # 🆕 v1.2.1: 匹配到的触发关键词
        original_message_text: str = "",  # 🆕 v1.2.2: 原始消息文本（用于关键词检测）
    ) -> bool:
        """
        执行AI决策判断（在处理完消息内容后）

        Returns:
            True=应该回复, False=不回复
        """
        # v1.1.2: 检查关键词智能模式（使用已提取的实例变量）
        keyword_smart_mode = self.keyword_smart_mode

        # 获取会话信息
        platform_name = event.get_platform_name()
        is_private = event.is_private_chat()
        chat_id = event.get_group_id() if not is_private else event.get_sender_id()

        # 🆕 v1.2.0: 检查是否为主动对话后的回复（在临时提升期内）
        is_proactive_reply = False
        if self.proactive_enabled:
            chat_key = ProbabilityManager.get_chat_key(
                platform_name, is_private, chat_id
            )
            state = ProactiveChatManager.get_chat_state(chat_key)
            proactive_active = state.get("proactive_active", False)
            last_proactive_time = state.get("last_proactive_time", 0)
            current_time = time.time()
            boost_duration = self.proactive_temp_boost_duration
            in_boost_period = (current_time - last_proactive_time) <= boost_duration

            # 如果主动对话活跃且在提升期内，标记为主动对话回复
            is_proactive_reply = proactive_active and in_boost_period

            if is_proactive_reply and self.debug_mode:
                logger.info(
                    f"[决策AI] 检测到主动对话回复（提升期剩余 "
                    f"{int(boost_duration - (current_time - last_proactive_time))}秒），"
                    f"将提示AI优先回复"
                )

        # 在读空气AI之前注入记忆（可选）
        decision_formatted_context = formatted_context
        if (
            self.enable_memory_injection
            and self.memory_insertion_timing == "pre_decision"
        ):
            memory_mode = self.memory_plugin_mode
            livingmemory_top_k = self.livingmemory_top_k

            if MemoryInjector.check_memory_plugin_available(
                self.context, mode=memory_mode
            ):
                try:
                    memories = await MemoryInjector.get_memories(
                        self.context,
                        event,
                        mode=memory_mode,
                        top_k=livingmemory_top_k,
                    )
                    mem_text = str(memories).strip() if memories is not None else ""
                    if mem_text and ("当前没有任何记忆" not in mem_text):
                        old_len = len(decision_formatted_context)
                        decision_formatted_context = (
                            MemoryInjector.inject_memories_to_message(
                                decision_formatted_context, mem_text
                            )
                        )
                        if self.debug_mode:
                            logger.info(
                                f"[决策AI] 已在判定前注入记忆({memory_mode}模式)，长度增加: {len(decision_formatted_context) - old_len} 字符"
                            )
                        try:
                            ckey = ProbabilityManager.get_chat_key(
                                platform_name, is_private, chat_id
                            )
                            if not hasattr(self, "_pre_decision_context_by_chat"):
                                self._pre_decision_context_by_chat = {}
                            self._pre_decision_context_by_chat[ckey] = (
                                decision_formatted_context
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"[决策AI] 判定前注入记忆失败: {e}", exc_info=True)
            elif self.debug_mode:
                logger.info(
                    f"[决策AI] 记忆插件({memory_mode}模式)不可用，判定前跳过记忆注入"
                )

        # 判断是否需要进行AI决策
        # @消息必定跳过AI决策
        # 触发关键词：智能模式下需要AI决策，非智能模式跳过AI决策
        should_do_ai_decision = not is_at_message and (
            not has_trigger_keyword or keyword_smart_mode
        )

        # 🆕 v1.2.3: 初始化对话疲劳信息（在决策块外部初始化，确保后续可用）
        conversation_fatigue_info = None

        # 🆕 v1.2.0: 拟人增强模式 - 静默模式检查
        chat_key = ProbabilityManager.get_chat_key(platform_name, is_private, chat_id)
        if should_do_ai_decision and self.humanize_mode_enabled:
            try:
                # 检查是否应该跳过AI决策（静默模式）
                # 🔧 v1.2.2: 使用原始消息文本进行关键词检测，而不是格式化后的上下文
                message_text_for_keyword = (
                    original_message_text
                    if original_message_text
                    else formatted_context
                )
                (
                    should_skip,
                    skip_reason,
                ) = await HumanizeModeManager.should_skip_ai_decision(
                    chat_key=chat_key,
                    is_mentioned=is_at_message or has_trigger_keyword,
                    message_text=message_text_for_keyword,
                )

                if should_skip:
                    if self.debug_mode:
                        logger.info(
                            f"【步骤9】🎭 拟人增强: 跳过AI决策 (原因: {skip_reason})"
                        )
                    return False
            except Exception as e:
                logger.warning(f"[拟人增强] 静默模式检查失败，继续正常处理: {e}")

        if should_do_ai_decision:
            # 🆕 v1.2.0: 拟人增强模式 - 注入历史决策记录
            if self.humanize_mode_enabled:
                try:
                    decision_history_prompt = (
                        await HumanizeModeManager.build_decision_history_prompt(
                            chat_key
                        )
                    )
                    if decision_history_prompt:
                        decision_formatted_context = (
                            decision_formatted_context + decision_history_prompt
                        )
                        if self.debug_mode:
                            logger.info("【步骤9】🎭 已注入历史决策记录到提示词")

                    # 🆕 检测兴趣话题并记录日志（实际概率调整已在 _check_probability 中完成）
                    # 🔧 v1.2.2: 使用原始消息文本进行关键词检测
                    (
                        is_interest_match,
                        matched_keyword,
                    ) = await HumanizeModeManager.check_interest_match(
                        message_text_for_keyword
                        if "message_text_for_keyword" in locals()
                        else (
                            original_message_text
                            if original_message_text
                            else formatted_context
                        )
                    )
                    if is_interest_match and self.debug_mode:
                        logger.info(f"【步骤9】🎭 检测到兴趣话题: {matched_keyword}")
                except Exception as e:
                    logger.warning(f"[拟人增强] 历史决策注入失败，继续正常处理: {e}")

            # 决策AI判断
            if self.debug_mode:
                logger.info("【步骤9】调用决策AI判断是否回复")

            _decision_start = time.time()

            # 🆕 v1.2.0: 获取增强上下文信息
            # 获取兴趣话题关键词
            interest_keywords = []
            if self.humanize_mode_enabled:
                interest_keywords = self.humanize_interest_keywords

            # 获取动态时间段配置信息
            time_period_info = None
            if self.enable_dynamic_reply_probability:
                try:
                    from .utils.time_period_manager import TimePeriodManager
                    from datetime import datetime as dt

                    periods = TimePeriodManager.parse_time_periods(
                        self.reply_time_periods, silent=True
                    )

                    if periods:
                        # 计算当前时间系数
                        current_factor = TimePeriodManager.calculate_time_factor(
                            current_time=None,  # 使用当前时间
                            periods_config=periods,
                            transition_minutes=self.reply_time_transition_minutes,
                            min_factor=self.reply_time_min_factor,
                            max_factor=self.reply_time_max_factor,
                            use_smooth_curve=self.reply_time_use_smooth_curve,
                        )

                        # 查找当前匹配的时间段名称
                        current_period_name = ""
                        now = dt.now()
                        current_minutes = now.hour * 60 + now.minute
                        for period in periods:
                            try:
                                start_parts = period["start"].split(":")
                                end_parts = period["end"].split(":")
                                start_minutes = int(start_parts[0]) * 60 + int(
                                    start_parts[1] if len(start_parts) > 1 else 0
                                )
                                end_minutes = int(end_parts[0]) * 60 + int(
                                    end_parts[1] if len(end_parts) > 1 else 0
                                )

                                # 判断是否在时间段内（支持跨天）
                                if start_minutes > end_minutes:
                                    in_period = (
                                        current_minutes >= start_minutes
                                        or current_minutes < end_minutes
                                    )
                                else:
                                    in_period = (
                                        start_minutes <= current_minutes < end_minutes
                                    )

                                if in_period:
                                    current_period_name = period.get(
                                        "name", f"{period['start']}-{period['end']}"
                                    )
                                    break
                            except:
                                continue

                        time_period_info = {
                            "enabled": True,
                            "current_factor": current_factor,
                            "current_period_name": current_period_name or "默认时段",
                        }
                except Exception as e:
                    if self.debug_mode:
                        logger.warning(f"[决策AI] 获取时间段配置失败: {e}")

            # 判断是否通过关键词触发（智能模式下）
            is_keyword_triggered = has_trigger_keyword and keyword_smart_mode

            # 🆕 获取对话疲劳信息
            conversation_fatigue_info = None
            if self.enable_conversation_fatigue and self.enable_attention_mechanism:
                try:
                    user_id = event.get_sender_id()
                    conversation_fatigue_info = await AttentionManager.get_conversation_fatigue_info(
                        platform_name, is_private, chat_id, user_id
                    )
                    if self.debug_mode and conversation_fatigue_info.get("consecutive_replies", 0) > 0:
                        logger.info(
                            f"[对话疲劳] 用户连续对话轮次: {conversation_fatigue_info.get('consecutive_replies', 0)}, "
                            f"疲劳等级: {conversation_fatigue_info.get('fatigue_level', 'none')}"
                        )
                except Exception as e:
                    if self.debug_mode:
                        logger.warning(f"[对话疲劳] 获取疲劳信息失败: {e}")

            should_reply = await DecisionAI.should_reply(
                self.context,
                event,
                decision_formatted_context,
                self.decision_ai_provider_id,
                self.decision_ai_extra_prompt,
                self.decision_ai_timeout,
                self.decision_ai_prompt_mode,
                image_urls=image_urls,
                is_proactive_reply=is_proactive_reply,
                config=self.config,
                include_sender_info=self.include_sender_info,
                # 🆕 v1.2.0: 新增参数
                is_keyword_triggered=is_keyword_triggered,
                matched_keyword=matched_trigger_keyword,
                interest_keywords=interest_keywords,
                time_period_info=time_period_info,
                humanize_mode_enabled=self.humanize_mode_enabled,
                # 🆕 v1.2.2: 传递原始消息文本用于关键词检测
                original_message_text=original_message_text,
                # 🆕 v1.2.3: 传递对话疲劳信息
                conversation_fatigue_info=conversation_fatigue_info,
            )
            # 🐛 修复：不要在这里删除缓存！
            # pre_decision 模式下，缓存的上下文（已植入记忆）需要在生成回复时使用
            # 缓存会在 _generate_and_send_reply 中使用 .pop() 时自动删除
            # 如果在这里删除，会导致最终回复AI看不到提前植入的记忆

            if self.debug_mode:
                _decision_elapsed = time.time() - _decision_start
                logger.info(f"【步骤9】决策AI判断完成，耗时: {_decision_elapsed:.2f}秒")

            if not should_reply:
                logger.info("决策AI判断: 不应该回复此消息")

                decision_ai_error = False
                try:
                    decision_ai_error = bool(
                        getattr(event, "_decision_ai_error", False)
                    )
                except Exception:
                    decision_ai_error = False

                if decision_ai_error:
                    logger.warning(
                        "[决策AI] 本次判断因AI调用失败而返回不回复，跳过拟人统计和注意力衰减"
                    )
                else:
                    # 🆕 v1.2.0: 拟人增强模式 - 记录决策结果
                    if self.humanize_mode_enabled:
                        try:
                            message_preview = (
                                formatted_context[:50] if formatted_context else ""
                            )
                            await HumanizeModeManager.record_decision(
                                chat_key=chat_key,
                                decision=False,
                                reason="AI判断不需要回复",
                                message_preview=message_preview,
                            )
                        except Exception as e:
                            logger.warning(f"[拟人增强] 记录决策失败: {e}")

                    # 🆕 注意力衰减：如果注意力机制启用且对该用户注意力较高，进行衰减
                    if self.enable_attention_mechanism:
                        try:
                            user_id = event.get_sender_id()
                            user_name = event.get_sender_name() or "未知用户"

                            # 调用注意力衰减方法
                            await AttentionManager.decrease_attention_on_no_reply(
                                platform_name,
                                is_private,
                                chat_id,
                                user_id,
                                user_name,
                                attention_decrease_step=self.attention_decrease_on_no_reply_step,
                                min_attention_threshold=self.attention_decrease_threshold,
                            )
                        except Exception as e:
                            logger.warning(f"[注意力衰减] 执行失败: {e}", exc_info=True)

                # 🔧 清理pre_decision缓存（防止内存残留）
                try:
                    ckey = ProbabilityManager.get_chat_key(
                        platform_name, is_private, chat_id
                    )
                    if (
                        hasattr(self, "_pre_decision_context_by_chat")
                        and ckey in self._pre_decision_context_by_chat
                    ):
                        del self._pre_decision_context_by_chat[ckey]
                        if self.debug_mode:
                            logger.info("  已清理pre_decision缓存（决策判定不回复）")
                except Exception:
                    pass
                return False

            logger.info("决策AI判断: 应该回复此消息")

            # 🆕 v1.2.0: 拟人增强模式 - 记录决策结果
            if self.humanize_mode_enabled:
                try:
                    message_preview = (
                        formatted_context[:50] if formatted_context else ""
                    )
                    await HumanizeModeManager.record_decision(
                        chat_key=chat_key,
                        decision=True,
                        reason="AI判断应该回复",
                        message_preview=message_preview,
                    )
                except Exception as e:
                    logger.warning(f"[拟人增强] 记录决策失败: {e}")

            return True
        else:
            # @消息或触发关键词(非智能模式)，必定回复
            # 注意：疲劳轮次重置移到AI实际回复后执行，避免在这里提前重置

            # 🆕 v1.2.3: 获取对话疲劳信息（即使跳过AI决策，回复AI也需要疲劳信息）
            if self.enable_conversation_fatigue and self.enable_attention_mechanism:
                try:
                    user_id = event.get_sender_id()
                    conversation_fatigue_info = await AttentionManager.get_conversation_fatigue_info(
                        platform_name, is_private, chat_id, user_id
                    )
                    if self.debug_mode and conversation_fatigue_info.get("consecutive_replies", 0) > 0:
                        logger.info(
                            f"[对话疲劳] 用户连续对话轮次: {conversation_fatigue_info.get('consecutive_replies', 0)}, "
                            f"疲劳等级: {conversation_fatigue_info.get('fatigue_level', 'none')}"
                        )
                except Exception as e:
                    if self.debug_mode:
                        logger.warning(f"[对话疲劳] 获取疲劳信息失败: {e}")

            # 🆕 v1.2.0: 拟人增强模式 - 被@或触发关键词时也记录决策（作为回复）
            if self.humanize_mode_enabled:
                try:
                    message_preview = (
                        formatted_context[:50] if formatted_context else ""
                    )
                    await HumanizeModeManager.record_decision(
                        chat_key=chat_key,
                        decision=True,
                        reason="被@或触发关键词，必定回复",
                        message_preview=message_preview,
                    )
                except Exception as e:
                    logger.warning(f"[拟人增强] 记录决策失败: {e}")
            if self.debug_mode:
                if is_at_message:
                    logger.info("【步骤9】@消息,跳过AI决策,必定回复")
                elif has_trigger_keyword and not keyword_smart_mode:
                    logger.info("【步骤9】触发关键词(非智能模式),跳过AI决策,必定回复")
            try:
                ckey = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )
                if not hasattr(self, "_ai_decision_skipped"):
                    self._ai_decision_skipped = set()
                self._ai_decision_skipped.add(ckey)
            except Exception:
                pass
            return True

    async def _process_message_content(
        self,
        event: AstrMessageEvent,
        chat_id: str,
        is_at_message: bool,
        mention_info: dict = None,
        has_trigger_keyword: bool = False,
        poke_info: dict = None,
        raw_is_at_message: bool = None,
    ) -> tuple:
        """
        处理消息内容（图片处理、上下文格式化）

        Args:
            event: 消息事件对象
            chat_id: 聊天ID
            is_at_message: 是否为@消息
            mention_info: @别人的信息字典（如果存在）
            has_trigger_keyword: 是否包含触发关键词
            poke_info: 戳一戳信息（如果存在）

        Returns:
            (should_continue, original_message_text, processed_message, formatted_context, image_urls)
            - should_continue: 是否继续处理
            - original_message_text: 纯净的原始消息（不含元数据）
            - processed_message: 处理后的消息（图片已处理，不含元数据，用于保存）
            - formatted_context: 格式化后的完整上下文（历史消息+当前消息，当前消息已添加元数据）
            - image_urls: 图片URL列表（用于多模态AI）
        """
        # 提取纯净原始消息
        if self.debug_mode:
            logger.info("【步骤6】提取纯净原始消息")

        # 使用MessageCleaner提取纯净的原始消息（不含系统提示词）
        original_message_text = MessageCleaner.extract_raw_message_from_event(event)
        if self.debug_mode:
            logger.info(f"  纯净原始消息: {original_message_text[:100]}...")

        real_is_at_message = (
            raw_is_at_message if raw_is_at_message is not None else is_at_message
        )

        # 检查是否是空@消息
        is_empty_at = MessageCleaner.is_empty_at_message(
            original_message_text, real_is_at_message
        )
        if is_empty_at:
            if self.debug_mode:
                logger.info("  纯@消息将使用特殊处理")

        # 处理图片（在缓存之前）
        # 这样如果图片被过滤，消息就不会被缓存
        if self.debug_mode:
            logger.info("【步骤6.5】处理图片内容")

        (
            should_continue,
            processed_message,
            image_urls,
        ) = await ImageHandler.process_message_images(
            event,
            self.context,
            self.enable_image_processing,
            self.image_to_text_scope,
            self.image_to_text_provider_id,
            self.image_to_text_prompt,
            real_is_at_message,
            has_trigger_keyword,
            self.image_to_text_timeout,
        )

        if not should_continue:
            logger.info("图片处理后决定丢弃此消息（图片被过滤或处理失败）")
            if self.debug_mode:
                logger.info("【步骤6.5】图片处理判定丢弃消息，不缓存")
                logger.info("=" * 60)
            return False, None, None, None, None

        # 缓存当前用户消息（图片处理通过后再缓存）
        # 注意：缓存处理后的消息（不含元数据），在保存时再添加元数据
        # processed_message 已经是经过图片处理的最终结果（可能是过滤后、转文字后、或原始消息）
        if self.debug_mode:
            logger.info("【步骤7】缓存处理后的用户消息（不含元数据，保存时再添加）")
            logger.info(f"  原始消息（提取自event）: {original_message_text[:200]}...")
            logger.info(f"  处理后消息（图片处理后）: {processed_message[:200]}...")

        # 🆕 v1.0.4: 确定触发方式（用于后续添加系统提示）
        # 根据is_at_message和has_trigger_keyword判断触发方式
        # 注意：在这个阶段还不知道是否会AI主动回复，所以先不设置trigger_type
        # 会在后续添加元数据时根据实际情况设置

        # 缓存处理后的消息内容，不包含元数据
        # 保存发送者信息和时间戳，用于后续添加元数据

        # 🔧 修复并发问题：在缓存中保存 message_id，用于在保存时排除正在处理中的消息
        current_message_id = self._get_message_id(event)
        
        cached_message = {
            "role": "user",
            "content": processed_message,  # 处理后的消息（可能已过滤图片、转文字、或保留原样）
            "timestamp": time.time(),
            # 🔧 修复并发问题：保存 message_id，用于识别正在处理中的消息
            "message_id": current_message_id,
            # 保存发送者信息，用于转正时添加正确的元数据
            "sender_id": event.get_sender_id(),
            "sender_name": event.get_sender_name(),
            "message_timestamp": event.message_obj.timestamp
            if hasattr(event, "message_obj") and hasattr(event.message_obj, "timestamp")
            else None,
            # 保存@别人的信息（如果存在）
            "mention_info": mention_info,
            # 🆕 v1.0.4: 保存触发方式信息（用于后续添加系统提示）
            # 注意：is_at_message 参数可能是 should_treat_as_at，所以需要同时保存 has_trigger_keyword
            # 以便后续能正确判断触发方式
            "is_at_message": is_at_message,
            "has_trigger_keyword": has_trigger_keyword,  # 重新添加，用于正确判断触发方式
            # 🆕 v1.0.9: 保存戳一戳信息（如果存在）
            "poke_info": poke_info,
            "image_urls": image_urls or [],
        }

        # 缓存内容日志
        # 优化：只在debug模式下或确实有问题时才记录警告
        # 空消息可能是正常的（如纯图片、纯表情、戳一戳等）
        if not original_message_text and not processed_message:
            # 只有原始和处理后都为空时才警告（可能是提取问题）
            if self.debug_mode:
                logger.info(
                    "⚠️ [缓存] 原始和处理后消息均为空（可能是纯图片/表情/戳一戳等）"
                )
        elif not original_message_text and self.debug_mode:
            logger.info("⚠️ [缓存] 原始消息为空（但处理后消息存在，可能是图片转文字）")
        elif not processed_message and self.debug_mode:
            logger.info("⚠️ [缓存] 处理后消息为空（但原始消息存在，可能是图片被过滤）")

        if chat_id not in self.pending_messages_cache:
            self.pending_messages_cache[chat_id] = []

        # 清理旧消息（使用配置的过期时间）
        current_time = time.time()
        cache_ttl = self.pending_cache_ttl_seconds  # 使用配置的过期时间
        old_count = len(self.pending_messages_cache[chat_id])
        self.pending_messages_cache[chat_id] = [
            msg
            for msg in self.pending_messages_cache[chat_id]
            # 🔧 修复：优先使用 message_timestamp，兼容 timestamp，与排序逻辑保持一致
            if current_time - (msg.get("message_timestamp") or msg.get("timestamp", 0)) < cache_ttl
        ]

        if self.debug_mode and old_count > len(self.pending_messages_cache[chat_id]):
            removed = old_count - len(self.pending_messages_cache[chat_id])
            logger.info(f"  已清理过期缓存: {removed} 条（超过{cache_ttl}秒）")

        # 添加到缓存（使用配置的最大条数）
        self.pending_messages_cache[chat_id].append(cached_message)
        if len(self.pending_messages_cache[chat_id]) > self.pending_cache_max_count:
            # 🔧 按 message_timestamp 排序后移除最旧的消息，避免并行处理导致顺序问题
            self.pending_messages_cache[chat_id].sort(
                key=lambda m: m.get("message_timestamp") or m.get("timestamp", 0)
            )
            removed_msg = self.pending_messages_cache[chat_id].pop(0)
            if self.debug_mode:
                logger.info(f"  缓存已满（上限{self.pending_cache_max_count}条），移除最旧消息")

        # 🆕 始终显示正常处理缓存日志（即使非debug模式）
        logger.info(
            f"📦 [缓存点2-正常处理] 消息处理完成，已暂存等待AI判断 (共{len(self.pending_messages_cache[chat_id])}条)"
        )

        # 详细日志（仅debug模式）
        if self.debug_mode:
            logger.info(
                f"【缓存详情】原始: {original_message_text[:100] if original_message_text else '(空)'}"
            )
            logger.info(
                f"【缓存详情】处理后: {processed_message[:100] if processed_message else '(空)'}"
            )
            logger.info(
                f"【缓存详情】已缓存: {cached_message['content'][:100] if cached_message['content'] else '(空)'}"
            )
            if processed_message != original_message_text:
                logger.info(f"  ⚠️ 消息内容有变化！原始≠处理后")
            else:
                logger.info(f"  消息内容无变化（原始==处理后）")

        # 为当前消息添加元数据（用于发送给AI）
        # 使用处理后的消息（可能包含图片描述），添加统一格式的元数据
        # 🆕 v1.0.4: 确定触发方式
        # 注意：is_at_message 参数可能是 should_treat_as_at（即 is_at_message or has_trigger_keyword）
        # 所以需要同时检查 has_trigger_keyword 参数来正确判断触发方式
        trigger_type = None
        if has_trigger_keyword:
            # 关键词触发（优先级高于@消息判断，因为is_at_message可能是should_treat_as_at）
            trigger_type = "keyword"
        elif is_at_message:
            # 真正的@消息触发
            trigger_type = "at"
        else:
            # 概率触发（AI主动回复）
            # 注意：虽然此时决策AI还没判断，但如果能走到这里说明概率判断已通过
            # 无论决策AI判断yes/no，这个trigger_type都是正确的：
            # - 判断yes：确实是AI主动回复，提示词"你打算回复他"正确
            # - 判断no：消息只会保存不会发给回复AI，提示词在保存时也正确
            trigger_type = "ai_decision"

        message_text_for_ai = MessageProcessor.add_metadata_to_message(
            event,
            processed_message,  # 使用处理后的消息（图片已处理）
            self.include_timestamp,
            self.include_sender_info,
            mention_info,  # 传递@信息
            trigger_type,  # 🆕 v1.0.4: 传递触发方式
            poke_info,  # 🆕 v1.0.9: 传递戳一戳信息
        )

        # 🆕 戳过对方追踪提示（需要同时满足：功能启用 + 群聊在白名单中 + 有追踪记录）
        if (
            self.poke_trace_enabled
            and self._is_poke_enabled_in_group(chat_id)
            and self._check_and_consume_poke_trace(chat_id, event.get_sender_id())
        ):
            _n = event.get_sender_name() or "未知用户"
            _id = event.get_sender_id()
            message_text_for_ai += (
                f"\n[戳过对方提示]你刚刚戳过这条消息的发送者{_n}(ID:{_id})"
            )
            if self.debug_mode:
                logger.info(f"  已添加戳过对方提示: 目标={_n}(ID:{_id})")

        if self.debug_mode:
            logger.info("【步骤7.5】为当前消息添加元数据（用于AI识别）")
            logger.info(f"  处理后消息: {processed_message[:100]}...")
            logger.info(f"  添加元数据后: {message_text_for_ai[:150]}...")

        # 提取历史上下文
        max_context = self.max_context_messages

        # 🔧 配置矫正：处理类型和异常值
        # 1. 首先确保是整数类型（配置文件可能传入字符串）
        if not isinstance(max_context, int):
            try:
                max_context = int(max_context)
                if self.debug_mode:
                    logger.info(
                        f"[配置矫正] max_context_messages 从 {type(self.max_context_messages).__name__} 转换为 int: {max_context}"
                    )
            except (ValueError, TypeError):
                logger.warning(
                    f"⚠️ [配置矫正] max_context_messages 配置值 '{self.max_context_messages}' 无法转换为整数，已矫正为 -1（不限制）"
                )
                max_context = -1

        # 2. 处理异常值（小于 -1 的情况）
        if isinstance(max_context, int) and max_context < -1:
            logger.warning(
                f"⚠️ [配置矫正] max_context_messages 配置值 {max_context} 小于 -1，已矫正为 -1（不限制）"
            )
            max_context = -1

        if self.debug_mode:
            logger.info("【步骤8】提取历史上下文")
            context_limit_desc = (
                "不限制"
                if max_context == -1
                else "不获取历史"
                if max_context == 0
                else f"限制为 {max_context} 条"
            )
            logger.info(f"  最大上下文数: {max_context} ({context_limit_desc})")

            def _log_msgs(tag, msgs):
                try:
                    cnt = len(msgs) if msgs else 0
                    logger.info(f"  {tag} 条数: {cnt}")
                    if not msgs:
                        return
                    # 展示末尾最多5条的详细信息
                    bot_id_for_check = str(event.get_self_id())
                    show = msgs[-min(5, len(msgs)) :]
                    lines = []
                    for idx, m in enumerate(show, start=cnt - len(show) + 1):
                        try:
                            # 提取通用字段
                            t = None
                            sid = ""
                            sname = ""
                            mid = ""
                            gid = None
                            selfid = ""
                            sess = ""
                            content = ""
                            if isinstance(m, AstrBotMessage):
                                t = getattr(m, "timestamp", None)
                                if hasattr(m, "sender") and m.sender:
                                    sid = str(getattr(m.sender, "user_id", ""))
                                    sname = getattr(m.sender, "nickname", "") or ""
                                mid = getattr(m, "message_id", "") or ""
                                gid = getattr(m, "group_id", None)
                                selfid = str(getattr(m, "self_id", "") or "")
                                sess = str(getattr(m, "session_id", "") or "")
                                content = getattr(m, "message_str", "") or ""
                            elif isinstance(m, dict):
                                # 官方原始历史等
                                t = m.get("timestamp") or m.get("ts")
                                # 规范里只有role/content
                                content = m.get("content", "")
                                # 尝试补充sender（若有的话）
                                if isinstance(m.get("sender"), dict):
                                    sid = str(m["sender"].get("user_id", ""))
                                    sname = m["sender"].get("nickname", "") or ""
                            # 时间格式化
                            if t:
                                try:
                                    timestr = time.strftime(
                                        "%Y-%m-%d %H:%M:%S", time.localtime(float(t))
                                    )
                                except Exception:
                                    timestr = "n/a"
                            else:
                                timestr = "n/a"
                            # 是否为机器人自己的消息
                            is_bot = sid and sid == bot_id_for_check
                            # 文本摘要
                            snippet = str(content).replace("\n", " ")
                            if len(snippet) > 80:
                                snippet = snippet[:80] + "…"
                            line = (
                                f"  [{idx}] t={timestr} sender={sname}(ID:{sid}) bot={is_bot} "
                                f"gid={gid} self_id={selfid} sess={sess} mid={mid} len={len(content)} txt={snippet}"
                            )
                            lines.append(line)
                        except Exception as _inner:
                            lines.append(f"  [预览异常] {type(m)}")
                    if lines:
                        for ln in lines:
                            logger.info(ln)
                except Exception:
                    pass

        # 🔧 根据配置决定是否获取历史
        # max_context == 0: 不获取历史，只用当前消息
        # max_context == -1: 不限制，获取所有历史
        # max_context > 0: 限制为指定数量

        # 🆕 v1.2.0: 准备缓存消息用于新的统一获取方法
        cached_astrbot_messages_for_fallback = []
        if not (isinstance(max_context, int) and max_context == 0):
            if (
                chat_id in self.pending_messages_cache
                and len(self.pending_messages_cache[chat_id]) > 1
            ):
                # 🔧 修复：过滤过期的缓存消息，避免使用已过期但未清理的消息
                cached_messages_raw = ProactiveChatManager.filter_expired_cached_messages(
                    self.pending_messages_cache[chat_id][:-1]
                )
                for cached_msg in cached_messages_raw:
                    if isinstance(cached_msg, dict):
                        try:
                            msg_obj = AstrBotMessage()
                            msg_obj.message_str = cached_msg.get("content", "")
                            msg_obj.platform_name = event.get_platform_name()
                            msg_obj.timestamp = cached_msg.get(
                                "message_timestamp"
                            ) or cached_msg.get("timestamp", time.time())
                            msg_obj.type = (
                                MessageType.GROUP_MESSAGE
                                if not event.is_private_chat()
                                else MessageType.FRIEND_MESSAGE
                            )
                            if not event.is_private_chat():
                                msg_obj.group_id = event.get_group_id()
                            msg_obj.self_id = event.get_self_id()
                            msg_obj.session_id = (
                                event.session_id
                                if hasattr(event, "session_id")
                                else chat_id
                            )
                            msg_obj.message_id = (
                                f"cached_{cached_msg.get('timestamp', time.time())}"
                            )
                            sender_id = cached_msg.get("sender_id", "")
                            sender_name = cached_msg.get("sender_name", "未知用户")
                            if sender_id:
                                msg_obj.sender = MessageMember(
                                    user_id=sender_id, nickname=sender_name
                                )
                            cached_astrbot_messages_for_fallback.append(msg_obj)
                        except Exception as e:
                            if self.debug_mode:
                                logger.warning(f"转换缓存消息失败: {e}")
                    elif isinstance(cached_msg, AstrBotMessage):
                        cached_astrbot_messages_for_fallback.append(cached_msg)

        # 🆕 v1.2.0: 使用新的统一方法获取历史消息（优先官方存储，回退自定义存储）
        if isinstance(max_context, int) and max_context == 0:
            # 配置为0，不获取任何历史上下文
            history_messages = []
            if self.debug_mode:
                logger.info("  配置为0，跳过历史上下文获取")
        else:
            # 使用新的统一方法：优先官方存储，回退自定义存储，自动拼接缓存消息
            history_messages = await ContextManager.get_history_messages_with_fallback(
                event=event,
                max_messages=max_context,
                context=self.context,
                cached_messages=cached_astrbot_messages_for_fallback,
            )
            if self.debug_mode:
                _log_msgs("历史-统一获取（官方优先+缓存）", history_messages)

        # 🆕 v1.2.0: 官方历史已在 get_history_messages_with_fallback 中处理
        # 以下为兼容性代码：尝试从 conversation_manager 获取额外的对话历史
        # 注意：message_history_manager 和 conversation_manager 是两个不同的存储
        # - message_history_manager: 存储平台消息历史（platform_message_history 表）
        # - conversation_manager: 存储 LLM 对话历史（conversations 表）
        if not (isinstance(max_context, int) and max_context == 0):
            try:
                cm = self.context.conversation_manager
                if cm:
                    uid = event.unified_msg_origin
                    cid = await cm.get_curr_conversation_id(uid)
                    if cid:
                        conv = await cm.get_conversation(
                            unified_msg_origin=uid, conversation_id=cid
                        )
                        official_history = None
                        if conv is not None:
                            if getattr(conv, "history", None):
                                try:
                                    official_history = json.loads(conv.history)
                                except Exception:
                                    official_history = None
                            if official_history is None and getattr(
                                conv, "content", None
                            ):
                                if isinstance(conv.content, list):
                                    official_history = conv.content
                                else:
                                    try:
                                        official_history = json.loads(conv.content)
                                    except Exception:
                                        official_history = None
                        if (
                            isinstance(official_history, list)
                            and len(official_history) > 0
                        ):
                            if self.debug_mode:
                                try:
                                    logger.info(
                                        f"  官方历史原始条数: {len(official_history)}"
                                    )
                                    if isinstance(max_context, int) and max_context > 0:
                                        logger.info(
                                            f"  官方历史选取窗口: 末尾 {max_context} 条"
                                        )
                                    else:
                                        logger.info("  官方历史选取窗口: 全量")
                                    _raw_prev = []
                                    for r in official_history[
                                        -min(5, len(official_history)) :
                                    ]:
                                        _s = (
                                            r.get("content", "")
                                            if isinstance(r, dict)
                                            else str(r)
                                        )
                                        _s = str(_s).replace("\n", " ")
                                        if len(_s) > 80:
                                            _s = _s[:80] + "…"
                                        _raw_prev.append(_s)
                                    if _raw_prev:
                                        logger.info(
                                            "  官方历史-原始预览: "
                                            + " | ".join(_raw_prev)
                                        )
                                except Exception:
                                    pass
                            hist_msgs = []
                            self_id = event.get_self_id()
                            platform_name = event.get_platform_name()
                            is_private_chat = event.is_private_chat()
                            default_user_name = "对方" if is_private_chat else "群友"
                            history_user_prefix = "history_user"
                            # 根据 max_context 决定截取范围
                            # -1: 不限制，使用全量
                            # > 0: 限制为指定数量
                            if isinstance(max_context, int):
                                if max_context == -1:
                                    msgs_iter = official_history  # 不限制
                                elif max_context > 0:
                                    msgs_iter = official_history[
                                        -max_context:
                                    ]  # 限制数量
                                else:
                                    msgs_iter = []  # max_context == 0 时不应走到这里
                            else:
                                msgs_iter = official_history  # 非整数时默认全量
                            for idx, msg in enumerate(msgs_iter):
                                if (
                                    isinstance(msg, dict)
                                    and "role" in msg
                                    and "content" in msg
                                ):
                                    m = AstrBotMessage()
                                    m.message_str = msg["content"]
                                    m.platform_name = platform_name
                                    _ts = (
                                        msg.get("timestamp")
                                        or msg.get("ts")
                                        or msg.get("time")
                                    )
                                    try:
                                        m.timestamp = (
                                            int(float(_ts)) if _ts else int(time.time())
                                        )
                                    except Exception:
                                        m.timestamp = int(time.time())
                                    m.type = (
                                        MessageType.GROUP_MESSAGE
                                        if not is_private_chat
                                        else MessageType.FRIEND_MESSAGE
                                    )
                                    if not is_private_chat:
                                        m.group_id = event.get_group_id()
                                    m.self_id = self_id
                                    m.session_id = getattr(
                                        event, "session_id", None
                                    ) or (
                                        event.get_sender_id()
                                        if is_private_chat
                                        else event.get_group_id()
                                    )
                                    raw_message_id = (
                                        msg.get("message_id")
                                        or msg.get("id")
                                        or msg.get("mid")
                                        or ""
                                    )
                                    m.message_id = (
                                        str(raw_message_id)
                                        or f"official_{idx}_{m.timestamp}"
                                    )

                                    if msg["role"] == "assistant":
                                        m.sender = MessageMember(
                                            user_id=self_id, nickname="AI"
                                        )
                                    else:
                                        sender_info = (
                                            msg.get("sender")
                                            if isinstance(msg.get("sender"), dict)
                                            else None
                                        )
                                        sender_id = None
                                        sender_name = None
                                        if sender_info:
                                            sender_id = (
                                                sender_info.get("user_id")
                                                or sender_info.get("id")
                                                or sender_info.get("uid")
                                                or sender_info.get("qq")
                                                or sender_info.get("uin")
                                            )
                                            sender_name = sender_info.get(
                                                "nickname"
                                            ) or sender_info.get("name")
                                        sender_id = (
                                            str(sender_id)
                                            if sender_id is not None
                                            else f"{history_user_prefix}_{idx}"
                                        )
                                        sender_name = sender_name or default_user_name
                                        m.sender = MessageMember(
                                            user_id=sender_id,
                                            nickname=sender_name,
                                        )
                                    hist_msgs.append(m)
                            if hist_msgs:
                                if history_messages:
                                    existing_contents = set()
                                    for _existing in history_messages:
                                        content = None
                                        if isinstance(_existing, AstrBotMessage):
                                            content = getattr(
                                                _existing, "message_str", None
                                            )
                                        elif isinstance(_existing, dict):
                                            content = _existing.get("content")
                                        if content:
                                            existing_contents.add(content)

                                    for hm in hist_msgs:
                                        if (
                                            hm.message_str
                                            and hm.message_str in existing_contents
                                        ):
                                            continue
                                        history_messages.append(hm)
                                        if hm.message_str:
                                            existing_contents.add(hm.message_str)
                                else:
                                    history_messages = hist_msgs
                                if self.debug_mode:
                                    logger.info("  已合并官方历史")
                                    _log_msgs("历史-合并官方", history_messages)
                        elif self.debug_mode:
                            logger.info("  未获取到官方历史")
            except Exception as _:
                pass
        else:
            if self.debug_mode:
                logger.info("  跳过官方历史读取: max_context_messages=0")

        # 🆕 v1.2.0: 缓存消息已在 get_history_messages_with_fallback 中处理
        # 以下代码保留用于兼容性，但实际上缓存已经在上面合并
        cached_messages_to_merge = []
        if isinstance(max_context, int) and max_context == 0:
            if self.debug_mode:
                logger.info("  跳过缓存合并: max_context_messages=0")
        else:
            if (
                chat_id in self.pending_messages_cache
                and len(self.pending_messages_cache[chat_id]) > 1
            ):
                # 🔧 修复：过滤过期的缓存消息，避免使用已过期但未清理的消息
                cached_messages = ProactiveChatManager.filter_expired_cached_messages(
                    self.pending_messages_cache[chat_id][:-1]
                )
                cached_candidates_count = len(cached_messages) if cached_messages else 0
                dedup_skipped = 0
                if cached_messages and history_messages:
                    history_contents = set()
                    for msg in history_messages:
                        if isinstance(msg, AstrBotMessage) and hasattr(
                            msg, "message_str"
                        ):
                            history_contents.add(msg.message_str)
                        elif isinstance(msg, dict) and "content" in msg:
                            history_contents.add(msg["content"])

                    for cached_msg in cached_messages:
                        if isinstance(cached_msg, dict) and "content" in cached_msg:
                            if cached_msg["content"] not in history_contents:
                                cached_messages_to_merge.append(cached_msg)
                            else:
                                dedup_skipped += 1
                elif cached_messages:
                    cached_messages_to_merge = cached_messages
                if self.debug_mode:
                    logger.info(
                        f"  缓存候选: {cached_candidates_count} 条, 去重跳过: {dedup_skipped} 条, 计划合并: {len(cached_messages_to_merge)} 条"
                    )

        # 初始化变量，避免 UnboundLocalError
        cached_count = 0
        original_history_count = len(history_messages) if history_messages else 0

        if cached_messages_to_merge:
            if history_messages is None:
                history_messages = []

            # 🆕 优化：将缓存消息转换为 AstrBotMessage 对象，并按时间戳排序插入
            cached_astrbot_messages = []
            for cached_msg in cached_messages_to_merge:
                if isinstance(cached_msg, dict):
                    try:
                        # 创建 AstrBotMessage 对象
                        msg_obj = AstrBotMessage()
                        msg_obj.message_str = cached_msg.get("content", "")
                        msg_obj.platform_name = event.get_platform_name()
                        # 使用 message_timestamp（原始消息时间戳），如果没有则使用缓存时间戳
                        msg_obj.timestamp = cached_msg.get(
                            "message_timestamp"
                        ) or cached_msg.get("timestamp", time.time())
                        msg_obj.type = (
                            MessageType.GROUP_MESSAGE
                            if not event.is_private_chat()
                            else MessageType.FRIEND_MESSAGE
                        )
                        if not event.is_private_chat():
                            msg_obj.group_id = event.get_group_id()
                        msg_obj.self_id = event.get_self_id()
                        msg_obj.session_id = (
                            event.session_id
                            if hasattr(event, "session_id")
                            else chat_id
                        )
                        msg_obj.message_id = (
                            f"cached_{cached_msg.get('timestamp', time.time())}"
                        )

                        # 设置发送者信息
                        sender_id = cached_msg.get("sender_id", "")
                        sender_name = cached_msg.get("sender_name", "未知用户")
                        if sender_id:
                            msg_obj.sender = MessageMember(
                                user_id=sender_id, nickname=sender_name
                            )

                        cached_astrbot_messages.append(msg_obj)
                    except Exception as e:
                        logger.warning(
                            f"转换缓存消息为 AstrBotMessage 失败: {e}，跳过该消息"
                        )
                else:
                    # 如果已经是 AstrBotMessage 对象，直接添加
                    cached_astrbot_messages.append(cached_msg)

            # 🆕 合并历史消息和缓存消息，并按时间戳排序
            # 这样可以形成完整的时间线，避免上下文跳跃
            if cached_astrbot_messages:
                # 记录原始历史消息数量（用于智能截断）
                original_history_count = len(history_messages)
                cached_count = len(cached_astrbot_messages)

                # 合并所有消息
                all_messages = history_messages + cached_astrbot_messages

                # 按时间戳排序（确保时间线连续）
                all_messages.sort(
                    key=lambda msg: msg.timestamp
                    if hasattr(msg, "timestamp") and msg.timestamp
                    else 0
                )

                history_messages = all_messages

                if self.debug_mode:
                    logger.info(f"  合并缓存消息: {cached_count} 条")
                    logger.info(f"  已按时间戳排序，形成完整上下文时间线")
                    logger.info(
                        f"  合并前: 历史={original_history_count}, 缓存={cached_count}"
                    )
                    _log_msgs("历史-合并缓存后（已排序）", history_messages)

        # 🆕 优化：应用上下文限制 - 智能截断策略
        # 🔧 修复：统一按时间排序后删除最早的消息，不区分缓存或历史
        # 这样可以保证时间连续性，避免上下文割裂
        # max_context == -1: 不限制，保留所有消息
        # max_context == 0: 已在获取阶段处理，这里不应有消息
        # max_context > 0: 限制为指定数量
        if (
            history_messages
            and isinstance(max_context, int)
            and max_context > 0
            and len(history_messages) > max_context
        ):
            before_cnt = len(history_messages)

            # 统一策略：删除最早的消息，只保留最新的 max_context 条
            # 由于消息已经按时间戳排序，直接截取末尾即可
            history_messages = history_messages[-max_context:]

            if self.debug_mode:
                removed_cnt = before_cnt - len(history_messages)
                logger.info(
                    f"  智能截断: {before_cnt} -> {len(history_messages)} "
                    f"(按时间顺序删除最早的 {removed_cnt} 条消息，保留最新的 {max_context} 条)"
                )
                _log_msgs("历史-截断后", history_messages)
        elif self.debug_mode:
            if isinstance(max_context, int) and max_context == -1:
                logger.info("  配置为-1，不限制上下文数量")
            elif isinstance(max_context, int) and max_context == 0:
                logger.info("  配置为0，无历史上下文")
            else:
                logger.info("  未触发上下文限制")

        if self.debug_mode:
            logger.info(
                f"  最终历史消息: {len(history_messages) if history_messages else 0} 条"
            )

        # 格式化上下文
        bot_id = event.get_self_id()
        formatted_context = await ContextManager.format_context_for_ai(
            history_messages,
            message_text_for_ai,
            bot_id,
            include_timestamp=self.include_timestamp,
            include_sender_info=self.include_sender_info,
        )

        if self.debug_mode:
            logger.info(f"  格式化后长度: {len(formatted_context)} 字符")
            try:
                _pv = formatted_context or ""
                snippet = _pv[:300].replace("\n", " ")
                logger.info(
                    "  格式化后预览: " + snippet + ("…" if len(_pv) > 300 else "")
                )
            except Exception:
                pass

        # 返回：原始消息文本、处理后的消息（不含元数据，用于保存）、格式化的上下文、图片URL列表、历史消息列表
        return (
            True,
            original_message_text,
            processed_message,
            formatted_context,
            image_urls,
            history_messages,
        )

    async def _generate_and_send_reply(
        self,
        event: AstrMessageEvent,
        formatted_context: str,
        message_text: str,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        is_at_message: bool = False,
        has_trigger_keyword: bool = False,
        image_urls: list = None,
        history_messages: list = None,
        current_message_cache: dict = None,  # 🔧 修复：当前消息缓存副本，避免并发竞争
        conversation_fatigue_info: dict = None,  # 🆕 v1.2.3: 对话疲劳信息
    ):
        """
        生成并发送回复，保存历史

        Args:
            event: 消息事件
            formatted_context: 格式化的上下文
            message_text: 消息文本
            platform_name: 平台名称
            is_private: 是否私聊
            chat_id: 聊天ID
            is_at_message: 是否@消息
            has_trigger_keyword: 是否包含触发关键词
            image_urls: 图片URL列表（用于多模态AI）
            history_messages: 历史消息列表（AstrBotMessage对象列表，用于contexts）
            current_message_cache: 当前消息的缓存副本（避免并发竞争导致缓存被清空）
            conversation_fatigue_info: 对话疲劳信息（用于生成收尾话语提示）

        Returns:
            生成器，用于yield回复
        """
        # 记录开始时间
        _process_start_time = time.time()

        # 如果image_urls为None，初始化为空列表
        if image_urls is None:
            image_urls = []
        # 注入记忆
        final_message = formatted_context
        try:
            ckey = ProbabilityManager.get_chat_key(platform_name, is_private, chat_id)

            # 🔧 修复：pre_decision 模式下，优先使用缓存的上下文（已植入记忆）
            # 无论是否跳过决策AI，只要是 pre_decision 模式且缓存存在，就应该使用缓存
            if (
                self.enable_memory_injection
                and self.memory_insertion_timing == "pre_decision"
            ):
                if (
                    hasattr(self, "_pre_decision_context_by_chat")
                    and ckey in self._pre_decision_context_by_chat
                ):
                    final_message = self._pre_decision_context_by_chat.pop(
                        ckey, formatted_context
                    )
                    if self.debug_mode:
                        logger.info(
                            "【步骤10.5】使用pre_decision缓存的上下文（已植入记忆）"
                        )

            # 清理跳过决策AI的标记
            if (
                hasattr(self, "_ai_decision_skipped")
                and ckey in self._ai_decision_skipped
            ):
                try:
                    self._ai_decision_skipped.discard(ckey)
                except Exception:
                    pass
        except Exception:
            pass

        if (
            self.enable_memory_injection
            and self.memory_insertion_timing == "post_decision"
        ):
            if self.debug_mode:
                logger.info("【步骤11】注入记忆内容")

            # 获取记忆插件配置（使用已提取的实例变量）
            memory_mode = self.memory_plugin_mode
            livingmemory_top_k = self.livingmemory_top_k

            if MemoryInjector.check_memory_plugin_available(
                self.context, mode=memory_mode
            ):
                memories = await MemoryInjector.get_memories(
                    self.context, event, mode=memory_mode, top_k=livingmemory_top_k
                )
                if memories:
                    final_message = MemoryInjector.inject_memories_to_message(
                        final_message, memories
                    )
                    if self.debug_mode:
                        logger.info(
                            f"  已注入记忆({memory_mode}模式),长度增加: {len(final_message) - len(formatted_context)} 字符"
                        )
            else:
                logger.warning(
                    f"记忆插件({memory_mode}模式)未安装或不可用,跳过记忆注入"
                )

        # 注入工具信息
        if self.enable_tools_reminder:
            if self.debug_mode:
                logger.info("【步骤12】注入工具信息")

            old_len = len(final_message)
            final_message = ToolsReminder.inject_tools_to_message(
                final_message, self.context
            )
            if self.debug_mode:
                logger.info(
                    f"  已注入工具信息,长度增加: {len(final_message) - old_len} 字符"
                )

        # 🆕 v1.0.2: 注入情绪状态（如果启用）
        if self.mood_enabled and self.mood_tracker:
            if self.debug_mode:
                logger.info("【步骤12.5】注入情绪状态")

            # 使用格式化后的上下文来判断情绪
            final_message = self.mood_tracker.inject_mood_to_prompt(
                chat_id, final_message, formatted_context
            )

        # 调用AI生成回复
        if self.debug_mode:
            logger.info("【步骤13】调用AI生成回复")
            logger.info(f"  最终消息长度: {len(final_message)} 字符")

        _start_time = time.time()

        ai_error_flag = False
        message_id_for_error = None
        try:
            message_id_for_error = self._get_message_id(event)
        except Exception:
            message_id_for_error = None

        try:
            reply_result = await ReplyHandler.generate_reply(
                event,
                self.context,
                final_message,
                self.reply_ai_extra_prompt,
                self.reply_ai_prompt_mode,
                image_urls,  # 传递图片URL列表
                include_sender_info=self.include_sender_info,
                history_messages=history_messages,  # 🔧 修复：传递历史消息用于构建contexts
                conversation_fatigue_info=conversation_fatigue_info,  # 🆕 v1.2.3: 传递疲劳信息
            )
        except Exception as e:
            ai_error_flag = True
            logger.error(f"生成AI回复时发生未捕获异常: {e}", exc_info=True)
            reply_result = event.plain_result(f"生成回复时发生错误: {str(e)}")

        if (
            not ai_error_flag
            and hasattr(reply_result, "is_llm_result")
            and hasattr(reply_result, "chain")
        ):
            try:
                if not reply_result.is_llm_result():
                    parts = []
                    for comp in getattr(reply_result, "chain", []) or []:
                        if hasattr(comp, "text"):
                            parts.append(comp.text)
                    err_text = "".join(parts)
                    if "生成回复时发生错误" in err_text:
                        ai_error_flag = True
            except Exception:
                pass

        if ai_error_flag and message_id_for_error:
            try:
                if not hasattr(self, "_ai_error_message_ids"):
                    self._ai_error_message_ids = set()
                self._ai_error_message_ids.add(message_id_for_error)
            except Exception:
                pass

        _elapsed = time.time() - _start_time
        if self.debug_mode:
            logger.info(f"【步骤13】AI回复生成完成，耗时: {_elapsed:.2f}秒")
        elif _elapsed > self.reply_generation_timeout_warning:
            logger.warning(
                f"⚠️ AI回复生成耗时异常: {_elapsed:.2f}秒（超过{self.reply_generation_timeout_warning}秒）"
            )

        # 🆕 v1.0.2: 处理回复文本（添加错别字）
        if self.typo_enabled and self.typo_generator and reply_result:
            if self.debug_mode:
                logger.info("【步骤13.5】处理回复文本（可能添加错别字）")

            # 提取回复文本
            original_reply = str(reply_result)
            processed_reply = self.typo_generator.process_reply(original_reply)

            if processed_reply != original_reply:
                # 回复被修改了，更新reply_result
                reply_result = processed_reply
                if self.debug_mode:
                    logger.info("  已添加错别字")

        # 🆕 v1.0.2: 模拟打字延迟
        if self.typing_simulator_enabled and self.typing_simulator and reply_result:
            if isinstance(reply_result, str):
                if self.debug_mode:
                    logger.info("【步骤13.6】模拟打字延迟")

                _typing_start = time.time()
                await self.typing_simulator.simulate_if_needed(reply_result)
                _typing_elapsed = time.time() - _typing_start

                if self.debug_mode:
                    logger.info(
                        f"【步骤13.6】打字延迟完成，耗时: {_typing_elapsed:.2f}秒"
                    )
                elif _typing_elapsed > self.typing_delay_timeout_warning:
                    logger.warning(
                        f"⚠️ 打字延迟耗时异常: {_typing_elapsed:.2f}秒（超过{self.typing_delay_timeout_warning}秒）"
                    )
            elif self.debug_mode:
                logger.info("【步骤13.6】跳过打字延迟（非字符串回复）")

        # 保存用户消息（从缓存读取并添加元数据）
        if self.debug_mode:
            logger.info("【步骤14】保存用户消息")

        try:
            # 🔧 修复：优先使用缓存副本，避免并发竞争导致缓存被清空
            message_to_save = ""

            # 优先使用传入的缓存副本
            last_cached = current_message_cache

            # 如果没有缓存副本，尝试从共享缓存读取（向后兼容）
            if not last_cached:
                if (
                    chat_id in self.pending_messages_cache
                    and len(self.pending_messages_cache[chat_id]) > 0
                ):
                    last_cached = self.pending_messages_cache[chat_id][-1]
                    if self.debug_mode:
                        logger.info(
                            "⚠️ [并发警告] 使用共享缓存（可能已被清空），建议检查并发逻辑"
                        )
            elif self.debug_mode:
                logger.info("🔒 [并发保护] 使用缓存副本，避免竞争")

            if (
                last_cached
                and isinstance(last_cached, dict)
                and "content" in last_cached
            ):
                # 获取处理后的消息内容（不含元数据）
                raw_content = last_cached["content"]

                if self.debug_mode:
                    logger.info(f"【步骤14-读缓存】内容: {raw_content[:100]}")
                else:
                    logger.info("🟢 读取缓存中")

                # 使用缓存中的发送者信息添加元数据
                # 🆕 v1.0.4: 根据缓存中的触发方式信息确定trigger_type
                # 注意：需要同时检查 has_trigger_keyword 来正确判断触发方式
                trigger_type = None
                if last_cached.get("has_trigger_keyword"):
                    # 关键词触发（优先级高于@消息判断）
                    trigger_type = "keyword"
                elif last_cached.get("is_at_message"):
                    # 真正的@消息触发
                    trigger_type = "at"
                else:
                    # 概率触发（AI主动回复）
                    trigger_type = "ai_decision"

                message_to_save = MessageProcessor.add_metadata_from_cache(
                    raw_content,
                    last_cached.get("sender_id", event.get_sender_id()),
                    last_cached.get("sender_name", event.get_sender_name()),
                    last_cached.get("message_timestamp")
                    or last_cached.get("timestamp"),
                    self.include_timestamp,
                    self.include_sender_info,
                    last_cached.get("mention_info"),  # 传递@信息
                    trigger_type,  # 🆕 v1.0.4: 传递触发方式
                    last_cached.get("poke_info"),  # 🆕 v1.0.9: 传递戳一戳信息
                )

                # 清理系统提示（保存前过滤）
                message_to_save = MessageCleaner.clean_message(message_to_save)

                if self.debug_mode:
                    logger.info(f"【步骤14-加元数据后】内容: {message_to_save[:150]}")

            # 如果从缓存获取失败，使用当前处理后的消息并添加元数据
            if not message_to_save:
                logger.warning("⚠️ 缓存中无消息，使用当前处理后的消息（这不应该发生！）")
                # 🆕 v1.0.4: 确定触发方式
                trigger_type = None
                if has_trigger_keyword:
                    # 关键词触发（优先级高于@消息判断）
                    trigger_type = "keyword"
                elif is_at_message:
                    # 真正的@消息触发
                    trigger_type = "at"
                else:
                    # 概率触发（AI主动回复）
                    trigger_type = "ai_decision"

                message_to_save = MessageProcessor.add_metadata_to_message(
                    event,
                    message_text,  # message_text 就是 processed_message
                    self.include_timestamp,
                    self.include_sender_info,
                    None,  # 这种情况下没有mention_info（从event提取的fallback）
                    trigger_type,  # 🆕 v1.0.4: 传递触发方式
                    None,  # 🆕 v1.0.9: 无法获取poke_info（fallback情况）
                )

                # 清理系统提示（保存前过滤）
                message_to_save = MessageCleaner.clean_message(message_to_save)

            if self.debug_mode:
                logger.info(f"  准备保存的完整消息: {message_to_save[:300]}...")

            await ContextManager.save_user_message(event, message_to_save, self.context)
            if self.debug_mode:
                logger.info(
                    f"  ✅ 用户消息已保存到自定义存储: {len(message_to_save)} 字符"
                )
        except Exception as e:
            logger.error(f"保存用户消息时发生错误: {e}")

        # 🆕 发送前过滤检查：防止直接转发用户消息和重复发送相同回复
        # 提取回复文本（仅当为字符串类型时；LLM请求结果在装饰阶段处理）
        reply_text = ""
        is_provider_request = False
        if reply_result:
            is_provider_request = isinstance(reply_result, ProviderRequest)
            if isinstance(reply_result, str):
                reply_text = reply_result.strip()

        # 重复判断标准：严格字符串一致（不做大小写、标点等归一化，仅移除首尾空白）

        # 检查1: 回复是否与用户消息相同（防止直接转发）
        # 仅对字符串型即时回复进行检查；LLM结果在装饰阶段处理
        if reply_text and not is_provider_request:
            # 获取用户原始消息（严格比较，仅去除首尾空白）
            user_message_clean = message_text.strip()

            if reply_text == user_message_clean:
                logger.info("[消息过滤]回复与用户消息相同，已过滤")
                if self.debug_mode:
                    logger.warning(
                        f"🚫 [消息过滤] 检测到回复与用户消息相同，跳过发送\n"
                        f"  用户消息: {user_message_clean[:100]}...\n"
                        f"  AI回复: {reply_text[:100]}..."
                    )
                else:
                    # 非debug模式下也显示部分信息
                    logger.info(f"  用户消息: {user_message_clean[:50]}...")
                    logger.info(f"  AI回复: {reply_text[:50]}...")
                # 不发送，直接返回
                return

        # 检查2: 回复是否与最近发送的回复重复（防止重复发送相同答案）
        # 仅对字符串型即时回复进行检查；LLM结果在装饰阶段处理
        # 🔧 使用可配置的重复消息检测参数
        # 🔧 重要：重复检测只拦截发送，不影响后续流程（概率调整、注意力记录等）
        is_duplicate_blocked = False
        if reply_text and not is_provider_request and self.enable_duplicate_filter:
            # 获取或初始化该会话的回复缓存
            if chat_id not in self.recent_replies_cache:
                self.recent_replies_cache[chat_id] = []

            current_time = time.time()
            
            # 根据配置决定是否启用时效性过滤
            if self.enable_duplicate_time_limit:
                # 清理过期的回复记录（使用配置的时效）
                time_limit = max(60, self.duplicate_filter_time_limit)  # 最少60秒
                self.recent_replies_cache[chat_id] = [
                    reply
                    for reply in self.recent_replies_cache[chat_id]
                    if current_time - reply.get("timestamp", 0) < time_limit
                ]

            # 检查是否与最近N条回复重复（使用配置的条数，严格全等匹配）
            check_count = max(1, self.duplicate_filter_check_count)  # 最少检查1条
            for recent_reply in self.recent_replies_cache[chat_id][-check_count:]:
                recent_content = recent_reply.get("content", "")
                recent_timestamp = recent_reply.get("timestamp", 0)
                
                # 如果启用时效性判断，检查消息是否在时效内
                if self.enable_duplicate_time_limit:
                    time_limit = max(60, self.duplicate_filter_time_limit)
                    if current_time - recent_timestamp >= time_limit:
                        continue  # 超过时效，跳过此条
                
                if recent_content and reply_text == recent_content.strip():
                    logger.info("[消息过滤]回复与最近发送的回复重复，已拦截发送（后续流程继续执行）")
                    if self.debug_mode:
                        logger.warning(
                            f"🚫 [消息过滤] 检测到回复与最近发送的回复重复，跳过发送\n"
                            f"  最近回复: {recent_content[:100]}...\n"
                            f"  当前回复: {reply_text[:100]}..."
                        )
                    else:
                        # 非debug模式下也显示部分信息
                        logger.info(f"  最近回复: {recent_content[:50]}...")
                        logger.info(f"  当前回复: {reply_text[:50]}...")
                    # 🔧 设置标记，跳过发送但继续后续流程
                    is_duplicate_blocked = True
                    break

        # 发送回复
        # 🔧 如果是重复消息，跳过发送但继续后续流程
        if not is_duplicate_blocked:
            if reply_result is None:
                logger.error("❌ [发送失败] reply_result为None，无法发送回复")
                if self.debug_mode:
                    logger.error("  这通常是因为ReplyHandler.generate_reply返回了None")
                return

            if self.debug_mode:
                logger.info(
                    f"【步骤13.9】准备发送回复，类型: {type(reply_result).__name__}"
                )

            yield reply_result

            if self.debug_mode:
                logger.info("【步骤13.9】回复已通过yield发送")
        else:
            if self.debug_mode:
                logger.info("【步骤13.9】跳过发送回复（重复消息已拦截），继续后续流程")

        # 🆕 记录已发送的回复（用于后续去重检查）
        # 仅记录字符串型即时回复；LLM结果在 after_message_sent 钩子中记录
        # 🔧 只在非重复消息时记录到缓存
        if reply_text and not is_provider_request and not is_duplicate_blocked:
            if chat_id not in self.recent_replies_cache:
                self.recent_replies_cache[chat_id] = []

            # 添加到缓存
            self.recent_replies_cache[chat_id].append(
                {"content": reply_text, "timestamp": time.time()}
            )

            # 🔒 限制缓存大小（保留配置条数的2倍，最少10条，但不超过硬上限）
            max_cache_size = min(
                max(10, self.duplicate_filter_check_count * 2),
                self._DUPLICATE_CACHE_SIZE_LIMIT
            )
            if len(self.recent_replies_cache[chat_id]) > max_cache_size:
                # 丢弃最旧的消息，保留最新的
                self.recent_replies_cache[chat_id] = self.recent_replies_cache[chat_id][
                    -max_cache_size:
                ]

            if self.debug_mode:
                logger.info(
                    f"【消息过滤】已记录回复到缓存，当前缓存数: {len(self.recent_replies_cache[chat_id])}"
                )

        # 🆕 v1.1.0: 记录AI回复（用于主动对话功能）
        if self.proactive_enabled:
            chat_key = ProbabilityManager.get_chat_key(
                platform_name, is_private, chat_id
            )
            # 在实际记录回复前，若处于主动对话临时提升阶段，则在此时机取消临时提升（AI已决定回复）
            ProactiveChatManager.check_and_handle_reply_after_proactive(
                chat_key, self.config, force=True
            )
            ProactiveChatManager.record_bot_reply(chat_key, is_proactive=False)
            if self.debug_mode:
                logger.info(f"[主动对话] 已记录AI回复（普通回复）")

        # 调整概率 / 记录注意力（二选一）
        attention_enabled = self.enable_attention_mechanism

        if attention_enabled:
            # 启用注意力机制：使用注意力机制，不使用传统概率提升
            if self.debug_mode:
                logger.info("【步骤15】跳过传统概率调整，使用注意力机制")
                logger.info("【步骤16】记录被回复用户信息（注意力机制-增强版）")

            # 获取被回复的用户信息
            replied_user_id = event.get_sender_id()
            replied_user_name = event.get_sender_name()

            # 获取消息预览（用于注意力机制的上下文记录）
            message_preview = message_text[:50] if message_text else ""

            await AttentionManager.record_replied_user(
                platform_name,
                is_private,
                chat_id,
                replied_user_id,
                replied_user_name,
                message_preview=message_preview,
                message_text=message_text,  # v1.1.2: 传递完整消息用于情感检测
                attention_boost_step=self.attention_boost_step,
                attention_decrease_step=self.attention_decrease_step,
                emotion_boost_step=self.emotion_boost_step,
            )

            # 注意：疲劳重置已移至 AI 决策确认回复后、生成回复前执行
            # 这样可以确保：1. 重置在 record_replied_user 之前 2. 不受跳过逻辑影响

            if self.debug_mode:
                logger.info(
                    f"【步骤16】已记录: {replied_user_name}(ID: {replied_user_id}), 消息预览: {message_preview}"
                )
        else:
            # 未启用注意力机制：使用传统概率提升
            if self.debug_mode:
                logger.info("【步骤15】调整读空气概率（传统模式）")

            await ProbabilityManager.boost_probability(
                platform_name,
                is_private,
                chat_id,
                self.after_reply_probability,
                self.probability_duration,
            )

            if self.debug_mode:
                logger.info("【步骤15】概率调整完成")

        # 🆕 v1.0.2: 频率动态调整检查
        if self.frequency_adjuster_enabled and self.frequency_adjuster:
            try:
                # 使用完整的会话标识，确保不同会话的状态隔离
                chat_key = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )

                # 检查是否需要进行频率调整
                message_count = self.frequency_adjuster.get_message_count(chat_key)

                if self.frequency_adjuster.should_check_frequency(
                    chat_key, message_count
                ):
                    if self.debug_mode:
                        _freq_start = time.time()
                        logger.info("【步骤17】开始频率动态调整检查")

                    # 获取最近的消息用于分析（使用配置的数量）
                    analysis_msg_count = self.frequency_analysis_message_count

                    # 🔧 配置矫正：处理异常值
                    if isinstance(analysis_msg_count, int) and analysis_msg_count < -1:
                        logger.warning(
                            f"⚠️ [频率调整-配置矫正] frequency_analysis_message_count 配置值 {analysis_msg_count} 小于 -1，已矫正为 -1（不限制）"
                        )
                        analysis_msg_count = -1

                    # 🆕 v1.2.0: 使用新的统一方法获取历史消息（优先官方存储，回退自定义存储）
                    # 根据配置决定是否获取历史
                    if isinstance(analysis_msg_count, int) and analysis_msg_count == 0:
                        # 配置为0，不进行频率分析
                        if self.debug_mode:
                            logger.info("[频率调整] 配置为0，跳过频率分析")
                        recent_messages = []
                    else:
                        # 准备缓存消息
                        cached_astrbot_messages_for_freq = []
                        if (
                            chat_id in self.pending_messages_cache
                            and self.pending_messages_cache[chat_id]
                        ):
                            # 🔧 修复：过滤过期的缓存消息，避免使用已过期但未清理的消息
                            cached_messages_raw = ProactiveChatManager.filter_expired_cached_messages(
                                self.pending_messages_cache[chat_id]
                            )
                            for cached_msg in cached_messages_raw:
                                if isinstance(cached_msg, dict):
                                    try:
                                        msg_obj = AstrBotMessage()
                                        msg_obj.message_str = cached_msg.get(
                                            "content", ""
                                        )
                                        msg_obj.platform_name = (
                                            event.get_platform_name()
                                        )
                                        msg_obj.timestamp = cached_msg.get(
                                            "message_timestamp"
                                        ) or cached_msg.get("timestamp", time.time())
                                        msg_obj.type = (
                                            MessageType.GROUP_MESSAGE
                                            if not event.is_private_chat()
                                            else MessageType.FRIEND_MESSAGE
                                        )
                                        if not event.is_private_chat():
                                            msg_obj.group_id = event.get_group_id()
                                        msg_obj.self_id = event.get_self_id()
                                        msg_obj.session_id = (
                                            event.session_id
                                            if hasattr(event, "session_id")
                                            else chat_id
                                        )
                                        msg_obj.message_id = f"cached_{cached_msg.get('timestamp', time.time())}"
                                        sender_id = cached_msg.get("sender_id", "")
                                        sender_name = cached_msg.get(
                                            "sender_name", "未知用户"
                                        )
                                        if sender_id:
                                            msg_obj.sender = MessageMember(
                                                user_id=sender_id, nickname=sender_name
                                            )
                                        cached_astrbot_messages_for_freq.append(msg_obj)
                                    except Exception as e:
                                        if self.debug_mode:
                                            logger.warning(
                                                f"[频率调整] 转换缓存消息失败: {e}"
                                            )
                                elif isinstance(cached_msg, AstrBotMessage):
                                    cached_astrbot_messages_for_freq.append(cached_msg)

                        # 使用新的统一方法获取历史消息
                        recent_messages = (
                            await ContextManager.get_history_messages_with_fallback(
                                event=event,
                                max_messages=analysis_msg_count,
                                context=self.context,
                                cached_messages=cached_astrbot_messages_for_freq,
                            )
                        )

                        if self.debug_mode and cached_astrbot_messages_for_freq:
                            logger.info(f"[频率调整] 缓存消息已在统一方法中合并")

                    if self.debug_mode:
                        expected_desc = (
                            "不限制"
                            if analysis_msg_count == -1
                            else f"{analysis_msg_count}条"
                        )
                        logger.info(
                            f"[频率调整] 获取最近消息: 期望{expected_desc}, 实际{len(recent_messages) if recent_messages else 0}条"
                        )

                    if recent_messages:
                        # 构建可读的消息文本
                        # AstrBotMessage 对象的属性访问方式
                        bot_id = event.get_self_id()
                        recent_text_parts = []
                        # 遍历所有消息（已经在上面根据配置截断过了）
                        for msg in recent_messages:
                            # 判断消息角色（用户还是bot）
                            role = "user"
                            if hasattr(msg, "sender") and msg.sender:
                                sender_id = (
                                    msg.sender.user_id
                                    if hasattr(msg.sender, "user_id")
                                    else ""
                                )
                                if str(sender_id) == str(bot_id):
                                    role = "assistant"

                            # 提取消息内容
                            content = ""
                            if hasattr(msg, "message_str"):
                                content = msg.message_str[:100]

                            recent_text_parts.append(f"{role}: {content}")

                        recent_text = "\n".join(recent_text_parts)

                        # 使用AI分析频率（使用配置的超时时间）
                        analysis_timeout = self.frequency_analysis_timeout
                        decision = await self.frequency_adjuster.analyze_frequency(
                            self.context,
                            event,
                            recent_text,
                            self.decision_ai_provider_id,
                            analysis_timeout,
                        )

                        if decision:
                            # 获取当前概率
                            current_prob = (
                                await ProbabilityManager.get_current_probability(
                                    platform_name,
                                    is_private,
                                    chat_id,
                                    self.initial_probability,
                                )
                            )

                            # 调整概率
                            new_prob = self.frequency_adjuster.adjust_probability(
                                current_prob, decision
                            )

                            # 如果概率有变化，应用新概率
                            if abs(new_prob - current_prob) > 0.01:
                                # 通过概率管理器设置新的基础概率
                                # 使用配置的持续时间
                                duration = self.frequency_adjust_duration
                                await ProbabilityManager.set_base_probability(
                                    platform_name,
                                    is_private,
                                    chat_id,
                                    new_prob,
                                    duration,
                                )
                                logger.info(
                                    f"[频率调整] ✅ 已应用概率调整: {current_prob:.2f} → {new_prob:.2f} (持续{duration}秒)"
                                )

                            # 更新检查状态（使用相同的chat_key确保状态一致）
                            self.frequency_adjuster.update_check_state(chat_key)

                    if self.debug_mode:
                        _freq_elapsed = time.time() - _freq_start
                        logger.info(
                            f"【步骤17】频率调整检查完成，耗时: {_freq_elapsed:.2f}秒"
                        )
            except Exception as e:
                logger.error(f"频率调整检查失败: {e}")

        if self.debug_mode:
            logger.info("=" * 60)
            logger.info("✓ 消息处理流程完成")

        _process_total_time = time.time() - _process_start_time
        timeout_threshold = self.reply_timeout_warning_threshold
        if _process_total_time > timeout_threshold:
            logger.warning(
                f"⚠️ 消息处理总耗时异常: {_process_total_time:.2f}秒 ({int(_process_total_time / 60)}分{int(_process_total_time % 60)}秒)（超过{timeout_threshold}秒阈值）"
            )
        elif self.debug_mode:
            logger.info(f"消息处理总耗时: {_process_total_time:.2f}秒")

        logger.info("消息处理完成,已发送回复并保存历史")

        # 🆕 回复后戳一戳功能
        if self.poke_after_reply_enabled:
            # 获取被回复的用户信息
            replied_user_id = event.get_sender_id()

            # 执行戳一戳（概率触发）
            await self._do_poke_after_reply(event, replied_user_id, is_private, chat_id)

    async def _do_poke_after_reply(
        self, event: AstrMessageEvent, user_id: str, is_private: bool, chat_id: str
    ):
        """
        回复后戳一戳功能

        Args:
            event: 消息事件
            user_id: 被戳的用户ID
            is_private: 是否为私聊
            chat_id: 聊天ID
        """
        try:
            # 只在群聊中生效（私聊不需要戳一戳）
            if is_private:
                if self.debug_mode:
                    logger.info("[戳一戳] 私聊消息，跳过戳一戳功能")
                return

            # 🆕 白名单检查：检查当前群聊是否允许戳一戳功能
            if not self._is_poke_enabled_in_group(chat_id):
                if self.debug_mode:
                    logger.info(
                        f"[戳一戳] 群 {chat_id} 不在戳一戳白名单中，跳过戳一戳功能"
                    )
                return

            # 检查平台是否为aiocqhttp
            platform_name = event.get_platform_name()
            if platform_name != "aiocqhttp":
                if self.debug_mode:
                    logger.info(f"[戳一戳] 当前平台 {platform_name} 不支持戳一戳，跳过")
                return

            # 根据概率决定是否戳一戳
            if random.random() > self.poke_after_reply_probability:
                if self.debug_mode:
                    logger.info(
                        f"[戳一戳] 未达到触发概率({self.poke_after_reply_probability})，跳过"
                    )
                return

            # 延迟执行（模拟真人思考时间）
            if self.poke_after_reply_delay > 0:
                await asyncio.sleep(self.poke_after_reply_delay)

            # 确保事件类型正确
            if not isinstance(event, AiocqhttpMessageEvent):
                logger.warning(f"[戳一戳] 事件类型不匹配，无法执行戳一戳")
                return

            # 执行戳一戳
            try:
                client = event.bot
                payloads = {"user_id": int(user_id)}
                # 添加群ID
                if chat_id:
                    payloads["group_id"] = int(chat_id)

                await client.api.call_action("send_poke", **payloads)

                if self.debug_mode:
                    logger.info(f"[戳一戳] ✅ 已戳一戳用户 {user_id} (群:{chat_id})")
                else:
                    logger.info(f"[戳一戳] 已戳一戳用户")

                if self.poke_trace_enabled:
                    self._register_poke_trace(chat_id, str(user_id))

            except Exception as e:
                logger.error(f"[戳一戳] 执行戳一戳失败: {e}")

        except Exception as e:
            logger.error(f"[戳一戳] 戳一戳功能发生错误: {e}")

    async def _maybe_reverse_poke_on_poke(
        self,
        event: AstrMessageEvent,
        poke_info: dict,
        is_private: bool,
        chat_id: str,
    ) -> bool:
        """
        在收到戳一戳消息且未被忽略时，按配置概率反向戳回发起戳一戳的用户。
        成功触发时返回True（表示本插件丢弃后续处理），否则返回False。
        """
        try:
            # 概率为0则不启用
            if self.poke_reverse_on_poke_probability <= 0:
                return False

            # 仅在群聊中执行（与回复后戳一戳一致的限制）
            if is_private:
                if self.debug_mode:
                    logger.info("【反戳】私聊消息，跳过反戳功能")
                return False

            # 🆕 白名单检查：检查当前群聊是否允许戳一戳功能
            if not self._is_poke_enabled_in_group(chat_id):
                if self.debug_mode:
                    logger.info(
                        f"【反戳】群 {chat_id} 不在戳一戳白名单中，跳过反戳功能"
                    )
                return False

            # 平台校验
            platform_name = event.get_platform_name()
            if platform_name != "aiocqhttp":
                if self.debug_mode:
                    logger.info(f"【反戳】平台 {platform_name} 不支持戳一戳，跳过")
                return False

            # 概率判断
            if random.random() >= self.poke_reverse_on_poke_probability:
                if self.debug_mode:
                    logger.info(
                        f"【反戳】未达到触发概率({self.poke_reverse_on_poke_probability})，继续正常处理"
                    )
                return False

            # 事件类型校验
            if not isinstance(event, AiocqhttpMessageEvent):
                logger.warning("【反戳】事件类型不匹配，无法执行戳一戳")
                return False

            # 执行反戳（戳回发起者）
            sender_id = poke_info.get("sender_id")
            if not sender_id:
                if self.debug_mode:
                    logger.info("【反戳】缺少sender_id，跳过")
                return False

            try:
                client = event.bot
                payloads = {"user_id": int(sender_id)}
                if chat_id:
                    payloads["group_id"] = int(chat_id)

                await client.api.call_action("send_poke", **payloads)
                if self.debug_mode:
                    logger.info(f"【反戳】✅ 已反戳用户 {sender_id} (群:{chat_id})")
                else:
                    logger.info("【反戳】已执行反戳")
                if self.poke_trace_enabled:
                    self._register_poke_trace(chat_id, str(sender_id))
            except Exception as e:
                logger.error(f"【反戳】执行反戳失败: {e}")
                # 即使失败，也不影响主流程，继续正常处理
                return False

            # 已触发反戳，本插件丢弃后续处理（不拦截消息传播）
            return True

        except Exception as e:
            logger.error(f"【反戳】反戳流程发生错误: {e}")
            return False

    def _get_poke_trace_store(self, chat_id: str) -> OrderedDict:
        key = str(chat_id)
        store = self.poke_trace_records.get(key)
        if not isinstance(store, OrderedDict):
            store = OrderedDict()
            self.poke_trace_records[key] = store
        return store

    def _cleanup_poke_trace(self, chat_id: str):
        store = self._get_poke_trace_store(chat_id)
        now_ts = time.time()
        to_delete = [uid for uid, exp in store.items() if exp <= now_ts]
        for uid in to_delete:
            try:
                del store[uid]
            except Exception:
                pass

    def _register_poke_trace(self, chat_id: str, user_id: str):
        try:
            if not self.poke_trace_enabled:
                return
            store = self._get_poke_trace_store(chat_id)
            self._cleanup_poke_trace(chat_id)
            uid = str(user_id)
            if uid in store:
                try:
                    del store[uid]
                except Exception:
                    pass
            while len(store) >= max(1, int(self.poke_trace_max_tracked_users)):
                try:
                    store.popitem(last=False)
                except Exception:
                    break
            expire_at = time.time() + max(1, int(self.poke_trace_ttl_seconds))
            store[uid] = expire_at
            if self.debug_mode:
                logger.info(
                    f"[戳过对方追踪] 注册: chat={chat_id} user={uid} ttl={self.poke_trace_ttl_seconds}s"
                )
        except Exception as e:
            logger.error(f"[戳过对方追踪] 注册失败: {e}")

    def _check_and_consume_poke_trace(self, chat_id: str, user_id: str) -> bool:
        try:
            if not self.poke_trace_enabled:
                return False
            store = self._get_poke_trace_store(chat_id)
            self._cleanup_poke_trace(chat_id)
            uid = str(user_id)
            exp = store.get(uid)
            if exp and exp > time.time():
                try:
                    del store[uid]
                except Exception:
                    pass
                if self.debug_mode:
                    logger.info(f"[戳过对方追踪] 命中并消费: chat={chat_id} user={uid}")
                return True
            return False
        except Exception as e:
            logger.error(f"[戳过对方追踪] 检查失败: {e}")
            return False

    async def _process_message(self, event: AstrMessageEvent):
        """
        消息处理主流程

        协调各个子步骤完成消息处理

        流程优化说明：
        - 概率判断在最前面，快速过滤不需要处理的消息
        - 避免对不需要处理的消息进行图片识别等耗时操作

        Args:
            event: 消息事件对象
        """
        _process_start_time = time.time()

        # 步骤1: 执行初始检查（最基本的过滤）
        (
            should_continue,
            platform_name,
            is_private,
            chat_id,
        ) = await self._perform_initial_checks(event)
        if not should_continue:
            return

        # 🆕 v1.0.2: 记录消息（用于频率调整统计）
        if self.frequency_adjuster_enabled and self.frequency_adjuster:
            # 使用完整的会话标识，确保不同会话的状态隔离
            chat_key = ProbabilityManager.get_chat_key(
                platform_name, is_private, chat_id
            )
            self.frequency_adjuster.record_message(chat_key)

        # 🆕 v1.1.0: 记录用户消息（用于主动对话功能）
        if self.proactive_enabled:
            chat_key = ProbabilityManager.get_chat_key(
                platform_name, is_private, chat_id
            )

            # 🆕 v1.2.0: 检测是否是对主动对话的成功回复
            if self.enable_adaptive_proactive:
                state = ProactiveChatManager.get_chat_state(chat_key)

                # 🔒 严格检查：主动对话必须处于活跃状态
                # 这是防误判的核心：只有主动对话真正发送成功后，proactive_active才为True
                proactive_active = state.get("proactive_active", False)

                if not proactive_active:
                    # 主动对话未激活，直接跳过所有检测
                    # 这避免了：
                    # 1. 从未触发过主动对话时的误判
                    # 2. 主动对话发送失败时的误判
                    # 3. 已判定失败/成功后的误判
                    # 4. 普通回复模式下的误判
                    if self.debug_mode and state.get("last_proactive_time", 0) > 0:
                        logger.info(
                            f"[主动对话检测] 群{chat_key} - 主动对话未激活，跳过检测"
                        )
                else:
                    # 主动对话已激活，可以进行检测
                    last_proactive_time = state.get("last_proactive_time", 0)
                    current_time = time.time()
                    outcome_recorded = state.get("proactive_outcome_recorded", False)

                    # 🔒 检查是否在临时提升期内（用于追踪多人回复）
                    boost_duration = self.proactive_temp_boost_duration
                    in_boost_period = (
                        last_proactive_time > 0
                        and (current_time - last_proactive_time) <= boost_duration
                    )

                    # 📊 多人回复追踪（在整个临时提升期内持续追踪）
                    if in_boost_period:
                        if not hasattr(self, "_proactive_reply_users"):
                            self._proactive_reply_users = {}

                        sender_id = event.get_sender_id()

                        # 初始化或更新追踪器
                        if chat_key not in self._proactive_reply_users:
                            self._proactive_reply_users[chat_key] = {
                                "users": set(),
                                "proactive_time": last_proactive_time,
                            }

                        # 如果是同一次主动对话，追踪用户
                        if (
                            self._proactive_reply_users[chat_key]["proactive_time"]
                            == last_proactive_time
                        ):
                            self._proactive_reply_users[chat_key]["users"].add(
                                sender_id
                            )
                        else:
                            # 新的主动对话，重置追踪
                            self._proactive_reply_users[chat_key] = {
                                "users": {sender_id},
                                "proactive_time": last_proactive_time,
                            }

                    # 📊 持续追踪多人回复（在整个提升期内）
                    # 但不在此处判定成功，等待AI真正决定回复时再判定
                    # 这避免了用户回复但AI不回复却被误判为成功的问题
                    if self.debug_mode and in_boost_period:
                        logger.debug(
                            f"[主动对话追踪] 群{chat_key} - "
                            f"用户{sender_id}在提升期内发言，持续追踪中"
                        )

            ProactiveChatManager.record_user_message(chat_key)
            # 检查并处理主动对话后的回复（新逻辑：仅在AI决定回复时由后续流程强制取消）
            ProactiveChatManager.check_and_handle_reply_after_proactive(
                chat_key, self.config, force=False
            )

        # 步骤2: 检查消息触发器（决定是否跳过概率判断）
        # 🆕 v1.2.1: 新增返回匹配到的触发关键词
        (
            is_at_message,
            has_trigger_keyword,
            matched_trigger_keyword,
        ) = await self._check_message_triggers(event)

        # 步骤2.5: 检测戳一戳信息（v1.0.9新增，在概率判断前提取）
        poke_result = self._check_poke_message(event)
        # 修复：保留完整的poke_result结构，包含is_poke字段
        poke_info_for_probability = (
            poke_result
            if poke_result.get("is_poke") and not poke_result.get("should_ignore")
            else None
        )

        # 关键逻辑：触发关键词等同于@消息
        # 这样在 mention_only 模式下，包含关键词的消息也能正常处理图片
        should_treat_as_at = is_at_message or has_trigger_keyword

        # 只在debug模式下显示详细判断，或在特殊情况下记录
        if self.debug_mode:
            logger.info(
                f"【等同@消息】判断: {'是' if should_treat_as_at else '否'} (is_at={is_at_message}, has_keyword={has_trigger_keyword})"
            )

        # 步骤3: 概率判断（第一道核心过滤，避免后续耗时处理）
        should_process = await self._check_probability_before_processing(
            event,
            platform_name,
            is_private,
            chat_id,
            is_at_message,
            has_trigger_keyword,
            poke_info_for_probability,  # 传递戳一戳信息
        )
        if not should_process:
            # 🆕 概率判断失败时，也进行简化的消息缓存（避免上下文断裂）
            # 🆕 v1.2.0: 尝试从平台 LTM 获取图片描述，充分利用平台的图片理解功能
            try:
                if self.debug_mode:
                    logger.info(
                        "【步骤3-缓存】概率判断失败，但仍缓存原始消息（避免上下文断裂）"
                    )

                # 提取原始消息文本（不含系统提示词
                original_message_text = MessageCleaner.extract_raw_message_from_event(
                    event
                )

                # 🔧 v1.2.0: 先让出控制权，让平台 LTM 有机会开始处理消息
                # 这是关键！asyncio.sleep(0) 会让出事件循环控制权，让其他协程（如平台 LTM）有机会执行
                await asyncio.sleep(0)
                
                # 检测图片，如果有图片则额外延迟，等待平台 LTM 处理
                has_image = PlatformLTMHelper.has_image_in_message(event)
                if has_image:
                    # 🔧 对于图片消息，使用配置的延迟时间
                    if self.probability_filter_cache_delay > 0:
                        await asyncio.sleep(self.probability_filter_cache_delay / 1000.0)

                # 🆕 v1.2.0: 检查消息是否包含图片，如果包含则尝试从平台获取图片描述
                is_pure_image = PlatformLTMHelper.is_pure_image_message(event)
                
                processed_text = None
                should_cache = True
                success = False  # 🔧 初始化 success 变量，用于后续日志判断
                
                if has_image:
                    # 消息包含图片，尝试从平台 LTM 获取图片描述
                    # 🔧 v1.2.0: 使用异步版本，支持智能等待平台处理完成，传递用户配置参数
                    success, platform_processed_text = await PlatformLTMHelper.extract_image_caption_from_platform(
                        self.context,
                        event,
                        original_message_text,
                        max_wait=self.platform_image_caption_max_wait,
                        retry_interval=self.platform_image_caption_retry_interval,
                        fast_check_count=self.platform_image_caption_fast_check_count,
                    )
                    
                    if success and platform_processed_text:
                        # 成功获取平台的图片描述
                        processed_text = platform_processed_text
                        logger.info(
                            f"🖼️ [概率过滤-平台图片描述] 成功提取图片描述，将缓存带描述的消息: {processed_text[:80]}..."
                        )
                    else:
                        # 平台未处理或获取失败，使用原有逻辑
                        if is_pure_image:
                            # 纯图片消息且平台未处理，丢弃
                            should_cache = False
                            if self.debug_mode:
                                logger.info("  纯图片消息且平台未处理图片描述，不缓存")
                        else:
                            # 图文混合消息，过滤图片只保留文字
                            should_cache, processed_text = (
                                MessageCleaner.process_cached_message_images(original_message_text)
                            )
                            if self.debug_mode:
                                logger.info(f"  图文混合消息，过滤图片后: {processed_text[:80] if processed_text else '(空)'}")
                else:
                    # 不包含图片，直接使用原始文本
                    processed_text = original_message_text
                    should_cache = bool(processed_text and processed_text.strip())

                if should_cache and processed_text:  # 只缓存非空且非纯图片的消息
                    # 创建简化的缓存条目
                    # 🔧 修复并发问题：添加 message_id，与正常处理流程保持一致
                    cached_message = {
                        "role": "user",
                        "content": processed_text,  # 使用处理后的消息（可能包含平台图片描述）
                        "timestamp": time.time(),
                        "message_id": self._get_message_id(event),  # 🔧 添加 message_id
                        "sender_id": event.get_sender_id(),
                        "sender_name": event.get_sender_name(),
                        "message_timestamp": event.message_obj.timestamp
                        if hasattr(event, "message_obj")
                        and hasattr(event.message_obj, "timestamp")
                        else None,
                        "mention_info": None,  # 概率失败时简化处理
                        "is_at_message": is_at_message,
                        "has_trigger_keyword": has_trigger_keyword,
                        "poke_info": None,  # 概率失败时简化处理
                        "probability_filtered": True,  # 标记为概率筛查过滤的消息
                    }

                    # 初始化缓存
                    if chat_id not in self.pending_messages_cache:
                        self.pending_messages_cache[chat_id] = []

                    # 清理旧消息（使用配置的过期时间）
                    current_time = time.time()
                    cache_ttl = self.pending_cache_ttl_seconds  # 使用配置的过期时间
                    self.pending_messages_cache[chat_id] = [
                        msg
                        for msg in self.pending_messages_cache[chat_id]
                        # 🔧 修复：优先使用 message_timestamp，兼容 timestamp，与排序逻辑保持一致
                        if current_time - (msg.get("message_timestamp") or msg.get("timestamp", 0)) < cache_ttl
                    ]

                    # 添加到缓存
                    self.pending_messages_cache[chat_id].append(cached_message)

                    # 限制缓存数量（使用配置的最大条数）
                    if len(self.pending_messages_cache[chat_id]) > self.pending_cache_max_count:
                        # 🔧 按 message_timestamp 排序后移除最旧的消息，避免并行处理导致顺序问题
                        self.pending_messages_cache[chat_id].sort(
                            key=lambda m: m.get("message_timestamp") or m.get("timestamp", 0)
                        )
                        self.pending_messages_cache[chat_id].pop(0)

                    # 🆕 始终显示概率过滤缓存日志（即使非debug模式）
                    # 🔧 区分普通消息和带图片描述的消息
                    if has_image and success:
                        logger.info(
                            f"📦 [缓存点1-概率过滤] 概率判断未通过，已缓存带图片描述的消息 (共{len(self.pending_messages_cache[chat_id])}条)"
                        )
                    else:
                        logger.info(
                            f"📦 [缓存点1-概率过滤] 概率判断未通过，已缓存消息保留上下文 (共{len(self.pending_messages_cache[chat_id])}条)"
                        )
                    if self.debug_mode:
                        logger.info(
                            f"  已缓存消息（概率过滤）: {processed_text[:100]}..."
                        )
                else:
                    if self.debug_mode:
                        if not should_cache:
                            logger.info("  消息为纯图片，不缓存")
                        else:
                            logger.info("  处理后的消息为空，跳过缓存")

            except Exception as e:
                logger.warning(f"[概率过滤-缓存] 缓存消息失败: {e}")

            # 概率判断失败，返回（不继续处理）
            return

        # 步骤3.5: 检测@提及信息（在图片处理之前，避免不必要的开销）
        mention_info = await self._check_mention_others(event)

        # 步骤3.6: 使用之前检测的戳一戳信息（避免重复检测）
        # 提取内嵌的poke_info用于后续处理
        poke_info = (
            poke_info_for_probability.get("poke_info")
            if poke_info_for_probability
            else None
        )

        # 收到戳一戳后的反戳逻辑（放在概率判断之后）：
        # 若命中概率，则反戳并丢弃本插件处理中剩余步骤
        if poke_info:
            reversed_and_discarded = await self._maybe_reverse_poke_on_poke(
                event, poke_info, is_private, chat_id
            )
            if reversed_and_discarded:
                # 不拦截消息传播，仅本插件结束处理
                return

        # 🆕 @消息提前检查是否已被其他插件处理，避免后续耗时操作（如图片转文字）
        # 注意：只检查真正的@消息，不检查触发关键词消息
        if is_at_message:
            if ReplyHandler.check_if_already_replied(event):
                logger.info("@消息已被其他插件处理,跳过后续流程")
                if self.debug_mode:
                    logger.info("【步骤3.7】@消息已被处理,退出")
                    logger.info("=" * 60)
                return

        # 步骤4-6: 处理消息内容（图片处理等耗时操作）
        # 使用 should_treat_as_at 作为 is_at_message 参与后续元数据/触发方式处理，
        # 同时通过 raw_is_at_message 传入真实的 @ 状态，便于图片识别范围精细控制
        result = await self._process_message_content(
            event,
            chat_id,
            should_treat_as_at,
            mention_info,
            has_trigger_keyword,
            poke_info,
            raw_is_at_message=is_at_message,
        )
        if not result[0]:  # should_continue为False
            return

        (
            _,
            original_message_text,
            message_text,
            formatted_context,
            image_urls,
            history_messages,
        ) = result

        merged_image_urls = image_urls or []
        try:
            if (
                self.enable_image_processing
                and not self.image_to_text_provider_id
                and chat_id in self.pending_messages_cache
            ):
                for _cached in self.pending_messages_cache[chat_id]:
                    if isinstance(_cached, dict):
                        _urls = _cached.get("image_urls") or []
                        if _urls:
                            merged_image_urls.extend(_urls)

                if merged_image_urls:
                    _seen_urls = set()
                    _dedup_urls = []
                    for _u in merged_image_urls:
                        if _u and _u not in _seen_urls:
                            _seen_urls.add(_u)
                            _dedup_urls.append(_u)
                    merged_image_urls = _dedup_urls
        except Exception as e:
            logger.warning(f"[图片缓存] 合并图片URL失败: {e}")

        # 🔧 修复并发竞争：在AI决策判断之前就提取缓存副本
        # 避免在决策AI判断期间（可能耗时6-8秒），缓存被其他并发消息清空
        current_message_cache = None
        # 提前获取 message_id，用于存储缓存快照
        early_message_id = self._get_message_id(event)
        try:
            if (
                chat_id in self.pending_messages_cache
                and len(self.pending_messages_cache[chat_id]) > 0
            ):
                # 深拷贝最后一条缓存消息，避免引用被清空

                current_message_cache = copy.deepcopy(
                    self.pending_messages_cache[chat_id][-1]
                )
                # 🔧 存储到实例变量，供 after_message_sent 使用
                self._message_cache_snapshots[early_message_id] = current_message_cache
                if self.debug_mode:
                    logger.info(
                        f"🔒 [并发保护] 已在AI决策前提取缓存副本: {current_message_cache.get('content', '')[:100]}..."
                    )
        except Exception as e:
            logger.warning(f"[并发保护] 提取缓存副本失败: {e}")

        # 步骤7: AI决策判断（第二道核心过滤）
        # 🆕 v1.2.1: 传递匹配到的触发关键词
        # 🆕 v1.2.2: 传递原始消息文本用于关键词检测
        should_reply = await self._check_ai_decision(
            event,
            formatted_context,
            is_at_message,
            has_trigger_keyword,
            merged_image_urls,
            matched_trigger_keyword=matched_trigger_keyword,
            original_message_text=original_message_text,
        )

        if not should_reply:
            # 不回复，但保存缓存的用户消息
            if self.debug_mode:
                logger.info("【步骤9】决策AI返回NO,但保存缓存的用户消息")

            try:
                # 🔧 优先使用提前提取的缓存副本，避免并发竞争
                last_cached_msg = current_message_cache
                if not last_cached_msg and (
                    chat_id in self.pending_messages_cache
                    and self.pending_messages_cache[chat_id]
                ):
                    last_cached_msg = self.pending_messages_cache[chat_id][-1]
                    logger.warning(
                        "⚠️ [并发警告] 使用共享缓存（可能已被清空），建议检查并发逻辑"
                    )

                if last_cached_msg:
                    # 获取处理后的消息内容（不含元数据）
                    raw_content = last_cached_msg["content"]

                    # 使用缓存中的发送者信息添加元数据
                    # 🆕 v1.0.4: 根据缓存中的触发方式信息确定trigger_type
                    # 注意：需要同时检查 has_trigger_keyword 来正确判断触发方式
                    trigger_type = None
                    if last_cached_msg.get("has_trigger_keyword"):
                        # 关键词触发（优先级高于@消息判断）
                        trigger_type = "keyword"
                    elif last_cached_msg.get("is_at_message"):
                        # 真正的@消息触发
                        trigger_type = "at"
                    else:
                        # 概率触发（AI主动回复）
                        trigger_type = "ai_decision"

                    message_with_metadata = MessageProcessor.add_metadata_from_cache(
                        raw_content,
                        last_cached_msg.get("sender_id", event.get_sender_id()),
                        last_cached_msg.get("sender_name", event.get_sender_name()),
                        last_cached_msg.get("message_timestamp")
                        or last_cached_msg.get("timestamp"),
                        self.include_timestamp,
                        self.include_sender_info,
                        last_cached_msg.get("mention_info"),  # 传递@信息
                        trigger_type,  # 🆕 v1.0.4: 传递触发方式
                        last_cached_msg.get("poke_info"),  # 🆕 v1.0.9: 传递戳一戳信息
                    )

                    # 清理系统提示（保存前过滤）
                    message_with_metadata = MessageCleaner.clean_message(
                        message_with_metadata
                    )

                    await ContextManager.save_user_message(
                        event,
                        message_with_metadata,
                        None,
                    )
                    logger.info(f"已保存未回复的用户消息到自定义历史（已添加元数据）")

                    # 🔧 从共享缓存中移除已保存的消息，避免后续回复时重复转正
                    if (
                        current_message_cache
                        and chat_id in self.pending_messages_cache
                        and self.pending_messages_cache[chat_id]
                    ):
                        # 🔧 修复：优先使用 message_id 移除，更精确
                        cache_msg_id = current_message_cache.get("message_id")
                        cache_timestamp = current_message_cache.get("timestamp")
                        
                        original_len = len(self.pending_messages_cache[chat_id])
                        if cache_msg_id:
                            # 使用 message_id 移除（更精确）
                            self.pending_messages_cache[chat_id] = [
                                msg
                                for msg in self.pending_messages_cache[chat_id]
                                if msg.get("message_id") != cache_msg_id
                            ]
                        elif cache_timestamp:
                            # 回退到使用时间戳移除
                            self.pending_messages_cache[chat_id] = [
                                msg
                                for msg in self.pending_messages_cache[chat_id]
                                if msg.get("timestamp") != cache_timestamp
                            ]
                        
                        removed = original_len - len(self.pending_messages_cache[chat_id])
                        if removed > 0 and self.debug_mode:
                            logger.info(
                                f"🗑️ [缓存清理] 已从共享缓存移除当前消息（避免重复转正）"
                            )
                else:
                    logger.warning(
                        "⚠️ [并发问题] 缓存副本和共享缓存都为空，无法保存用户消息"
                    )
            except Exception as e:
                logger.warning(f"保存未回复消息失败: {e}")

            # 🔧 清理缓存快照（不回复时 after_message_sent 不会被调用）
            self._message_cache_snapshots.pop(early_message_id, None)

            if self.debug_mode:
                logger.info("=" * 60)
            return

        # 🔧 修复：使用message_id作为键，避免同一会话中多条消息并发时标记冲突
        message_id = self._get_message_id(event)

        # 🔧 并发保护：检查同一会话是否有其他消息正在处理
        # 如果有，循环等待直到前一个消息完成或达到最大等待次数
        max_wait_loops = self.concurrent_wait_max_loops  # 最大等待循环次数
        wait_interval = self.concurrent_wait_interval  # 每次循环等待秒数

        for loop_count in range(max_wait_loops):
            existing_processing = [
                msg_id
                for msg_id, cid in self.processing_sessions.items()
                if cid == chat_id and msg_id != message_id
            ]

            if not existing_processing:
                # 没有其他消息在处理，可以继续
                break

            if loop_count == 0:
                logger.warning(
                    f"⚠️ [并发检测] 会话 {chat_id} 中有 {len(existing_processing)} 条消息正在处理中，"
                    f"开始等待（最多 {max_wait_loops} 次，每次 {wait_interval} 秒）..."
                )

            await asyncio.sleep(wait_interval)

            if self.debug_mode:
                logger.info(
                    f"  [并发等待] 第 {loop_count + 1}/{max_wait_loops} 次检测..."
                )
        else:
            # 循环结束仍有消息在处理
            still_processing = [
                msg_id
                for msg_id, cid in self.processing_sessions.items()
                if cid == chat_id and msg_id != message_id
            ]
            if still_processing:
                logger.warning(
                    f"⚠️ [并发警告] 等待 {max_wait_loops * wait_interval:.1f} 秒后仍有 "
                    f"{len(still_processing)} 条消息在处理，继续执行可能产生竞争"
                )

        self.processing_sessions[message_id] = chat_id
        if self.debug_mode:
            logger.info(f"  已标记消息 {message_id[:30]}... 为本插件处理中")

        # 🆕 在读空气AI判定确认回复后，检查主动对话成功并重置计时器
        # 关键逻辑：只有AI真正决定回复时，才判定主动对话成功
        if should_reply and self.proactive_enabled:
            chat_key = ProbabilityManager.get_chat_key(
                platform_name, is_private, chat_id
            )

            # ✅ 在AI决定回复时，检查是否为主动对话成功
            state = ProactiveChatManager.get_chat_state(chat_key)
            proactive_active = state.get("proactive_active", False)
            outcome_recorded = state.get("proactive_outcome_recorded", False)
            last_proactive_time = state.get("last_proactive_time", 0)
            current_time = time.time()

            # 检查是否在提升期内
            boost_duration = self.proactive_temp_boost_duration
            in_boost_period = (current_time - last_proactive_time) <= boost_duration

            # 只有主动对话活跃、未判定过、且在提升期内，才判定为成功
            if proactive_active and not outcome_recorded and in_boost_period:
                # 检测是否快速回复（30秒内）
                is_quick_reply = (current_time - last_proactive_time) <= 30

                # 检测是否多人回复（基于追踪器）
                is_multi_user = False
                if chat_key in self._proactive_reply_users:
                    if (
                        self._proactive_reply_users[chat_key]["proactive_time"]
                        == last_proactive_time
                    ):
                        is_multi_user = (
                            len(self._proactive_reply_users[chat_key]["users"]) >= 2
                        )

                # 记录成功互动（AI真正决定回复，才算成功）
                ProactiveChatManager.record_proactive_success(
                    chat_key, self.config, is_quick_reply, is_multi_user
                )

                if self.debug_mode:
                    logger.info(
                        f"✅ [主动对话成功] 群{chat_key} - "
                        f"AI决定回复，快速回复={is_quick_reply}, 多人回复={is_multi_user}"
                    )

            # 取消主动对话的临时概率提升与连续尝试（AI已决定回复）
            ProactiveChatManager.check_and_handle_reply_after_proactive(
                chat_key, self.config, force=True
            )
            ProactiveChatManager.record_bot_reply(chat_key, is_proactive=False)
            if self.debug_mode:
                logger.info(f"[主动对话] 读空气AI判定确认回复，已重置主动对话计时器")

        # 🆕 v1.2.1: 冷却解除检测 (Requirements 2.1, 2.2)
        # 当AI决定回复时，尝试解除用户的冷却状态
        if should_reply and self.cooldown_enabled:
            try:
                chat_key = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )
                user_id = event.get_sender_id()

                # 确定触发类型
                if has_trigger_keyword:
                    trigger_type = "keyword"
                elif is_at_message:
                    trigger_type = "at"
                else:
                    trigger_type = "normal"

                # 尝试解除冷却状态
                released = await CooldownManager.try_release_cooldown_on_reply(
                    chat_key, user_id, trigger_type
                )

                if released:
                    logger.info(
                        f"🧊 [冷却解除] 用户 {event.get_sender_name()}(ID:{user_id}) "
                        f"已从冷却列表移除，触发方式: {trigger_type}"
                    )
            except Exception as e:
                logger.warning(f"[冷却解除] 检测失败: {e}")

        # 🆕 v1.2.3: 对话疲劳重置（在AI决策确认回复后、生成回复前执行）
        # 重要：必须在 record_replied_user() 之前执行，否则会先累加再重置
        # 只有 @消息 或 关键词触发 才重置疲劳状态（表示用户主动想继续聊天）
        if should_reply and self.enable_conversation_fatigue and self.enable_attention_mechanism:
            if is_at_message or has_trigger_keyword:
                try:
                    user_id = event.get_sender_id()
                    user_name = event.get_sender_name() or "未知用户"
                    await AttentionManager.reset_consecutive_replies(
                        platform_name, is_private, chat_id, user_id
                    )
                    if self.debug_mode:
                        trigger_reason = "@消息" if is_at_message else "关键词"
                        logger.info(
                            f"[对话疲劳] 用户 {user_name} 通过{trigger_reason}主动触发，"
                            f"已重置连续对话轮次（在生成回复前）"
                        )
                except Exception as e:
                    if self.debug_mode:
                        logger.warning(f"[对话疲劳] 重置连续对话轮次失败: {e}")

        # 步骤10-15: 生成并发送回复
        # 注意：current_message_cache 已在AI决策判断之前提取
        
        # 🆕 v1.2.3: 获取对话疲劳信息（用于生成收尾提示）
        conversation_fatigue_info = None
        if self.enable_conversation_fatigue and self.enable_attention_mechanism:
            try:
                user_id = event.get_sender_id()
                conversation_fatigue_info = await AttentionManager.get_conversation_fatigue_info(
                    platform_name, is_private, chat_id, user_id
                )
            except Exception as e:
                if self.debug_mode:
                    logger.warning(f"[对话疲劳] 获取疲劳信息失败: {e}")
        
        # 🆕 v1.2.3: 准备疲劳信息用于回复AI（添加收尾提示的随机判断）
        reply_fatigue_info = None
        if conversation_fatigue_info and conversation_fatigue_info.get("enabled", False):
            fatigue_level = conversation_fatigue_info.get("fatigue_level", "none")
            # 只有中度或重度疲劳时才可能添加收尾提示
            if fatigue_level in ("medium", "heavy"):
                import random
                # 根据配置的概率决定是否添加收尾提示
                closing_probability = self.fatigue_closing_probability
                should_add_closing = random.random() < closing_probability
                if should_add_closing:
                    reply_fatigue_info = {
                        **conversation_fatigue_info,
                        "should_add_closing_hint": True,
                    }
                    if self.debug_mode:
                        logger.info(
                            f"[对话疲劳] 触发收尾提示（概率={closing_probability:.0%}），"
                            f"疲劳等级={fatigue_level}"
                        )
        
        async for result in self._generate_and_send_reply(
            event,
            formatted_context,
            message_text,
            platform_name,
            is_private,
            chat_id,
            is_at_message,
            has_trigger_keyword,  # 🆕 v1.0.4: 传递触发方式信息
            merged_image_urls,  # 传递图片URL列表（用于多模态AI）
            history_messages,  # 🔧 修复：传递历史消息用于构建contexts
            current_message_cache,  # 🔧 修复：传递当前消息缓存副本，避免并发竞争
            reply_fatigue_info,  # 🆕 v1.2.3: 传递疲劳信息用于收尾提示
        ):
            yield result

    @filter.on_llm_request(priority=-1)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """
        🆕 v1.2.0: LLM 请求钩子 - 处理插件与平台/其他插件的上下文冲突
        
        优先级设置为 -1（较低），确保在其他插件（如 emotionai，priority=100000）
        和平台 LTM（priority=0）之后执行
        
        执行顺序：emotionai(100000) -> 平台LTM(0) -> 本插件(-1)
        
        当检测到请求来自本插件时（通过 PLUGIN_REQUEST_MARKER 标记）：
        1. 使用插件自己的上下文替换平台 LTM 注入的上下文
        2. 保留其他插件（如 emotionai）注入的 system_prompt 内容
        
        这样既能让其他插件的钩子生效，又能避免与平台 LTM 的上下文冲突
        """
        from .utils.reply_handler import (
            PLUGIN_REQUEST_MARKER,
            PLUGIN_CUSTOM_CONTEXTS,
            PLUGIN_CUSTOM_SYSTEM_PROMPT,
            PLUGIN_CUSTOM_PROMPT,
            PLUGIN_IMAGE_URLS,
        )
        
        # 检查是否是来自本插件的请求
        is_plugin_request = event.get_extra(PLUGIN_REQUEST_MARKER, False)
        if not is_plugin_request:
            # 不是本插件的请求，不做任何处理
            return
        
        if self.debug_mode:
            logger.info("🔧 [on_llm_request] 检测到本插件的 LLM 请求，开始处理上下文冲突...")
        
        # 获取插件存储的自定义数据
        plugin_contexts = event.get_extra(PLUGIN_CUSTOM_CONTEXTS, [])
        plugin_system_prompt = event.get_extra(PLUGIN_CUSTOM_SYSTEM_PROMPT, "")
        plugin_prompt = event.get_extra(PLUGIN_CUSTOM_PROMPT, "")
        plugin_image_urls = event.get_extra(PLUGIN_IMAGE_URLS, [])
        
        # 🔧 关键：保留其他插件注入的 system_prompt 内容
        # emotionai 等插件会在 system_prompt 后面追加内容
        # 我们需要保留这些追加的内容，但使用插件自己的基础 system_prompt
        other_plugin_additions = ""
        if req.system_prompt and plugin_system_prompt:
            # 检查 req.system_prompt 是否包含了其他插件追加的内容
            # 其他插件通常会在原有 system_prompt 后面追加内容
            if len(req.system_prompt) > len(plugin_system_prompt):
                # 提取其他插件追加的部分
                # 注意：这里假设其他插件是在原有内容后面追加的
                # 如果其他插件修改了原有内容，这种方法可能不完美
                other_plugin_additions = req.system_prompt[len(plugin_system_prompt):]
                if self.debug_mode:
                    logger.info(f"  检测到其他插件追加的 system_prompt 内容，长度: {len(other_plugin_additions)}")
        
        # 🔧 使用插件自己的上下文替换平台 LTM 注入的上下文
        # 平台 LTM 的 on_req_llm 方法会修改 req.contexts 和 req.system_prompt
        # 我们需要恢复插件自己的设置
        req.contexts = plugin_contexts
        req.prompt = plugin_prompt
        req.image_urls = plugin_image_urls
        
        # 🔧 合并 system_prompt：插件基础 + 其他插件追加
        if other_plugin_additions:
            req.system_prompt = plugin_system_prompt + other_plugin_additions
        else:
            req.system_prompt = plugin_system_prompt
        
        if self.debug_mode:
            logger.info(f"  ✅ 已恢复插件自定义上下文:")
            logger.info(f"    - contexts 数量: {len(req.contexts)}")
            logger.info(f"    - system_prompt 长度: {len(req.system_prompt)}")
            logger.info(f"    - prompt 长度: {len(req.prompt)}")
            logger.info(f"    - image_urls 数量: {len(req.image_urls) if req.image_urls else 0}")

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        在最终结果装饰阶段进行去重：
        - 仅处理由本插件标记的消息（processing_sessions）
        - 仅处理 LLM 生成的最终文本结果
        - 若与最近 5 条回复内容重复（30 分钟内），清空结果以跳过发送
        """
        try:
            platform_name = event.get_platform_name()
            is_private = event.is_private_chat()
            chat_id = event.get_group_id() if not is_private else event.get_sender_id()

            # 🔧 修复：使用message_id作为键进行检查
            message_id = self._get_message_id(event)

            # 仅处理由本插件触发的消息
            if message_id not in self.processing_sessions:
                return

            result = event.get_result()
            if not result or not hasattr(result, "chain") or not result.chain:
                return

            # 仅处理 LLM 最终结果（非流式片段）
            if not result.is_llm_result():
                return

            # 提取纯文本
            reply_text = "".join(
                [comp.text for comp in result.chain if hasattr(comp, "text")]
            ).strip()
            if not reply_text:
                return

            self.raw_reply_cache[message_id] = reply_text

            # 🆕 v1.2.0: 应用输出内容过滤（独立于保存过滤）
            filtered_reply_text = reply_text
            try:
                filtered_reply_text = self.content_filter.process_for_output(reply_text)
            except Exception:
                logger.error("[输出过滤] 过滤时发生异常，将使用原始内容", exc_info=True)
            if filtered_reply_text != reply_text:
                logger.info(
                    f"[输出过滤] 已过滤AI回复，原长度: {len(reply_text)}, 过滤后: {len(filtered_reply_text)}"
                )
                # 更新 result 中的文本内容
                # 🔧 修复：需要处理所有文本组件，而不是只处理第一个
                first_text_comp = True
                for comp in result.chain:
                    if hasattr(comp, "text"):
                        if first_text_comp:
                            # 第一个文本组件：设置为过滤后的完整文本
                            comp.text = filtered_reply_text
                            first_text_comp = False
                        else:
                            # 其他文本组件：清空内容（避免重复输出）
                            comp.text = ""
                reply_text = filtered_reply_text

            if not reply_text:
                # 过滤后为空，清空结果
                if self.debug_mode:
                    logger.info("[输出过滤] 过滤后内容为空，跳过发送")
                event.clear_result()
                if message_id in self.raw_reply_cache:
                    del self.raw_reply_cache[message_id]
                return

            # 清理过期缓存并进行重复检查（使用可配置参数）
            # 🔧 使用配置的重复消息检测参数
            if self.enable_duplicate_filter:
                now_ts = time.time()
                if chat_id not in self.recent_replies_cache:
                    self.recent_replies_cache[chat_id] = []
                
                # 根据配置决定是否启用时效性过滤
                if self.enable_duplicate_time_limit:
                    time_limit = max(60, self.duplicate_filter_time_limit)
                    self.recent_replies_cache[chat_id] = [
                        r
                        for r in self.recent_replies_cache[chat_id]
                        if now_ts - r.get("timestamp", 0) < time_limit
                    ]

                # 检查是否与最近N条回复重复（使用配置的条数）
                check_count = max(1, self.duplicate_filter_check_count)
                for recent in self.recent_replies_cache[chat_id][-check_count:]:
                    recent_content = recent.get("content", "")
                    recent_timestamp = recent.get("timestamp", 0)
                    
                    # 如果启用时效性判断，检查消息是否在时效内
                    if self.enable_duplicate_time_limit:
                        time_limit = max(60, self.duplicate_filter_time_limit)
                        if now_ts - recent_timestamp >= time_limit:
                            continue  # 超过时效，跳过此条
                    
                    if recent_content and reply_text == recent_content.strip():
                        logger.warning(
                            f"🚫 [装饰阶段过滤] 检测到与最近回复重复，跳过发送（后续流程继续执行）\n"
                            f"  最近回复: {recent_content[:100]}...\n"
                            f"  当前回复: {reply_text[:100]}..."
                        )
                        logger.info(f"[装饰阶段] 正在清空event.result以阻止发送，但保留processing_sessions标记以便保存用户消息")
                        # 清空结果以阻止发送
                        event.clear_result()
                        # 🔧 重要修改：不删除 processing_sessions 标记，而是添加到 _duplicate_blocked_messages
                        # 这样 after_message_sent 会跳过AI消息保存，但继续保存用户消息
                        self._duplicate_blocked_messages[message_id] = True
                        if message_id in self.raw_reply_cache:
                            del self.raw_reply_cache[message_id]
                        if self.debug_mode:
                            logger.info(
                                f"[装饰阶段] 已标记消息为重复拦截: {message_id[:30]}...（将跳过AI消息保存，但保存用户消息）"
                            )
                        return

            # 非重复，不在此处更新缓存（在 after_message_sent 中记录）
        except Exception as e:
            logger.error(f"[装饰阶段] 去重处理失败: {e}", exc_info=True)

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        """
        消息发送后的钩子，保存AI回复到官方对话系统

        在这里保存是因为此时event.result已经完整设置

        注意：所有消息发送都会触发，需要检查是否本插件的回复
        """
        try:
            # 获取会话信息（用于检查标记）
            platform_name = event.get_platform_name()
            is_private = event.is_private_chat()
            chat_id = event.get_group_id() if not is_private else event.get_sender_id()

            # 🔧 修复：使用message_id作为键进行检查
            message_id = self._get_message_id(event)

            # 检查是否为本插件处理的消息
            if message_id not in self.processing_sessions:
                return  # 不是本插件触发的回复，忽略

            # 清除标记（无论成功与否，都要清除）
            del self.processing_sessions[message_id]
            
            # 🔧 检查是否为重复消息拦截（跳过AI消息保存，但继续保存用户消息）
            is_duplicate_blocked = message_id in self._duplicate_blocked_messages
            if is_duplicate_blocked:
                # 清除重复拦截标记
                del self._duplicate_blocked_messages[message_id]
                logger.info(f"[消息发送后] 会话 {chat_id} 检测到重复消息拦截标记，将跳过AI消息保存，但继续保存用户消息")

            # 只处理有result的消息（重复消息拦截时result已被清空，但仍需保存用户消息）
            if not is_duplicate_blocked and (not event._result or not hasattr(event._result, "chain")):
                logger.info(f"[消息发送后] 会话 {chat_id} 没有result或chain，跳过")
                return

            # 检查是否为LLM result，或是否存在AI调用错误标记
            result_obj = event._result if event._result else None
            is_llm_result = False
            if result_obj:
                try:
                    is_llm_result = bool(result_obj.is_llm_result())
                except Exception:
                    is_llm_result = False

            ai_error_flag = (
                hasattr(self, "_ai_error_message_ids")
                and message_id in self._ai_error_message_ids
            )

            # 🔧 重复消息拦截时，跳过LLM结果检查，直接进入用户消息保存流程
            if not is_duplicate_blocked and not is_llm_result and not ai_error_flag:
                logger.info(f"[消息发送后] 会话 {chat_id} 不是LLM结果，跳过")
                return

            # 提取回复文本（仅在为LLM结果且非重复拦截时使用）
            displayed_bot_reply_text = ""
            original_bot_reply_text = ""
            bot_reply_to_save = None  # 🔧 初始化为None，重复拦截时不保存AI消息
            
            if is_llm_result and not is_duplicate_blocked:
                displayed_bot_reply_text = "".join(
                    [comp.text for comp in result_obj.chain if hasattr(comp, "text")]
                )
                if not displayed_bot_reply_text:
                    logger.info(f"[消息发送后] 会话 {chat_id} 回复文本为空，跳过")
                    return
                if hasattr(self, "raw_reply_cache"):
                    original_bot_reply_text = self.raw_reply_cache.pop(message_id, "")
                if not original_bot_reply_text:
                    original_bot_reply_text = displayed_bot_reply_text

            # 🔧 只在非重复拦截时保存AI消息
            if is_llm_result and not is_duplicate_blocked:
                if self.debug_mode:
                    logger.info(
                        f"【消息发送后】会话 {chat_id} - 保存AI回复，长度: {len(original_bot_reply_text)} 字符"
                    )

                # 🆕 v1.2.0: 应用保存内容过滤（独立于输出过滤）
                bot_reply_to_save = original_bot_reply_text
                try:
                    bot_reply_to_save = self.content_filter.process_for_save(
                        original_bot_reply_text
                    )
                except Exception:
                    logger.error(
                        "[保存过滤] 过滤时发生异常，将使用原始内容", exc_info=True
                    )
                    bot_reply_to_save = original_bot_reply_text
                if bot_reply_to_save != original_bot_reply_text:
                    logger.info(
                        f"[保存过滤] 已过滤AI回复，原长度: {len(original_bot_reply_text)}, 过滤后: {len(bot_reply_to_save)}"
                    )

                # 保存AI回复到自定义存储（使用过滤后的内容）
                await ContextManager.save_bot_message(
                    event, bot_reply_to_save, self.context
                )

                # 记录到最近回复缓存（用于后续去重，使用原始内容）
                try:
                    if chat_id not in self.recent_replies_cache:
                        self.recent_replies_cache[chat_id] = []
                    self.recent_replies_cache[chat_id].append(
                        {"content": displayed_bot_reply_text, "timestamp": time.time()}
                    )
                    # 🔒 限制缓存大小（保留配置条数的2倍，最少10条，但不超过硬上限）
                    max_cache_size = min(
                        max(10, self.duplicate_filter_check_count * 2),
                        self._DUPLICATE_CACHE_SIZE_LIMIT
                    )
                    if len(self.recent_replies_cache[chat_id]) > max_cache_size:
                        # 丢弃最旧的消息，保留最新的
                        self.recent_replies_cache[chat_id] = self.recent_replies_cache[
                            chat_id
                        ][-max_cache_size:]
                except Exception:
                    pass
            elif is_duplicate_blocked:
                logger.info(f"[消息发送后] 会话 {chat_id} - 跳过AI消息保存（重复消息已拦截），继续保存用户消息")

            # 获取用户消息
            # 🔧 修复并发问题：优先使用 _message_cache_snapshots（在AI决策前提取的副本）
            # 避免在处理期间新消息进来导致获取到错误的消息
            message_to_save = ""
            
            # 优先使用缓存快照（并发安全）
            last_cached = self._message_cache_snapshots.pop(message_id, None)
            if not last_cached:
                # 回退到共享缓存（不应该发生，但作为保险）
                if (
                    chat_id in self.pending_messages_cache
                    and len(self.pending_messages_cache[chat_id]) > 0
                ):
                    last_cached = self.pending_messages_cache[chat_id][-1]
                    logger.warning(
                        "[消息发送后] ⚠️ 使用共享缓存获取当前消息（并发风险）"
                    )

            if last_cached and isinstance(last_cached, dict) and "content" in last_cached:
                # 获取处理后的消息内容（不含元数据）
                raw_content = last_cached["content"]

                # 强制日志：从缓存读取的内容
                logger.info(f"🟡 [官方保存-读缓存] 内容: {raw_content[:100]}")

                if self.debug_mode:
                    logger.info(
                        f"[消息发送后] 从缓存副本读取内容: {raw_content[:200]}..."
                    )

                # 使用缓存中的发送者信息添加元数据
                # 🆕 v1.0.4: 根据缓存中的触发方式信息确定trigger_type
                # 注意：需要同时检查 has_trigger_keyword 来正确判断触发方式
                trigger_type = None
                if last_cached.get("has_trigger_keyword"):
                    # 关键词触发（优先级高于@消息判断）
                    trigger_type = "keyword"
                elif last_cached.get("is_at_message"):
                    # 真正的@消息触发
                    trigger_type = "at"
                else:
                    # 概率触发（AI主动回复）
                    trigger_type = "ai_decision"

                message_to_save = MessageProcessor.add_metadata_from_cache(
                    raw_content,
                    last_cached.get("sender_id", event.get_sender_id()),
                    last_cached.get("sender_name", event.get_sender_name()),
                    last_cached.get("message_timestamp")
                    or last_cached.get("timestamp"),
                    self.include_timestamp,
                    self.include_sender_info,
                    last_cached.get("mention_info"),  # 传递@信息
                    trigger_type,  # 🆕 v1.0.4: 传递触发方式
                    last_cached.get("poke_info"),  # 🆕 v1.0.9: 传递戳一戳信息
                )

                # 清理系统提示（保存前过滤）
                message_to_save = MessageCleaner.clean_message(message_to_save)

                # 强制日志：添加元数据后的内容
                logger.info(
                    f"🟡 [官方保存-加元数据后] 内容: {message_to_save[:150]}"
                )

            # 如果缓存中没有，尝试从当前消息提取
            if not message_to_save:
                logger.warning(
                    "[消息发送后] ⚠️ 缓存中无消息，从event提取消息（不应该发生）"
                )
                # 使用当前处理后的消息
                processed = MessageCleaner.extract_raw_message_from_event(event)
                if processed:
                    message_to_save = MessageProcessor.add_metadata_to_message(
                        event,
                        processed,
                        self.include_timestamp,
                        self.include_sender_info,
                        None,  # 这种情况下没有mention_info（从event提取的fallback）
                        None,  # trigger_type未知
                        None,  # 🆕 v1.0.9: 无法获取poke_info（fallback情况）
                    )
                    # 清理系统提示（保存前过滤）
                    message_to_save = MessageCleaner.clean_message(message_to_save)
                    logger.info(
                        f"[消息发送后] 从event提取的消息: {message_to_save[:200]}..."
                    )

            if not message_to_save:
                logger.warning("[消息发送后] 无法获取用户消息，跳过官方保存")
                return

            if self.debug_mode:
                logger.info(
                    f"[消息发送后] 准备保存到官方系统的消息: {message_to_save[:300]}..."
                )

            # 准备需要转正的缓存消息（包含那些之前未回复的消息）
            # 缓存中的消息不包含元数据，需要在转正时添加
            # 🔧 修复并发问题：
            # 1. 排除当前正在处理的消息（基于 message_id）
            # 2. 排除其他正在处理中的消息（检查 processing_sessions）
            # 3. 只保存时间戳早于当前消息的缓存消息
            # 4. 🆕 检查主动对话是否正在处理此会话
            cached_messages_to_convert = []
            current_msg_timestamp = None
            current_msg_id = None
            if last_cached:
                current_msg_timestamp = last_cached.get("timestamp")
                current_msg_id = last_cached.get("message_id")
            
            # 🆕 并发保护：检查主动对话是否正在处理此会话（使用循环等待机制）
            proactive_processing = False
            if hasattr(self, "proactive_processing_sessions") and chat_id in self.proactive_processing_sessions:
                # 使用与普通消息并发保护相同的配置
                max_wait_loops = self.concurrent_wait_max_loops
                wait_interval = self.concurrent_wait_interval
                
                for loop_count in range(max_wait_loops):
                    if chat_id not in self.proactive_processing_sessions:
                        # 主动对话已完成，可以继续
                        break
                    
                    if loop_count == 0:
                        logger.info(
                            f"🔒 [并发保护] 检测到主动对话正在处理会话 {chat_id}，"
                            f"开始等待（最多 {max_wait_loops} 次，每次 {wait_interval} 秒）..."
                        )
                    
                    await asyncio.sleep(wait_interval)
                    
                    if self.debug_mode:
                        logger.info(
                            f"  [主动对话并发等待] 第 {loop_count + 1}/{max_wait_loops} 次检测..."
                        )
                else:
                    # 循环结束仍在处理
                    if chat_id in self.proactive_processing_sessions:
                        proactive_start_time = self.proactive_processing_sessions.get(chat_id, 0)
                        elapsed_time = time.time() - proactive_start_time
                        
                        # 如果等待超时，清除标记并继续（避免死锁）
                        del self.proactive_processing_sessions[chat_id]
                        logger.warning(
                            f"⚠️ [并发保护] 等待 {max_wait_loops * wait_interval:.1f} 秒后主动对话仍在处理"
                            f"（已运行 {elapsed_time:.1f} 秒），已清除标记并继续执行"
                        )
                
                # 再次检查是否仍在处理（可能在等待期间完成了）
                proactive_processing = chat_id in self.proactive_processing_sessions
            
            if (
                chat_id in self.pending_messages_cache
                and len(self.pending_messages_cache[chat_id]) > 0
                and not proactive_processing  # 🆕 如果主动对话正在处理，跳过缓存转正
            ):
                # 🔧 修复并发问题：过滤掉正在处理中的消息
                # 获取当前正在处理中的所有消息ID
                processing_msg_ids = set(self.processing_sessions.keys())
                
                raw_cached = []
                skipped_processing = 0
                for msg in self.pending_messages_cache[chat_id]:
                    msg_id = msg.get("message_id")
                    msg_timestamp = msg.get("timestamp", 0)
                    
                    # 排除当前消息
                    if current_msg_id and msg_id == current_msg_id:
                        continue
                    
                    # 排除正在处理中的消息（这些消息会自己保存）
                    if msg_id and msg_id in processing_msg_ids:
                        skipped_processing += 1
                        if self.debug_mode:
                            logger.info(f"[消息发送后] 跳过正在处理中的消息: {msg_id[:30]}...")
                        continue
                    
                    # 只保存时间戳早于当前消息的缓存消息
                    if current_msg_timestamp and msg_timestamp >= current_msg_timestamp:
                        continue
                    
                    raw_cached.append(msg)
                
                if skipped_processing > 0:
                    logger.info(f"[消息发送后] 跳过 {skipped_processing} 条正在处理中的消息（并发保护）")
                
                if raw_cached:
                    logger.info(f"[消息发送后] 发现 {len(raw_cached)} 条待转正的缓存消息")
                else:
                    logger.info(f"[消息发送后] 没有待转正的缓存消息")

                # 处理每条缓存消息，使用缓存中的发送者信息添加元数据
                for cached_msg in raw_cached:
                    if isinstance(cached_msg, dict) and "content" in cached_msg:
                        # 获取处理后的消息内容（不含元数据）
                        raw_content = cached_msg["content"]

                        # 使用缓存中保存的发送者信息添加元数据
                        # 这样每条消息都会有正确的发送者信息
                        # 🆕 v1.0.4: 根据缓存中的触发方式信息确定trigger_type
                        # 注意：需要同时检查 has_trigger_keyword 来正确判断触发方式
                        trigger_type = None
                        if cached_msg.get("has_trigger_keyword"):
                            # 关键词触发（优先级高于@消息判断）
                            trigger_type = "keyword"
                        elif cached_msg.get("is_at_message"):
                            # 真正的@消息触发
                            trigger_type = "at"
                        else:
                            # 概率触发（AI主动回复）
                            trigger_type = "ai_decision"

                        msg_content = MessageProcessor.add_metadata_from_cache(
                            raw_content,
                            cached_msg.get("sender_id", "unknown"),
                            cached_msg.get("sender_name", "未知用户"),
                            cached_msg.get("message_timestamp")
                            or cached_msg.get("timestamp"),
                            self.include_timestamp,
                            self.include_sender_info,
                            cached_msg.get("mention_info"),  # 传递@信息
                            trigger_type,  # 🆕 v1.0.4: 传递触发方式
                            cached_msg.get("poke_info"),  # 🆕 v1.0.9: 传递戳一戳信息
                        )

                        # 清理系统提示（保存前过滤）
                        msg_content = MessageCleaner.clean_message(msg_content)

                        # 🔧 修复：保存图片URL到转正消息中（如果存在）
                        # 这样缓存中的图片信息不会在转正时丢失
                        cached_image_urls = cached_msg.get("image_urls", [])
                        
                        # 添加到转正列表
                        convert_entry = {
                            "role": cached_msg.get("role", "user"),
                            "content": msg_content,
                        }
                        
                        # 🔧 如果有图片URL，添加到转正条目中
                        if cached_image_urls:
                            convert_entry["image_urls"] = cached_image_urls
                        
                        cached_messages_to_convert.append(convert_entry)

                        if self.debug_mode:
                            sender_info = f"{cached_msg.get('sender_name')}(ID: {cached_msg.get('sender_id')})"
                            image_info = f", 图片{len(cached_image_urls)}张" if cached_image_urls else ""
                            logger.info(
                                f"[消息发送后] 转正消息（已添加元数据，发送者: {sender_info}{image_info}）: {msg_content[:100]}..."
                            )
            else:
                logger.info(f"[消息发送后] 没有待转正的缓存消息")

            # 保存到官方对话系统（包含缓存转正+去重）
            # 注意：去重逻辑在 save_to_official_conversation_with_cache 内部处理
            # 会自动过滤掉与现有官方历史重复的消息
            
            # 🔧 确定是否保存AI回复
            # - 重复消息拦截时：不保存AI回复（bot_reply_to_save 已经是 None）
            # - AI调用错误时：不保存AI回复
            # - 正常情况：保存AI回复
            if is_duplicate_blocked:
                bot_to_save = None
                logger.info(
                    f"[消息发送后] 准备保存: 缓存{len(cached_messages_to_convert)}条 + 当前用户消息（跳过AI回复，重复消息已拦截）"
                )
            elif not is_llm_result and ai_error_flag:
                bot_to_save = None
                logger.info(
                    f"[消息发送后] 准备保存: 缓存{len(cached_messages_to_convert)}条 + 当前用户消息（跳过AI回复，AI调用错误）"
                )
            else:
                bot_to_save = bot_reply_to_save
                logger.info(
                    f"[消息发送后] 准备保存: 缓存{len(cached_messages_to_convert)}条 + 当前对话(用户+AI)"
                )

            success = await ContextManager.save_to_official_conversation_with_cache(
                event,
                cached_messages_to_convert,  # 待转正的缓存消息（未去重，交给方法内部处理）
                message_to_save,  # 当前用户消息（已添加时间戳和发送者信息）
                bot_to_save,  # AI回复
                self.context,
            )

            if success:
                logger.info(f"[消息发送后] ✅ 成功保存到官方对话系统")
                # 成功保存后，清理已保存的缓存消息
                # 🔧 修复并发问题：
                # 1. 只清理时间戳 <= 当前消息的缓存消息
                # 2. 保留正在处理中的消息（它们会自己保存）
                # 3. 保留后续新进来的消息
                # 4. 🆕 如果主动对话正在处理，跳过缓存清理
                if proactive_processing:
                    logger.info(
                        f"[消息发送后] 🔒 主动对话正在处理，跳过缓存清理（由主动对话负责）"
                    )
                elif chat_id in self.pending_messages_cache:
                    original_count = len(self.pending_messages_cache[chat_id])
                    
                    # 获取当前正在处理中的所有消息ID
                    processing_msg_ids = set(self.processing_sessions.keys())
                    
                    # 保留：时间戳晚于当前消息的 或 正在处理中的消息
                    new_cache = []
                    for msg in self.pending_messages_cache[chat_id]:
                        msg_id = msg.get("message_id")
                        msg_timestamp = msg.get("timestamp", 0)
                        
                        # 保留正在处理中的消息（排除当前消息）
                        if msg_id and msg_id in processing_msg_ids and msg_id != current_msg_id:
                            new_cache.append(msg)
                            continue
                        
                        # 保留时间戳晚于当前消息的缓存消息
                        if current_msg_timestamp and msg_timestamp > current_msg_timestamp:
                            new_cache.append(msg)
                            continue
                    
                    self.pending_messages_cache[chat_id] = new_cache
                    cleared_count = original_count - len(new_cache)
                    remaining_count = len(new_cache)
                    
                    if remaining_count > 0:
                        logger.info(
                            f"[消息发送后] 已清理 {cleared_count} 条已保存的缓存消息，"
                            f"保留 {remaining_count} 条（正在处理中或后续消息）"
                        )
                    else:
                        logger.info(f"[消息发送后] 已清空消息缓存: {cleared_count} 条")
            else:
                logger.warning(f"[消息发送后] ⚠️ 保存到官方对话系统失败")
                if self.debug_mode:
                    logger.info(f"[消息发送后] 保存失败，缓存保留（待下次使用或清理）")

            if hasattr(self, "_ai_error_message_ids"):
                try:
                    self._ai_error_message_ids.discard(message_id)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[消息发送后] 保存AI回复时发生错误: {e}", exc_info=True)

    def _is_enabled(self, event: AstrMessageEvent) -> bool:
        """
        检查当前群组是否启用插件

        判断逻辑：
        - 私聊直接返回False（不处理）
        - enabled_groups为空则全部群聊启用
        - enabled_groups有值则仅列表内的群启用

        Args:
            event: 消息事件对象

        Returns:
            True=启用，False=未启用
        """
        # 只处理群消息,不处理私聊
        if event.is_private_chat():
            if self.debug_mode:
                logger.info("插件不处理私聊消息")
            return False

        # 获取启用的群组列表
        enabled_groups = self.enabled_groups

        if self.debug_mode:
            logger.info(f"当前配置的启用群组列表: {enabled_groups}")

        # 如果列表为空,则在所有群聊中启用
        if not enabled_groups or len(enabled_groups) == 0:
            if self.debug_mode:
                logger.info("未配置群组列表,在所有群聊中启用")
            return True

        # 如果列表不为空,检查当前群组是否在列表中
        group_id = event.get_group_id()
        if group_id in enabled_groups:
            if self.debug_mode:
                logger.info(f"群组 {group_id} 在启用列表中")
            return True
        else:
            if self.debug_mode:
                logger.info(f"群组 {group_id} 未在启用列表中")
            return False

    def _is_poke_enabled_in_group(self, chat_id: str) -> bool:
        """
        检查当前群组是否在戳一戳功能白名单中

        判断逻辑：
        - poke_enabled_groups为空则所有群聊都允许戳一戳功能
        - poke_enabled_groups有值则仅列表内的群允许戳一戳功能

        Args:
            chat_id: 群组ID（字符串）

        Returns:
            True=允许戳一戳功能，False=不允许
        """
        # 如果白名单为空，所有群都允许
        if not self.poke_enabled_groups or len(self.poke_enabled_groups) == 0:
            return True

        # 检查当前群组是否在白名单中
        chat_id_str = str(chat_id)
        if chat_id_str in self.poke_enabled_groups:
            if self.debug_mode:
                logger.info(
                    f"【戳一戳白名单】群组 {chat_id} 在白名单中，允许戳一戳功能"
                )
            return True
        else:
            if self.debug_mode:
                logger.info(
                    f"【戳一戳白名单】群组 {chat_id} 不在白名单中，禁止戳一戳功能"
                )
            return False

    def _get_message_id(self, event: AstrMessageEvent) -> str:
        """
        生成消息的唯一标识符

        用于跨处理器标记消息（例如标记指令消息）

        Args:
            event: 消息事件对象

        Returns:
            消息的唯一标识字符串
        """
        try:
            # 使用 发送者ID + 群组ID + 消息内容 的组合作为唯一标识
            sender_id = event.get_sender_id()
            group_id = (
                event.get_group_id() if not event.is_private_chat() else "private"
            )
            msg_content = event.get_message_str()[:100]  # 只取前100字符避免过长

            # 🔧 修复：使用 hashlib.md5 生成稳定的哈希标识（跨进程一致）
            hash_input = f"{sender_id}_{group_id}_{msg_content}".encode("utf-8")
            content_hash = hashlib.md5(hash_input).hexdigest()[:16]  # 取前16位即可
            msg_id = f"{sender_id}_{group_id}_{content_hash}"
            return msg_id
        except Exception as e:
            # 如果生成失败，返回一个基于时间的唯一ID
            return f"fallback_{time.time()}_{random.randint(1000, 9999)}"

    def _normalize_bare(self, s: str) -> str:
        """
        归一化字符串：
        - 去除所有空白
        - 转小写
        - 去掉开头的任意非字母数字字符（视为前缀符号，如 / ! # 等）
        返回“裸指令/裸文本”以便与平台无关地比较。
        """
        try:
            s2 = "".join(s.split()).lower()
            i = 0
            while i < len(s2) and not s2[i].isalnum():
                i += 1
            return s2[i:]
        except Exception:
            return ""

    def _is_command_message(self, event: AstrMessageEvent) -> bool:
        """
        检测消息是否为指令消息（根据配置的指令前缀和完整指令列表）

        支持以下格式的检测：
        1. /command 或 !command 等（直接以前缀开头）
        2. @机器人 /command（@ 机器人后跟指令）
        3. @[AT:机器人ID] /command（消息链中 @ 后跟指令）
        4. 【v1.1.2新增】完整指令字符串检测：
           - @机器人 new 或 new（单独的指令，全字符串匹配）
           - 会自动去除@组件和空格/空白符进行匹配
           - @机器人 new你好 或 new你好 不算指令（有其他内容）

        如果开启了指令过滤功能，并且消息符合指令格式，
        则认为是指令消息，本插件应跳过处理（但不影响其他插件）

        Args:
            event: 消息事件对象

        Returns:
            True=是指令消息（应跳过），False=不是指令消息
        """
        # 检查是否启用指令过滤功能
        enable_filter = self.enable_command_filter
        if not enable_filter:
            if self.debug_mode:
                logger.info("指令过滤功能未启用")
            return False

        # 获取配置的指令前缀列表
        command_prefixes = self.command_prefixes

        # 获取完整指令检测配置
        enable_full_cmd = self.enable_full_command_detection
        full_command_list = self.full_command_list

        # 获取指令前缀匹配配置（v1.2.0新增）
        enable_prefix_match = self.enable_command_prefix_match
        prefix_match_list = self.command_prefix_match_list

        # 如果所有检测方式都未配置，直接返回
        has_prefix_filter = bool(command_prefixes)
        has_full_cmd = enable_full_cmd and bool(full_command_list)
        has_prefix_match = enable_prefix_match and bool(prefix_match_list)

        if not has_prefix_filter and not has_full_cmd and not has_prefix_match:
            if self.debug_mode:
                logger.info(
                    "指令过滤已启用，但未配置任何前缀、完整指令或前缀匹配指令！"
                )
            return False

        # 输出检测开始日志
        if self.debug_mode:
            logger.info(f"开始指令检测")
            if command_prefixes:
                logger.info(f"  - 配置的前缀: {command_prefixes}")
            if has_full_cmd:
                logger.info(f"  - 完整指令列表: {full_command_list}")
            if has_prefix_match:
                logger.info(f"  - 前缀匹配指令列表: {prefix_match_list}")
            logger.info(f"  - 消息内容: {event.get_message_str()}")

        try:
            # ✅ 关键：使用原始消息链（event.message_obj.message）
            # AstrBot 的 WakingCheckStage 会修改 event.message_str，
            # 但不会修改 event.message_obj.message！
            original_messages = event.message_obj.message
            if not original_messages:
                if self.debug_mode:
                    logger.info("[指令检测] 原始消息链为空")
                return False

            if self.debug_mode:
                logger.info(f"[指令检测] 原始消息链组件数: {len(original_messages)}")

            # ========== 第一步：检查指令前缀 ==========
            if command_prefixes:
                # 检查原始消息链中的第一个 Plain 组件
                for component in original_messages:
                    if isinstance(component, Plain):
                        # 获取第一个 Plain 组件的原始文本
                        first_text = component.text.strip()

                        if self.debug_mode:
                            logger.info(f"[前缀检测] 第一个Plain文本: '{first_text}'")

                        # 检查是否以任一指令前缀开头
                        for prefix in command_prefixes:
                            if prefix and first_text.startswith(prefix):
                                if self.debug_mode:
                                    logger.info(
                                        f"🚫 [指令过滤-前缀] 检测到指令前缀 '{prefix}'，原始文本: {first_text[:50]}... - 插件跳过处理"
                                    )
                                return True

                        # 找到第一个 Plain 组件后就停止
                        break

            # ========== 第二步：检查完整指令字符串 ==========
            if enable_full_cmd and full_command_list:
                # 提取所有Plain组件的文本，忽略At组件
                plain_texts = []
                for component in original_messages:
                    if isinstance(component, Plain):
                        plain_texts.append(component.text)
                    # 跳过At、AtAll等组件

                # 合并所有Plain文本
                combined_text = "".join(plain_texts)

                # 去除所有空格和空白符（包括空格、制表符、换行符等）
                cleaned_text = "".join(combined_text.split())

                if self.debug_mode:
                    logger.info(f"[完整指令检测] 合并后文本: '{combined_text}'")
                    logger.info(f"[完整指令检测] 清理后文本: '{cleaned_text}'")

                # 检查是否完全匹配配置的完整指令
                for cmd in full_command_list:
                    if not cmd:  # 跳过空字符串
                        continue

                    # 同样去除指令配置中的空格
                    cleaned_cmd = "".join(str(cmd).split())

                    # 全字符串匹配（大小写敏感）
                    if cleaned_text == cleaned_cmd:
                        if self.debug_mode:
                            logger.info(
                                f"🚫 [指令过滤-完整匹配] 检测到完整指令 '{cmd}'，清理后文本: '{cleaned_text}' - 插件跳过处理"
                            )
                        return True

            # ========== 第三步：检查指令前缀匹配（v1.2.0新增） ==========
            if has_prefix_match:
                # 提取所有Plain组件的文本，忽略At组件
                plain_texts = []
                for component in original_messages:
                    if isinstance(component, Plain):
                        plain_texts.append(component.text)

                # 合并所有Plain文本
                combined_text = "".join(plain_texts)

                # 去除开头的空白符，但保留中间的空格（用于判断指令边界）
                stripped_text = combined_text.lstrip()

                if self.debug_mode:
                    logger.info(f"[前缀匹配检测] 去除开头空白后文本: '{stripped_text}'")

                # 检查是否以配置的指令开头
                for cmd in prefix_match_list:
                    if not cmd:  # 跳过空字符串
                        continue

                    cmd_str = str(cmd).strip()
                    if not cmd_str:
                        continue

                    # 检查消息是否以该指令开头
                    if stripped_text.startswith(cmd_str):
                        # 检查指令后面是否为空格、消息结束或其他空白符
                        # 避免误匹配（如 'add' 不应匹配 'address'）
                        remaining = stripped_text[len(cmd_str) :]
                        if not remaining or remaining[0].isspace():
                            if self.debug_mode:
                                logger.info(
                                    f"🚫 [指令过滤-前缀匹配] 检测到指令前缀 '{cmd_str}'，原始文本: '{stripped_text[:50]}...' - 插件跳过处理"
                                )
                            return True

            if self.debug_mode:
                logger.info("[指令检测] 未检测到指令格式，继续正常处理")
            return False

        except Exception as e:
            # 出错时不影响主流程，只记录错误日志
            logger.error(f"[指令检测] 发生错误: {e}", exc_info=True)
            return False

    def _is_user_blacklisted(self, event: AstrMessageEvent) -> bool:
        """
        检测发送者是否在用户黑名单中（v1.0.7新增）

        如果用户在黑名单中，本插件将忽略该消息，但不影响其他插件和官方功能。

        Args:
            event: 消息事件对象

        Returns:
            bool: True=在黑名单中（应该忽略），False=不在黑名单中（正常处理）
        """
        try:
            # 检查是否启用了黑名单功能
            if not self.enable_user_blacklist:
                return False

            # 获取黑名单列表
            blacklist = self.blacklist_user_ids
            if not blacklist:
                # 黑名单为空，不过滤任何用户
                return False

            # 提取发送者的用户ID
            sender_id = event.get_sender_id()

            # 将 sender_id 转换为字符串进行比对（确保类型一致）
            sender_id_str = str(sender_id)

            # 检查是否在黑名单中（支持字符串和数字类型的ID）
            is_blacklisted = (
                sender_id in blacklist
                or sender_id_str in blacklist
                or (
                    int(sender_id_str) in blacklist
                    if sender_id_str.isdigit()
                    else False
                )
            )

            if is_blacklisted:
                if self.debug_mode:
                    logger.info(
                        f"🚫 [用户黑名单] 用户 {sender_id} 在黑名单中，本插件跳过处理该消息"
                    )
                return True

            return False

        except Exception as e:
            # 发生错误时不影响主流程，只记录错误日志
            logger.error(f"[用户黑名单检测] 发生错误: {e}", exc_info=True)
            return False

    def _should_ignore_at_all(self, event: AstrMessageEvent) -> bool:
        """
        检测是否应该忽略@全体成员的消息

        这是插件内部的额外过滤机制，作为AstrBot平台配置的双保险。
        即使平台未配置忽略@全体成员，开启此功能后插件也会过滤掉这类消息。

        Args:
            event: 消息事件对象

        Returns:
            bool: True=应该忽略这条消息（包含@全体成员），False=继续处理
        """
        try:
            # 检查是否启用了忽略@全体成员功能
            if not self.ignore_at_all_enabled:
                if self.debug_mode:
                    logger.info("[@全体成员检测] 功能未启用，跳过检测")
                return False

            # 【修复】使用原始消息链，与指令检测保持一致
            # event.get_messages() 可能返回处理后的消息链，AtAll组件可能已被移除或转换
            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "message"
            ):
                if self.debug_mode:
                    logger.info("[@全体成员检测] 无法获取原始消息链")
                return False

            original_messages = event.message_obj.message
            if not original_messages:
                if self.debug_mode:
                    logger.info("[@全体成员检测] 原始消息链为空")
                return False

            # 【调试】输出消息链详细信息
            if self.debug_mode:
                logger.info(f"[@全体成员检测] 消息链组件数: {len(original_messages)}")
                for i, component in enumerate(original_messages):
                    component_type = type(component).__name__
                    logger.info(f"[@全体成员检测] 组件{i}: 类型={component_type}")
                    if isinstance(component, At):
                        logger.info(f"[@全体成员检测] At组件详情: qq={component.qq}")
                    elif isinstance(component, AtAll):
                        logger.info(f"[@全体成员检测] 检测到AtAll组件")

            # 检查消息中是否包含AtAll组件或At组件(qq="all")
            for component in original_messages:
                # 检查AtAll类型
                if isinstance(component, AtAll):
                    if self.debug_mode:
                        logger.info(
                            "[@全体成员检测] 检测到AtAll类型组件，根据配置忽略处理"
                        )
                    return True
                # 检查At类型且qq为"all"的情况
                if isinstance(component, At):
                    qq_value = str(component.qq).lower()
                    if qq_value == "all":
                        if self.debug_mode:
                            logger.info(
                                f"[@全体成员检测] 检测到At(qq='all')组件，根据配置忽略处理"
                            )
                        return True

            # 没有检测到@全体成员
            if self.debug_mode:
                logger.info("[@全体成员检测] 未检测到@全体成员相关组件")
            return False

        except Exception as e:
            logger.error(f"[@全体成员检测] 发生错误: {e}", exc_info=True)
            # 发生错误时为了安全起见，不忽略消息（保持原有行为）
            return False

    def _should_ignore_at_others(self, event: AstrMessageEvent) -> bool:
        """
        检测是否应该忽略@他人的消息

        根据配置决定：
        1. 如果未启用此功能，返回False（不忽略）
        2. 如果启用了，检测消息是否@了其他人：
           - strict模式：只要@了其他人就忽略
           - allow_with_bot模式：@了其他人但也@了机器人，则不忽略

        Args:
            event: 消息事件对象

        Returns:
            bool: True=应该忽略这条消息，False=继续处理
        """
        try:
            # 检查是否启用了忽略@他人功能
            if not self.enable_ignore_at_others:
                return False

            # 获取忽略模式
            ignore_mode = self.ignore_at_others_mode

            # 获取机器人自己的ID
            bot_id = event.get_self_id()

            # 获取消息组件列表
            messages = event.get_messages()
            if not messages:
                return False

            # 检查消息中的At组件
            has_at_others = False  # 是否@了其他人
            has_at_bot = False  # 是否@了机器人

            for component in messages:
                if isinstance(component, At):
                    mentioned_id = str(component.qq)

                    # 检查是否@了机器人
                    if mentioned_id == bot_id:
                        has_at_bot = True
                        if self.debug_mode:
                            logger.info(f"[@他人检测] 检测到@机器人: ID={mentioned_id}")
                    # 检查是否@了其他人（排除@全体成员）
                    elif mentioned_id.lower() != "all":
                        has_at_others = True
                        mentioned_name = (
                            component.name
                            if hasattr(component, "name") and component.name
                            else ""
                        )
                        if self.debug_mode:
                            logger.info(
                                f"[@他人检测] 检测到@其他人: ID={mentioned_id}, 名称={mentioned_name or '未知'}"
                            )

            # 若消息中包含对机器人的 @，无论模式如何都应该继续处理
            if has_at_bot:
                if self.debug_mode:
                    logger.info("[@他人检测] 检测到@机器人，继续处理该消息")
                return False

            # 根据模式决定是否忽略
            if ignore_mode == "strict":
                # strict模式：只要@了其他人就忽略
                if has_at_others:
                    if self.debug_mode:
                        logger.info(
                            f"[@他人检测-strict模式] 消息中@了其他人，本插件跳过处理"
                        )
                    return True
            elif ignore_mode == "allow_with_bot":
                # allow_with_bot模式：@了其他人但也@了机器人，则继续处理
                if has_at_others and not has_at_bot:
                    if self.debug_mode:
                        logger.info(
                            f"[@他人检测-allow_with_bot模式] 消息中@了其他人但未@机器人，本插件跳过处理"
                        )
                    return True
                elif has_at_others and has_at_bot:
                    if self.debug_mode:
                        logger.info(
                            f"[@他人检测-allow_with_bot模式] 消息中@了其他人但也@了机器人，继续处理"
                        )

            return False

        except Exception as e:
            # 出错时不影响主流程，只记录错误日志
            logger.error(f"[@他人检测] 发生错误: {e}", exc_info=True)
            return False

    async def _check_mention_others(self, event: AstrMessageEvent) -> dict:
        """
        检测消息中是否@了别人（不是机器人自己）

        Args:
            event: 消息事件对象

        Returns:
            dict: 包含@信息的字典，如果没有@别人则返回None
                  格式: {"mentioned_user_id": "xxx", "mentioned_user_name": "xxx"}
        """
        try:
            # 获取机器人自己的ID
            bot_id = event.get_self_id()

            # 获取消息组件列表
            messages = event.get_messages()
            if not messages:
                return None

            # 检查消息中的At组件
            for component in messages:
                if isinstance(component, At):
                    # 获取被@的用户ID
                    mentioned_id = str(component.qq)

                    # 如果@的不是机器人自己，且不是@全体成员
                    if mentioned_id != bot_id and mentioned_id.lower() != "all":
                        mentioned_name = (
                            component.name
                            if hasattr(component, "name") and component.name
                            else ""
                        )

                        # 强制输出 @ 检测日志（使用 INFO 级别确保可见）
                        logger.info(
                            f"🔍 [@检测-@别人] 发现@其他用户: ID={mentioned_id}, 名称={mentioned_name or '未知'}"
                        )
                        if self.debug_mode:
                            logger.info(
                                f"【@检测】详细信息: mentioned_id={mentioned_id}, mentioned_name={mentioned_name}"
                            )

                        return {
                            "mentioned_user_id": mentioned_id,
                            "mentioned_user_name": mentioned_name,
                        }

            # 未检测到@别人，输出日志（仅在debug模式）
            if self.debug_mode:
                logger.info("【@检测】未检测到@其他用户")
            return None

        except Exception as e:
            # 出错时不影响主流程，只记录错误日志
            logger.error(f"检测@提及时发生错误: {e}", exc_info=True)
            return None

    def _check_poke_message(self, event: AstrMessageEvent) -> dict:
        """
        检测是否为戳一戳消息（v1.0.9新增）

        ⚠️ 仅支持QQ平台的aiocqhttp消息事件

        根据配置决定如何处理：
        1. ignore模式：忽略所有戳一戳消息
        2. bot_only模式：只处理戳机器人的消息
        3. all模式：接受所有戳一戳消息

        Args:
            event: 消息事件对象

        Returns:
            dict: 戳一戳信息，格式:
                  {
                      "is_poke": True/False,  # 是否为戳一戳消息
                      "should_ignore": True/False,  # 是否应该忽略（本插件不处理）
                      "poke_info": {  # 戳一戳详细信息（仅当应该处理时存在）
                          "is_poke_bot": True/False,  # 是否戳的是机器人
                          "sender_id": "xxx",  # 戳人者ID
                          "sender_name": "xxx",  # 戳人者昵称
                          "target_id": "xxx",  # 被戳者ID
                          "target_name": "xxx"  # 被戳者昵称（可能为空）
                      }
                  }
        """
        try:
            # 获取配置的戳一戳处理模式
            poke_mode = self.poke_message_mode

            # 检查平台是否为aiocqhttp
            if event.get_platform_name() != "aiocqhttp":
                return {"is_poke": False, "should_ignore": False}

            # 获取原始消息对象
            raw_message = getattr(event.message_obj, "raw_message", None)
            if not raw_message:
                return {"is_poke": False, "should_ignore": False}

            # 检查是否为戳一戳事件
            # 参考astrbot_plugin_llm_poke的实现
            is_poke = (
                raw_message.get("post_type") == "notice"
                and raw_message.get("notice_type") == "notify"
                and raw_message.get("sub_type") == "poke"
            )

            if not is_poke:
                return {"is_poke": False, "should_ignore": False}

            # 确实是戳一戳消息
            if self.debug_mode:
                logger.info("【戳一戳检测】检测到戳一戳消息")

            # 🆕 白名单检查：检查当前群聊是否允许戳一戳功能
            group_id = raw_message.get("group_id")
            if group_id:
                if not self._is_poke_enabled_in_group(str(group_id)):
                    if self.debug_mode:
                        # 群聊不在白名单中，忽略此戳一戳消息
                        logger.info(
                            f"【戳一戳白名单】群 {group_id} 未在白名单中，忽略戳一戳消息"
                        )
                    return {"is_poke": True, "should_ignore": True}

            # 模式1: ignore - 忽略所有戳一戳消息
            if poke_mode == "ignore":
                if self.debug_mode:
                    logger.info("【戳一戳检测】当前模式为ignore，忽略此消息")
                return {"is_poke": True, "should_ignore": True}

            # 获取戳一戳相关信息
            bot_id = raw_message.get("self_id")
            sender_id = raw_message.get("user_id")
            target_id = raw_message.get("target_id")
            group_id = raw_message.get("group_id")

            # 获取发送者昵称（戳人者）
            sender_name = event.get_sender_name()

            # 获取被戳者昵称（如果可能）
            target_name = ""
            try:
                # 尝试从群信息中获取被戳者昵称
                if group_id and target_id and str(target_id) != str(bot_id):
                    # 这里可以调用API获取成员信息，但为了简化，暂时留空
                    # 后续可以通过 event.get_group() 获取群成员列表来查找
                    pass
            except Exception as e:
                if self.debug_mode:
                    logger.info(f"【戳一戳检测】获取被戳者昵称失败: {e}")

            # 判断是否戳的是机器人
            is_poke_bot = str(target_id) == str(bot_id)

            if self.debug_mode:
                logger.info(
                    f"【戳一戳检测】戳人者ID={sender_id}, 被戳者ID={target_id}, 机器人ID={bot_id}"
                )
                logger.info(f"【戳一戳检测】是否戳机器人: {is_poke_bot}")

            # 模式2: bot_only - 只处理戳机器人的消息
            if poke_mode == "bot_only":
                if not is_poke_bot:
                    if self.debug_mode:
                        logger.info(
                            "【戳一戳检测】当前模式为bot_only，但戳的不是机器人，忽略此消息"
                        )
                    return {"is_poke": True, "should_ignore": True}
                else:
                    logger.info(
                        f"✅ 检测到戳一戳消息（有人戳机器人），当前模式为bot_only，本插件将处理"
                    )
                    return {
                        "is_poke": True,
                        "should_ignore": False,
                        "poke_info": {
                            "is_poke_bot": True,
                            "sender_id": str(sender_id),
                            "sender_name": sender_name or "未知用户",
                            "target_id": str(target_id),
                            "target_name": "",  # 机器人自己，不需要名称
                        },
                    }

            # 模式3: all - 接受所有戳一戳消息
            if poke_mode == "all":
                logger.info(f"✅ 检测到戳一戳消息，当前模式为all，本插件将处理")
                return {
                    "is_poke": True,
                    "should_ignore": False,
                    "poke_info": {
                        "is_poke_bot": is_poke_bot,
                        "sender_id": str(sender_id),
                        "sender_name": sender_name or "未知用户",
                        "target_id": str(target_id),
                        "target_name": target_name or "未知用户",
                    },
                }

            # 未知模式，默认忽略
            logger.warning(f"⚠️ 未知的戳一戳处理模式: {poke_mode}，默认忽略")
            return {"is_poke": True, "should_ignore": True}

        except Exception as e:
            # 出错时不影响主流程，只记录错误日志
            logger.error(f"【戳一戳检测】发生错误: {e}", exc_info=True)
            return {"is_poke": False, "should_ignore": False}

    async def _check_probability(
        self,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        event: AstrMessageEvent,
        poke_info: dict = None,
    ) -> bool:
        """
        读空气概率检查，决定是否处理消息

        Args:
            platform_name: 平台名称
            is_private: 是否私聊
            chat_id: 聊天ID
            event: 消息事件对象（用于获取发送者信息）
            poke_info: 戳一戳信息（可选）

        Returns:
            True=处理，False=跳过
        """
        # 获取当前概率
        current_probability = await ProbabilityManager.get_current_probability(
            platform_name,
            is_private,
            chat_id,
            self.initial_probability,
        )

        if self.debug_mode:
            logger.info(f"  当前概率: {current_probability:.2f}")
            logger.info(f"  初始概率: {self.initial_probability:.2f}")
            logger.info(f"  会话ID: {chat_id}")

        # 应用注意力机制调整概率
        attention_enabled = self.enable_attention_mechanism
        if attention_enabled:
            if self.debug_mode:
                logger.info("  【注意力机制】开始调整概率")

            # 获取当前消息发送者信息
            current_user_id = event.get_sender_id()
            current_user_name = event.get_sender_name()

            # 根据注意力机制调整概率
            # 如果是戳一戳消息且未跳过概率，传递戳一戳增值参考值
            poke_boost_ref = 0.0
            if poke_info and poke_info.get("is_poke"):
                poke_boost_ref = self.poke_bot_probability_boost_reference
                if self.debug_mode:
                    logger.info(
                        f"  【戳一戳增值】检测到戳一戳消息，参考值={poke_boost_ref:.2f}"
                    )
            elif self.debug_mode and poke_info:
                logger.info(
                    f"  【戳一戳增值】poke_info存在但is_poke=False: {poke_info}"
                )
            elif self.debug_mode:
                logger.info("  【戳一戳增值】poke_info为None，无戳一戳消息")

            adjusted_probability = await AttentionManager.get_adjusted_probability(
                platform_name,
                is_private,
                chat_id,
                current_user_id,
                current_user_name,
                current_probability,
                self.attention_increased_probability,
                self.attention_decreased_probability,
                self.attention_duration,
                attention_enabled,
                poke_boost_reference=poke_boost_ref,
            )

            if abs(adjusted_probability - current_probability) > 1e-9:
                logger.info(
                    f"  【注意力机制】概率已调整: {current_probability:.2f} -> {adjusted_probability:.2f}"
                )
                current_probability = adjusted_probability
            else:
                if self.debug_mode:
                    logger.info(
                        f"  【注意力机制】无需调整，使用原概率: {current_probability:.2f}"
                    )

        # 🆕 v1.2.0: 拟人增强模式 - 兴趣话题概率提升
        if self.humanize_mode_enabled:
            try:
                # 从事件中提取消息文本
                message_text = MessageCleaner.extract_raw_message_from_event(event)
                if message_text:
                    interest_boost = (
                        await HumanizeModeManager.get_interest_probability_boost(
                            message_text
                        )
                    )
                    if interest_boost > 0:
                        old_probability = current_probability
                        current_probability = min(
                            1.0, current_probability + interest_boost
                        )
                        logger.info(
                            f"  【拟人增强】检测到兴趣话题，概率提升: {old_probability:.2f} -> {current_probability:.2f} (+{interest_boost:.2f})"
                        )
            except Exception as e:
                if self.debug_mode:
                    logger.warning(f"  【拟人增强】兴趣话题检测失败，跳过: {e}")

        # 🆕 v1.2.3: 对话疲劳机制 - 概率降低
        # 设计说明：疲劳降低是特殊机制，允许突破 attention_decreased_probability 的最低限制
        # 因为疲劳机制的目的就是让连续对话过长时降低回复倾向
        if self.enable_conversation_fatigue and self.enable_attention_mechanism:
            try:
                current_user_id = event.get_sender_id()
                fatigue_info = await AttentionManager.get_conversation_fatigue_info(
                    platform_name, is_private, chat_id, current_user_id
                )
                probability_decrease = fatigue_info.get("probability_decrease", 0.0)
                if probability_decrease > 0:
                    old_probability = current_probability
                    current_probability = current_probability - probability_decrease
                    fatigue_level = fatigue_info.get("fatigue_level", "none")
                    consecutive = fatigue_info.get("consecutive_replies", 0)
                    logger.info(
                        f"  【对话疲劳】检测到{fatigue_level}疲劳(连续{consecutive}轮)，"
                        f"概率降低: {old_probability:.2f} -> {current_probability:.2f} (-{probability_decrease:.2f})"
                    )
            except Exception as e:
                if self.debug_mode:
                    logger.warning(f"  【对话疲劳】获取疲劳信息失败，跳过: {e}")

        # === 最终硬性边界限制 ===
        # 1. 应用用户配置的概率硬性限制（如果启用）
        if self.enable_probability_hard_limit:
            original_prob = current_probability
            current_probability = max(
                self.probability_min_limit,
                min(self.probability_max_limit, current_probability)
            )
            if abs(original_prob - current_probability) > 1e-9:
                logger.info(
                    f"  【概率硬性限制】应用用户配置限制: {original_prob:.2f} -> {current_probability:.2f} "
                    f"(范围: [{self.probability_min_limit:.2f}, {self.probability_max_limit:.2f}])"
                )
        
        # 2. 系统硬性边界 [0, 1]，确保概率在有效范围内
        current_probability = max(0.0, min(1.0, current_probability))

        if self.debug_mode:
            logger.info(f"  【边界检查】最终概率: {current_probability:.2f}")

        # 随机判断
        roll = random.random()
        should_process = roll < current_probability
        if self.debug_mode:
            logger.info(
                f"读空气概率检查: 当前概率={current_probability:.2f}, 随机值={roll:.2f}, 结果={'触发' if should_process else '未触发'}"
            )

        if self.debug_mode:
            logger.info(f"  随机值: {roll:.4f}")
            logger.info(
                f"  判定: {'通过' if should_process else '失败'} ({roll:.4f} {'<' if should_process else '>='} {current_probability:.4f})"
            )

        return should_process
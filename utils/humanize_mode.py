"""
拟人增强模式模块
实现类似MaiBot的拟人效果增强功能

核心功能：
1. 静默状态机 - 连续不回复后进入静默模式，减少LLM调用
2. 历史决策记录 - 让LLM知道自己之前的决策
3. 兴趣话题匹配 - 关键词快速检测是否与兴趣相关
4. 动态消息阈值 - 根据连续不回复次数调整触发阈值

作者: Him666233
版本: v1.2.0
"""

import time
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from astrbot.api import logger

# 详细日志开关
DEBUG_MODE: bool = False


@dataclass
class DecisionRecord:
    """决策记录"""

    timestamp: float
    decision: bool  # True=回复, False=不回复
    reason: str  # 决策理由（可选）
    message_preview: str  # 触发消息预览（前30字）


@dataclass
class ChatHumanizeState:
    """
    聊天的拟人状态

    每个聊天流独立维护一个状态
    """

    # 静默状态
    silent_until_called: bool = False  # 是否处于静默模式
    silent_start_time: float = 0  # 进入静默的时间

    # 连续不回复计数
    consecutive_no_reply_count: int = 0

    # 最后活跃时间（最后一次回复的时间）
    last_active_time: float = field(default_factory=time.time)

    # 最后读取消息的时间
    last_read_time: float = field(default_factory=time.time)

    # 历史决策记录（保留最近N条）
    decision_history: List[DecisionRecord] = field(default_factory=list)

    # 消息积累计数（用于动态阈值）
    pending_message_count: int = 0


class HumanizeModeManager:
    """
    拟人增强模式管理器

    管理所有聊天的拟人状态，提供：
    1. 静默状态机控制
    2. 历史决策记录
    3. 兴趣话题快速检测
    4. 动态消息阈值计算
    """

    # 聊天状态存储
    _chat_states: Dict[str, ChatHumanizeState] = {}
    _lock = asyncio.Lock()

    # 配置缓存
    _config: Optional[dict] = None

    # 默认配置
    DEFAULT_CONFIG = {
        # 静默模式配置
        "silent_mode_threshold": 3,  # 连续不回复N次后进入静默
        "silent_mode_max_duration": 600,  # 静默模式最长持续时间（秒）
        "silent_mode_max_messages": 8,  # 静默模式下积累N条消息后自动退出
        # 动态阈值配置
        "enable_dynamic_threshold": True,  # 启用动态消息阈值
        "base_message_threshold": 1,  # 基础消息阈值
        "max_message_threshold": 3,  # 最大消息阈值
        # 历史决策配置
        "include_decision_history_in_prompt": True,  # 是否在提示词中包含历史决策
        # 兴趣话题配置
        "interest_keywords": [],  # 兴趣关键词列表
        "interest_boost_probability": 0.3,  # 兴趣话题额外提升的概率
    }

    @classmethod
    def initialize(cls, config: dict) -> None:
        """
        初始化管理器

        说明：配置由 main.py 统一提取后传入，此处直接使用传入的值，
        不再提供默认值（避免 AstrBot 平台多次读取配置的问题）

        Args:
            config: 插件配置（由 main.py 统一提取）
        """
        cls._config = config
        if DEBUG_MODE:
            logger.info("[拟人增强] 管理器已初始化")

    @classmethod
    def get_config(cls, key: str, default: Any = None) -> Any:
        """
        获取配置值

        说明：配置由 main.py 统一提取后传入，此处直接从 _config 中获取，
        如果 _config 为 None 则使用 DEFAULT_CONFIG 作为兜底（仅用于单元测试场景）
        """
        if cls._config is None:
            # 仅用于单元测试场景，正常运行时 _config 不应为 None
            return cls.DEFAULT_CONFIG.get(key, default)
        # 直接从配置中获取，不再提供默认值
        return cls._config.get(key, default)

    @classmethod
    async def get_or_create_state(cls, chat_key: str) -> ChatHumanizeState:
        """获取或创建聊天状态"""
        async with cls._lock:
            if chat_key not in cls._chat_states:
                cls._chat_states[chat_key] = ChatHumanizeState()
                if DEBUG_MODE:
                    logger.info(f"[拟人增强] 创建新的聊天状态: {chat_key}")
            return cls._chat_states[chat_key]

    @classmethod
    async def should_skip_ai_decision(
        cls,
        chat_key: str,
        is_mentioned: bool,
        message_text: str,
    ) -> Tuple[bool, str]:
        """
        判断是否应该跳过AI决策（静默模式检查）

        Args:
            chat_key: 聊天唯一标识
            is_mentioned: 是否被提及（@或叫名字）
            message_text: 消息文本

        Returns:
            (should_skip, reason): 是否跳过, 原因
        """
        state = await cls.get_or_create_state(chat_key)
        current_time = time.time()

        # 注意：不在这里增加消息计数，因为在 main.py 的 _check_probability_before_processing
        # 中已经通过 increment_message_count 增加过了，避免双重计数

        # 如果不在静默模式，正常处理
        if not state.silent_until_called:
            return False, ""

        # ===== 静默模式下的检查 =====

        # 检查1: 是否被提及
        if is_mentioned:
            await cls._exit_silent_mode(chat_key, "被提及")
            return False, ""

        # 检查2: 是否超过最大静默时间
        silent_duration = current_time - state.silent_start_time
        max_duration = cls.get_config("silent_mode_max_duration", 600)
        if silent_duration > max_duration:
            await cls._exit_silent_mode(chat_key, f"静默超时({int(silent_duration)}秒)")
            return False, ""

        # 检查3: 是否积累了足够多的消息
        max_messages = cls.get_config("silent_mode_max_messages", 8)
        if state.pending_message_count >= max_messages:
            await cls._exit_silent_mode(
                chat_key, f"消息积累({state.pending_message_count}条)"
            )
            return False, ""

        # 检查4: 兴趣话题检测
        interest_keywords = cls.get_config("interest_keywords", [])
        if interest_keywords and message_text:
            for keyword in interest_keywords:
                if keyword and keyword.lower() in message_text.lower():
                    await cls._exit_silent_mode(chat_key, f"检测到兴趣话题: {keyword}")
                    return False, ""

        # 继续静默
        if DEBUG_MODE:
            remaining = max_duration - silent_duration
            logger.info(
                f"[拟人增强] {chat_key} 处于静默模式，跳过AI决策 "
                f"(剩余{int(remaining)}秒，已积累{state.pending_message_count}条消息)"
            )

        return True, "静默模式"

    @classmethod
    async def _exit_silent_mode(cls, chat_key: str, reason: str) -> None:
        """退出静默模式"""
        state = await cls.get_or_create_state(chat_key)
        state.silent_until_called = False
        state.pending_message_count = 0
        logger.info(f"[拟人增强] {chat_key} 退出静默模式，原因: {reason}")

    @classmethod
    async def record_decision(
        cls,
        chat_key: str,
        decision: bool,
        reason: str = "",
        message_preview: str = "",
    ) -> None:
        """
        记录决策结果

        Args:
            chat_key: 聊天唯一标识
            decision: 决策结果 (True=回复, False=不回复)
            reason: 决策理由
            message_preview: 触发消息预览
        """
        state = await cls.get_or_create_state(chat_key)
        current_time = time.time()

        # 创建决策记录
        record = DecisionRecord(
            timestamp=current_time,
            decision=decision,
            reason=reason[:100] if reason else "",  # 限制长度
            message_preview=message_preview[:30] if message_preview else "",
        )

        # 添加到历史
        state.decision_history.append(record)

        # 限制历史记录数量（固定保留5条，与提示词显示数量一致）
        if len(state.decision_history) > 5:
            state.decision_history = state.decision_history[-5:]

        # 更新状态
        if decision:
            # 回复了，重置连续不回复计数
            state.consecutive_no_reply_count = 0
            state.last_active_time = current_time
            state.pending_message_count = 0

            if DEBUG_MODE:
                logger.info(f"[拟人增强] {chat_key} 决策: 回复")
        else:
            # 不回复，增加计数
            state.consecutive_no_reply_count += 1

            if DEBUG_MODE:
                logger.info(
                    f"[拟人增强] {chat_key} 决策: 不回复 "
                    f"(连续{state.consecutive_no_reply_count}次)"
                )

            # 检查是否应该进入静默模式
            threshold = cls.get_config("silent_mode_threshold", 3)
            if (
                state.consecutive_no_reply_count >= threshold
                and not state.silent_until_called
            ):
                state.silent_until_called = True
                state.silent_start_time = current_time
                logger.info(
                    f"[拟人增强] {chat_key} 进入静默模式 "
                    f"(连续{state.consecutive_no_reply_count}次不回复)"
                )

    @classmethod
    async def get_message_threshold(cls, chat_key: str) -> int:
        """
        获取当前的消息触发阈值

        根据连续不回复次数动态调整：
        - 连续不回复次数越多，需要积累更多消息才触发判断

        Args:
            chat_key: 聊天唯一标识

        Returns:
            消息阈值
        """
        if not cls.get_config("enable_dynamic_threshold", True):
            return cls.get_config("base_message_threshold", 1)

        state = await cls.get_or_create_state(chat_key)

        base = cls.get_config("base_message_threshold", 1)
        max_threshold = cls.get_config("max_message_threshold", 3)

        # 根据连续不回复次数计算阈值
        # 0-2次: 基础阈值
        # 3-4次: 基础+1
        # 5+次: 最大阈值
        if state.consecutive_no_reply_count >= 5:
            threshold = max_threshold
        elif state.consecutive_no_reply_count >= 3:
            threshold = min(base + 1, max_threshold)
        else:
            threshold = base

        if DEBUG_MODE and threshold > base:
            logger.info(
                f"[拟人增强] {chat_key} 动态阈值: {threshold} "
                f"(连续不回复{state.consecutive_no_reply_count}次)"
            )

        return threshold

    @classmethod
    async def should_skip_for_dynamic_threshold(
        cls,
        chat_key: str,
        is_mentioned: bool,
    ) -> Tuple[bool, str, int]:
        """
        检查是否应该因为动态消息阈值而跳过本次判断

        Args:
            chat_key: 聊天唯一标识
            is_mentioned: 是否被提及（@或叫名字）

        Returns:
            (should_skip, reason, current_count): 是否跳过, 原因, 当前消息计数
        """
        # 被提及时不跳过
        if is_mentioned:
            return False, "", 0

        # 如果未启用动态阈值，不跳过
        if not cls.get_config("enable_dynamic_threshold", True):
            return False, "", 0

        state = await cls.get_or_create_state(chat_key)

        # 获取当前阈值
        threshold = await cls.get_message_threshold(chat_key)

        # 增加消息计数（这里用于动态阈值，与静默模式的 pending_message_count 共用）
        # 注意：这个计数在 record_decision 中的回复决策会重置
        current_count = state.pending_message_count

        # 如果未达到阈值，跳过
        if current_count < threshold:
            if DEBUG_MODE:
                logger.info(
                    f"[拟人增强] {chat_key} 动态阈值检查: "
                    f"当前{current_count}条 < 阈值{threshold}条，跳过本次判断"
                )
            return True, f"动态阈值({current_count}/{threshold})", current_count

        # 达到阈值，重置计数并继续判断
        # 注意：这里重置计数，这样如果AI判断不回复，下次需要重新积累消息
        # 如果AI判断回复，record_decision 也会重置计数
        state.pending_message_count = 0

        if DEBUG_MODE:
            logger.info(
                f"[拟人增强] {chat_key} 动态阈值检查: "
                f"已达到{threshold}条阈值，触发判断，重置计数"
            )

        return False, "", current_count

    @classmethod
    async def increment_message_count(cls, chat_key: str) -> int:
        """
        增加消息计数（用于动态阈值）

        Args:
            chat_key: 聊天唯一标识

        Returns:
            增加后的消息计数
        """
        state = await cls.get_or_create_state(chat_key)
        state.pending_message_count += 1
        return state.pending_message_count

    @classmethod
    async def build_decision_history_prompt(cls, chat_key: str) -> str:
        """
        构建历史决策提示词

        用于注入到DecisionAI的提示词中，让AI知道自己之前的决策

        Args:
            chat_key: 聊天唯一标识

        Returns:
            历史决策提示词文本
        """
        if not cls.get_config("include_decision_history_in_prompt", True):
            return ""

        state = await cls.get_or_create_state(chat_key)

        if not state.decision_history:
            return ""

        # 使用全部记录（存储上限已固定为5条）
        recent_decisions = state.decision_history

        lines = ["", "=" * 40, "📋 【你之前的判断记录】", "=" * 40]

        for record in recent_decisions:
            time_str = datetime.fromtimestamp(record.timestamp).strftime("%H:%M:%S")
            decision_str = "✅回复" if record.decision else "❌不回复"

            if record.reason:
                lines.append(f"{time_str}: {decision_str} - {record.reason}")
            else:
                lines.append(f"{time_str}: {decision_str}")

        lines.append("")
        lines.append("提示：保持判断的一致性，如果话题没有变化或没有新的互动需求，")
        lines.append("      可以继续选择不回复，避免过于频繁地打扰对话。")
        lines.append("=" * 40)
        lines.append("")

        return "\n".join(lines)

    @classmethod
    async def check_interest_match(
        cls,
        message_text: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        检查消息是否匹配兴趣话题

        Args:
            message_text: 消息文本

        Returns:
            (is_match, matched_keyword): 是否匹配, 匹配到的关键词
        """
        interest_keywords = cls.get_config("interest_keywords", [])

        if not interest_keywords or not message_text:
            return False, None

        message_lower = message_text.lower()
        for keyword in interest_keywords:
            if keyword and keyword.lower() in message_lower:
                return True, keyword

        return False, None

    @classmethod
    async def get_interest_probability_boost(cls, message_text: str) -> float:
        """
        获取兴趣话题的概率提升值

        Args:
            message_text: 消息文本

        Returns:
            概率提升值 (0.0 - 1.0)
        """
        is_match, keyword = await cls.check_interest_match(message_text)

        if is_match:
            boost = cls.get_config("interest_boost_probability", 0.3)
            if DEBUG_MODE:
                logger.info(f"[拟人增强] 检测到兴趣话题 '{keyword}'，概率提升 {boost}")
            return boost

        return 0.0

    @classmethod
    async def get_state_summary(cls, chat_key: str) -> Dict[str, Any]:
        """获取状态摘要（用于调试）"""
        state = await cls.get_or_create_state(chat_key)

        return {
            "silent_mode": state.silent_until_called,
            "consecutive_no_reply": state.consecutive_no_reply_count,
            "pending_messages": state.pending_message_count,
            "decision_history_count": len(state.decision_history),
            "last_active": datetime.fromtimestamp(state.last_active_time).strftime(
                "%H:%M:%S"
            ),
        }

    @classmethod
    async def reset_state(cls, chat_key: str) -> None:
        """重置聊天状态"""
        async with cls._lock:
            if chat_key in cls._chat_states:
                del cls._chat_states[chat_key]
                logger.info(f"[拟人增强] {chat_key} 状态已重置")

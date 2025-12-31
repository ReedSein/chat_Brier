"""
频率动态调整器 - 自动调整Bot发言频率
根据用户反馈自动调整回复概率，让Bot融入群聊节奏

核心理念：
- 保持"读空气"核心不变
- 通过AI判断用户是否觉得Bot话太多/太少
- 自动微调概率参数

作者: Him666233
版本: v1.1.2
参考: MaiBot frequency_control.py (简化实现)
"""

import time
from typing import Dict, Optional
from astrbot.api.all import logger, Context
from .ai_response_filter import AIResponseFilter

# 详细日志开关（与 main.py 同款方式：单独用 if 控制）
DEBUG_MODE: bool = False
from astrbot.api.event import AstrMessageEvent

# 导入 DecisionAI（延迟导入以避免循环依赖）
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_ai import DecisionAI


class FrequencyAdjuster:
    """
    频率动态调整器

    核心功能：
    - 定期分析最近的对话
    - 使用AI判断发言频率是否合适
    - 自动调整概率参数
    """

    # 默认检查间隔（秒）- 可通过配置或直接设置类变量修改
    CHECK_INTERVAL = 180  # 3分钟检查一次

    def __init__(self, context: Context, config: dict = None):
        """
        初始化频率调整器

        Args:
            context: AstrBot上下文
            config: 插件配置字典（可选）
        """
        self.context = context
        self.config = config or {}

        # 说明：配置由 main.py 统一提取后传入，此处直接使用传入的值，
        # 不再提供默认值（避免 AstrBot 平台多次读取配置的问题）
        self.min_message_count = self.config["frequency_min_message_count"]
        self.adjust_factor_decrease = self.config["frequency_decrease_factor"]
        self.adjust_factor_increase = self.config["frequency_increase_factor"]
        self.min_probability = self.config["frequency_min_probability"]
        self.max_probability = self.config["frequency_max_probability"]

        # 存储每个会话的检查状态（使用完整的会话标识确保隔离）
        # 格式: {chat_key: {"last_check_time": 时间戳, "message_count": 消息数}}
        # 其中 chat_key = "{platform}_{type}_{id}"，例如 "aiocqhttp_group_123456"
        self.check_states: Dict[str, Dict] = {}

        if DEBUG_MODE:
            logger.info("[频率动态调整器] 已初始化")
            logger.info(f"  - 最小消息数: {self.min_message_count}")
            logger.info(
                f"  - 降低系数: {self.adjust_factor_decrease} (降低{(1 - self.adjust_factor_decrease) * 100:.0f}%)"
            )
            logger.info(
                f"  - 提升系数: {self.adjust_factor_increase} (提升{(self.adjust_factor_increase - 1) * 100:.0f}%)"
            )
            logger.info(
                f"  - 概率范围: {self.min_probability:.2f} - {self.max_probability:.2f}"
            )

    def should_check_frequency(self, chat_key: str, message_count: int) -> bool:
        """
        判断是否应该检查频率

        Args:
            chat_key: 会话唯一标识（格式：platform_type_id）
            message_count: 自上次检查以来的消息数量

        Returns:
            True=应该检查，False=暂不检查
        """
        current_time = time.time()

        if chat_key not in self.check_states:
            # 初始化检查状态
            self.check_states[chat_key] = {
                "last_check_time": current_time,
                "message_count": 0,
            }
            if DEBUG_MODE:
                logger.info(f"[频率动态调整器] 会话 {chat_key} 首次初始化，暂不检查")
            return False

        state = self.check_states[chat_key]
        time_since_check = current_time - state["last_check_time"]

        # 条件1: 距离上次检查超过指定时间
        # 条件2: 自上次检查以来有足够的消息
        if (
            time_since_check > self.CHECK_INTERVAL
            and message_count >= self.min_message_count
        ):
            if DEBUG_MODE:
                logger.info(
                    f"[频率动态调整器] ✅ 满足检查条件 - 会话:{chat_key}, "
                    f"距上次检查:{time_since_check:.0f}秒 (需>{self.CHECK_INTERVAL}秒), "
                    f"消息数:{message_count} (需≥{self.min_message_count}条)"
                )
            return True

        # 不满足条件，输出详细信息
        if DEBUG_MODE:
            time_remaining = max(0, self.CHECK_INTERVAL - time_since_check)
            msg_remaining = max(0, self.min_message_count - message_count)
            reasons = []
            if time_since_check <= self.CHECK_INTERVAL:
                reasons.append(f"时间不足(还需{time_remaining:.0f}秒)")
            if message_count < self.min_message_count:
                reasons.append(f"消息不足(还需{msg_remaining}条)")

            logger.info(
                f"[频率动态调整器] ⏸️ 暂不检查 - 会话:{chat_key}, "
                f"原因:{', '.join(reasons)}"
            )

        return False

    async def analyze_frequency(
        self,
        context: Context,
        event: AstrMessageEvent,
        recent_messages: str,
        provider_id: str = "",
        timeout: int = 20,
    ) -> Optional[str]:
        """
        使用AI分析发言频率是否合适

        Args:
            context: AstrBot上下文
            event: 消息事件
            recent_messages: 最近的消息记录
            provider_id: AI提供商ID
            timeout: 超时时间

        Returns:
            "过于频繁" / "过少" / "正常" / None(分析失败)
        """
        try:
            # 使用与 DecisionAI 相同风格的分隔线，在提示词中包裹时间提示块，方便 LLM 识别结构
            separator = "=" * 60
            # time_context 用于承载“当前时间与活跃度提示”这一大段文本
            # 当未启用动态时间段功能时保持为空字符串，不影响原有频率判断逻辑
            time_context = ""

            # 如果开启了动态时间段概率功能（与主插件配置保持一致），
            # 则在频率分析时也让 AI 知道“现在是一天中的哪个时间段、活跃度系数是多少”。
            # 注意：这里只是把时间信息写进提示词，不直接修改概率数值。
            # 🔧 使用字典键访问替代 config.get()，避免 astrBot 平台多次读取配置的问题
            if self.config["enable_dynamic_reply_probability"]:
                try:
                    from .time_period_manager import TimePeriodManager
                    from datetime import datetime as dt

                    # 读取时间段配置 JSON，完全复用 TimePeriodManager 的解析与校验逻辑
                    # 🔧 使用字典键访问替代 config.get()
                    periods_json = self.config["reply_time_periods"]
                    # silent=True 避免频繁重复解析时在日志中刷屏
                    periods = TimePeriodManager.parse_time_periods(
                        periods_json, silent=True
                    )

                    if periods:
                        # 使用与 ProbabilityManager / DecisionAI 一致的时间系数计算方法
                        # current_factor 表示当前时间下推荐的“活跃度倍率”，例如：
                        #  - 0.2 表示应该明显少说话
                        #  - 1.0 表示正常
                        #  - 1.5 表示可以更活跃
                        # 🔧 使用字典键访问替代 config.get()
                        current_factor = TimePeriodManager.calculate_time_factor(
                            current_time=None,
                            periods_config=periods,
                            transition_minutes=self.config[
                                "reply_time_transition_minutes"
                            ],
                            min_factor=self.config["reply_time_min_factor"],
                            max_factor=self.config["reply_time_max_factor"],
                            use_smooth_curve=self.config[
                                "reply_time_use_smooth_curve"
                            ],
                        )

                        now = dt.now()
                        # 将当前时间转换为一天中的分钟数，用于匹配配置中的时间段名称
                        current_minutes = now.hour * 60 + now.minute
                        current_period_name = ""

                        # 在已解析的时间段列表中，找到当前时间所属的时间段名称（支持跨天配置）
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

                                # 时间段跨天（例如 23:00-07:00）时，判断逻辑为
                                #   当前 >= start 或 当前 < end
                                # 否则为普通区间判断 start <= 当前 < end
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
                            except Exception:
                                # 单个时间段解析失败不影响整体，直接跳过即可
                                continue

                        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        weekday_names = [
                            "周一",
                            "周二",
                            "周三",
                            "周四",
                            "周五",
                            "周六",
                            "周日",
                        ]
                        current_weekday = weekday_names[now.weekday()]

                        # 根据 current_factor 的数值区间，给出更直观的中文描述和建议文案，
                        # 这些描述只影响 LLM 的理解，不会改变概率计算代码本身。
                        if current_factor < 0.3:
                            factor_desc = "非常低"
                            activity_suggestion = "用户配置此时段应该很少回复。一般认为Bot应该尽量安静，只有在必要的情况下才发言。"
                        elif current_factor < 0.5:
                            factor_desc = "很低"
                            activity_suggestion = "用户配置此时段应该较少回复。除非话题比较重要或直接与Bot相关，否则应该减少发言。"
                        elif current_factor < 0.8:
                            factor_desc = "偏低"
                            activity_suggestion = "用户配置此时段应该适当减少回复。可以适度降低存在感，不要频繁插话。"
                        elif current_factor <= 1.2:
                            factor_desc = "正常"
                            activity_suggestion = (
                                "用户配置此时段活跃度正常。可以按正常频率参与对话。"
                            )
                        elif current_factor <= 1.5:
                            factor_desc = "偏高"
                            activity_suggestion = "用户配置此时段应该更活跃。可以适当多说一些，让气氛活跃一点。"
                        else:
                            factor_desc = "很高"
                            activity_suggestion = "用户配置此时段应该非常活跃。Bot可以比较健谈，只要不打扰他人正常对话即可。"

                        # time_context 最终是一整块可读性较强的文本，会被直接插入到下面构造的 prompt 中，
                        # 用于告诉 LLM 当前所处时间段和推荐的活跃度。
                        time_context = (
                            f"\n\n{separator}\n"
                            f"🕐 【当前时间与活跃度提示】\n"
                            f"{separator}\n"
                            f"当前时间: {current_time_str} ({current_weekday})\n"
                            f"用户配置的时间段: {current_period_name or '默认时段'}\n"
                            f"活跃度系数: {current_factor:.2f} ({factor_desc})\n"
                            f"建议: {activity_suggestion}\n"
                            f"\n⚠️ 在判断发言频率时，请根据上述活跃度设置，思考当前Bot是否说得太多或太少。\n"
                            f"{separator}\n"
                        )
                except Exception as e:
                    # 时间段配置解析或计算失败时，不影响频率分析主流程，只在调试模式下输出日志
                    if DEBUG_MODE:
                        logger.info(f"[频率动态调整器] 获取时间段配置失败: {e}")

            # 在原有频率分析提示词基础上，前面插入“当前人格与时间说明”这一段，
            # 让 LLM 在判断频率时能够综合考虑人格设定和当前时间段的活跃度建议。
            # 频率分析本身仍然只关注 user/assistant 消息的节奏，不涉及拟人增强的状态机。
            prompt = f"""你是一个群聊观察者。请分析最近的聊天记录，判断AI助手的发言频率是否合适。

【当前人格与时间说明】
- 你需要结合你当前的人格设定，判断在不同时间段下你应该多活跃或少活跃。
- 如果下面提供了“当前时间与活跃度提示”，请参考用户配置的活跃度系数来判断现在说话是否合适。
{time_context}

【消息格式说明】
- "user: xxx" = 用户发送的消息
- "assistant: xxx" = AI助手（你）发送的消息

【重要说明】
- 最近的内容中可能包含系统提示词、内部配置说明或其他非对话文本，这些都不属于群聊参与者的发言，请一律忽略。
- 在判断发言频率时，只关注以"user:"或"assistant:"开头的对话内容，其他任何内容都不要考虑。

最近的聊天记录：
{recent_messages}

请分析：
1. AI助手（即"assistant"角色）的发言是否过于频繁（刷屏、过度活跃）？
2. AI助手（即"assistant"角色）的发言是否过少（太沉默、存在感低）？

判断标准：
- 如果AI（assistant）在短时间内连续回复多条，或者打断了用户（user）之间的正常对话 → 过于频繁
- 如果AI（assistant）长时间不发言，即使有用户（user）提到相关话题也不回应 → 过少
- 如果AI（assistant）的发言频率自然，既不抢话也不冷场 → 正常

**你只能输出以下三个词之一，不要输出任何其他文字、解释或标点：**
- 正常
- 过于频繁
- 过少"""

            # 复用 DecisionAI.call_decision_ai，而不是直接调用底层 provider：
            # 这样可以自动继承人格设定、上下文注入以及统一的思考链过滤逻辑，
            # 同时保持与主读空气逻辑一致的安全性和行为习惯。
            from .decision_ai import DecisionAI

            response = await DecisionAI.call_decision_ai(
                context=context,
                event=event,
                prompt=prompt,
                provider_id=provider_id,
                timeout=timeout,
                prompt_mode="override",
            )

            if not response:
                logger.warning("[频率动态调整器] AI返回为空")
                return None

            # 使用专门的频率判断结果提取器，将 LLM 的自然语言输出归一化为
            # "正常" / "过于频繁" / "过少" 三种枚举值，避免下游逻辑需要解析自由文本。
            decision = AIResponseFilter.extract_frequency_decision(response)

            if decision:
                logger.info(f"[频率动态调整器] AI判断结果: {decision}")
                return decision

            logger.warning(
                f"[频率动态调整器] 无法从AI响应中提取有效判断: {response[:50]}..."
            )
            return None

        except Exception as e:
            logger.error(f"[频率动态调整器] 频率分析失败: {e}")
            return None

    def adjust_probability(self, current_probability: float, decision: str) -> float:
        """
        根据AI判断调整概率

        Args:
            current_probability: 当前概率值
            decision: AI的判断结果 ("过于频繁" / "过少" / "正常")

        Returns:
            调整后的概率值
        """
        if decision == "过于频繁":
            # 降低概率
            new_probability = current_probability * self.adjust_factor_decrease
            logger.info(
                f"[频率动态调整器] 检测到发言过于频繁，降低概率: {current_probability:.2f} → {new_probability:.2f} (系数:{self.adjust_factor_decrease})"
            )

        elif decision == "过少":
            # 提升概率
            new_probability = current_probability * self.adjust_factor_increase

            logger.info(
                f"[频率动态调整器] 检测到发言过少，提升概率: {current_probability:.2f} → {new_probability:.2f} (系数:{self.adjust_factor_increase})"
            )

        else:  # "正常"
            # 保持不变
            new_probability = current_probability

            logger.info(
                f"[频率动态调整器] 发言频率正常，保持概率: {current_probability:.2f}"
            )

        # 限制在合理范围内
        new_probability = max(
            self.min_probability, min(self.max_probability, new_probability)
        )

        return new_probability

    def update_check_state(self, chat_key: str):
        """
        更新检查状态（在完成一次检查后调用）

        Args:
            chat_key: 会话唯一标识（格式：platform_type_id）
        """
        self.check_states[chat_key] = {
            "last_check_time": time.time(),
            "message_count": 0,
        }

    def record_message(self, chat_key: str):
        """
        记录新消息（用于统计消息数量）

        Args:
            chat_key: 会话唯一标识（格式：platform_type_id）
        """
        if chat_key not in self.check_states:
            self.check_states[chat_key] = {
                "last_check_time": time.time(),
                "message_count": 0,
            }

        self.check_states[chat_key]["message_count"] += 1

        if DEBUG_MODE:
            current_count = self.check_states[chat_key]["message_count"]
            logger.info(
                f"[频率动态调整器] 📝 记录消息 - 会话:{chat_key}, "
                f"当前计数:{current_count}/{self.min_message_count}"
            )

    def get_message_count(self, chat_key: str) -> int:
        """
        获取自上次检查以来的消息数量

        Args:
            chat_key: 会话唯一标识（格式：platform_type_id）

        Returns:
            消息数量
        """
        if chat_key not in self.check_states:
            return 0

        return self.check_states[chat_key]["message_count"]

"""
关键词检查工具
负责检查消息中的触发关键词和黑名单关键词

作者: Him666233
版本: v1.1.2
"""

from astrbot.api.all import *

# 详细日志开关（与 main.py 同款方式：单独用 if 控制）
DEBUG_MODE: bool = False


class KeywordChecker:
    """关键词检查工具类"""

    @staticmethod
    def _check_keywords(
        event: AstrMessageEvent, keywords: list, keyword_type: str
    ) -> bool:
        """
        通用关键词检查方法

        Args:
            event: 消息事件
            keywords: 关键词列表
            keyword_type: 关键词类型（用于日志输出，如"触发关键词"或"黑名单关键词"）

        Returns:
            True=包含，False=不包含
        """
        if not keywords:
            return False

        try:
            # 获取消息文本
            message_text = event.get_message_outline()

            # 检查是否包含关键词
            for keyword in keywords:
                if keyword and keyword in message_text:
                    if DEBUG_MODE:
                        logger.info(f"检测到{keyword_type}: {keyword}")
                    return True

            return False

        except Exception as e:
            logger.error(f"检查{keyword_type}时发生错误: {e}")
            return False

    @staticmethod
    def check_trigger_keywords(event: AstrMessageEvent, keywords: list) -> bool:
        """
        检查消息是否包含触发关键词

        Args:
            event: 消息事件
            keywords: 触发关键词列表

        Returns:
            True=包含，False=不包含
        """
        return KeywordChecker._check_keywords(event, keywords, "触发关键词")

    @staticmethod
    def check_trigger_keywords_with_match(
        event: AstrMessageEvent, keywords: list
    ) -> tuple:
        """
        检查消息是否包含触发关键词，并返回匹配到的关键词

        🆕 v1.2.1: 新增方法，用于增强读空气AI的判断

        Args:
            event: 消息事件
            keywords: 触发关键词列表

        Returns:
            (has_keyword, matched_keyword): 是否包含关键词, 匹配到的关键词（未匹配则为空字符串）
        """
        if not keywords:
            return False, ""

        try:
            # 获取消息文本
            message_text = event.get_message_outline()

            # 检查是否包含关键词
            for keyword in keywords:
                if keyword and keyword in message_text:
                    if DEBUG_MODE:
                        logger.info(f"检测到触发关键词: {keyword}")
                    return True, keyword

            return False, ""

        except Exception as e:
            logger.error(f"检查触发关键词时发生错误: {e}")
            return False, ""

    @staticmethod
    def check_blacklist_keywords(event: AstrMessageEvent, keywords: list) -> bool:
        """
        检查消息是否包含黑名单关键词

        Args:
            event: 消息事件
            keywords: 黑名单关键词列表

        Returns:
            True=包含，False=不包含
        """
        return KeywordChecker._check_keywords(event, keywords, "黑名单关键词")

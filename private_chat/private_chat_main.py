"""
私信功能主处理模块

与群聊功能独立的私信处理逻辑，主要特点：
1. 每条消息都回复（无概率筛选和读空气AI）
2. 支持消息聚合（等待一段时间合并多条消息）
3. 独立配置（可与群聊配置不同）
4. 黑名单模式（禁用指定用户）

作者: Him666233
版本: v1.1.2
"""

import time
import asyncio
import random
from typing import Optional, List, Dict, Any
from pathlib import Path

from astrbot.api.all import *
from astrbot.api import logger


class PrivateChatMain:
    """
    私信功能主消息类

    负责协调私信消息的接收、聚合、处理和回复
    """

    def __init__(
        self, context: Context, config: dict, plugin_instance=None, data_dir: str = None
    ):
        """
        初始化私信处理器

        Args:
            context: AstrBot Context对象
            config: 插件配置（包含私信相关配置）
            plugin_instance: 主插件实例（用于共享某些状态）
            data_dir: 插件数据目录路径（从主插件传入）
        """
        self.context = context
        self.config = config
        self.plugin_instance = plugin_instance
        self.data_dir = data_dir

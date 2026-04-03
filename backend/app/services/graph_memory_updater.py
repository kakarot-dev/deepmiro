"""
图谱记忆更新服务
将模拟中的Agent活动动态更新到图谱存储后端中
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from ..storage.factory import get_storage
from ..storage.base import GraphStorage
from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale

logger = get_logger('mirofish.graph_memory_updater')


@dataclass
class AgentActivity:
    """Agent活动记录"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """
        将活动转换为可以发送给存储后端的文本描述

        采用自然语言描述格式，让NER能够从中提取实体和关系
        不添加模拟相关的前缀，避免误导图谱更新
        """
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }

        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()

        return f"{self.agent_name}: {description}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"\u53d1\u5e03\u4e86\u4e00\u6761\u5e16\u5b50\uff1a\u300c{content}\u300d"
        return "\u53d1\u5e03\u4e86\u4e00\u6761\u5e16\u5b50"

    def _describe_like_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if post_content and post_author:
            return f"\u70b9\u8d5e\u4e86{post_author}\u7684\u5e16\u5b50\uff1a\u300c{post_content}\u300d"
        elif post_content:
            return f"\u70b9\u8d5e\u4e86\u4e00\u6761\u5e16\u5b50\uff1a\u300c{post_content}\u300d"
        elif post_author:
            return f"\u70b9\u8d5e\u4e86{post_author}\u7684\u4e00\u6761\u5e16\u5b50"
        return "\u70b9\u8d5e\u4e86\u4e00\u6761\u5e16\u5b50"

    def _describe_dislike_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if post_content and post_author:
            return f"\u8e29\u4e86{post_author}\u7684\u5e16\u5b50\uff1a\u300c{post_content}\u300d"
        elif post_content:
            return f"\u8e29\u4e86\u4e00\u6761\u5e16\u5b50\uff1a\u300c{post_content}\u300d"
        elif post_author:
            return f"\u8e29\u4e86{post_author}\u7684\u4e00\u6761\u5e16\u5b50"
        return "\u8e29\u4e86\u4e00\u6761\u5e16\u5b50"

    def _describe_repost(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        if original_content and original_author:
            return f"\u8f6c\u53d1\u4e86{original_author}\u7684\u5e16\u5b50\uff1a\u300c{original_content}\u300d"
        elif original_content:
            return f"\u8f6c\u53d1\u4e86\u4e00\u6761\u5e16\u5b50\uff1a\u300c{original_content}\u300d"
        elif original_author:
            return f"\u8f6c\u53d1\u4e86{original_author}\u7684\u4e00\u6761\u5e16\u5b50"
        return "\u8f6c\u53d1\u4e86\u4e00\u6761\u5e16\u5b50"

    def _describe_quote_post(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        base = ""
        if original_content and original_author:
            base = f"\u5f15\u7528\u4e86{original_author}\u7684\u5e16\u5b50\u300c{original_content}\u300d"
        elif original_content:
            base = f"\u5f15\u7528\u4e86\u4e00\u6761\u5e16\u5b50\u300c{original_content}\u300d"
        elif original_author:
            base = f"\u5f15\u7528\u4e86{original_author}\u7684\u4e00\u6761\u5e16\u5b50"
        else:
            base = "\u5f15\u7528\u4e86\u4e00\u6761\u5e16\u5b50"
        if quote_content:
            base += f"\uff0c\u5e76\u8bc4\u8bba\u9053\uff1a\u300c{quote_content}\u300d"
        return base

    def _describe_follow(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        if target_user_name:
            return f"\u5173\u6ce8\u4e86\u7528\u6237\u300c{target_user_name}\u300d"
        return "\u5173\u6ce8\u4e86\u4e00\u4e2a\u7528\u6237"

    def _describe_create_comment(self) -> str:
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if content:
            if post_content and post_author:
                return f"\u5728{post_author}\u7684\u5e16\u5b50\u300c{post_content}\u300d\u4e0b\u8bc4\u8bba\u9053\uff1a\u300c{content}\u300d"
            elif post_content:
                return f"\u5728\u5e16\u5b50\u300c{post_content}\u300d\u4e0b\u8bc4\u8bba\u9053\uff1a\u300c{content}\u300d"
            elif post_author:
                return f"\u5728{post_author}\u7684\u5e16\u5b50\u4e0b\u8bc4\u8bba\u9053\uff1a\u300c{content}\u300d"
            return f"\u8bc4\u8bba\u9053\uff1a\u300c{content}\u300d"
        return "\u53d1\u8868\u4e86\u8bc4\u8bba"

    def _describe_like_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        if comment_content and comment_author:
            return f"\u70b9\u8d5e\u4e86{comment_author}\u7684\u8bc4\u8bba\uff1a\u300c{comment_content}\u300d"
        elif comment_content:
            return f"\u70b9\u8d5e\u4e86\u4e00\u6761\u8bc4\u8bba\uff1a\u300c{comment_content}\u300d"
        elif comment_author:
            return f"\u70b9\u8d5e\u4e86{comment_author}\u7684\u4e00\u6761\u8bc4\u8bba"
        return "\u70b9\u8d5e\u4e86\u4e00\u6761\u8bc4\u8bba"

    def _describe_dislike_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        if comment_content and comment_author:
            return f"\u8e29\u4e86{comment_author}\u7684\u8bc4\u8bba\uff1a\u300c{comment_content}\u300d"
        elif comment_content:
            return f"\u8e29\u4e86\u4e00\u6761\u8bc4\u8bba\uff1a\u300c{comment_content}\u300d"
        elif comment_author:
            return f"\u8e29\u4e86{comment_author}\u7684\u4e00\u6761\u8bc4\u8bba"
        return "\u8e29\u4e86\u4e00\u6761\u8bc4\u8bba"

    def _describe_search(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"\u641c\u7d22\u4e86\u300c{query}\u300d" if query else "\u8fdb\u884c\u4e86\u641c\u7d22"

    def _describe_search_user(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"\u641c\u7d22\u4e86\u7528\u6237\u300c{query}\u300d" if query else "\u641c\u7d22\u4e86\u7528\u6237"

    def _describe_mute(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        if target_user_name:
            return f"\u5c4f\u853d\u4e86\u7528\u6237\u300c{target_user_name}\u300d"
        return "\u5c4f\u853d\u4e86\u4e00\u4e2a\u7528\u6237"

    def _describe_generic(self) -> str:
        return f"\u6267\u884c\u4e86{self.action_type}\u64cd\u4f5c"


class GraphMemoryUpdater:
    """
    图谱记忆更新器

    监控模拟的actions日志文件，将新的agent活动实时更新到图谱存储后端中。
    按平台分组，每累积BATCH_SIZE条活动后批量发送。
    """

    BATCH_SIZE = 5
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '\u4e16\u754c1',
        'reddit': '\u4e16\u754c2',
    }
    SEND_INTERVAL = 0.5
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self, graph_id: str, storage: Optional[GraphStorage] = None):
        """
        初始化更新器

        Args:
            graph_id: 图谱ID
            storage: 可选的存储后端实例（默认从factory获取）
        """
        self.graph_id = graph_id
        self.storage = storage or get_storage()

        # 活动队列
        self._activity_queue: Queue = Queue()

        # 按平台分组的活动缓冲区
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        # 控制标志
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # 统计
        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0

        logger.info(f"GraphMemoryUpdater 初始化完成: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")

    def _get_platform_display_name(self, platform: str) -> str:
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        """启动后台工作线程"""
        if self._running:
            return

        current_locale = get_locale()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(current_locale,),
            daemon=True,
            name=f"GraphMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"GraphMemoryUpdater 已启动: graph_id={self.graph_id}")

    def stop(self):
        """停止后台工作线程"""
        self._running = False
        self._flush_remaining()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)
        logger.info(f"GraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")

    def add_activity(self, activity: AgentActivity):
        """添加一个agent活动到队列"""
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"添加活动到队列: {activity.agent_name} - {activity.action_type}")

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """从字典数据添加活动"""
        if "event_type" in data:
            return
        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        self.add_activity(activity)

    def _worker_loop(self, locale: str = 'zh'):
        """后台工作循环"""
        set_locale(locale)
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            self._send_batch_activities(batch, platform)
                            time.sleep(self.SEND_INTERVAL)
                except Empty:
                    pass
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """批量发送活动到图谱存储"""
        if not activities:
            return

        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)

        for attempt in range(self.MAX_RETRIES):
            try:
                self.storage.add_text(self.graph_id, combined_text)
                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"成功批量发送 {len(activities)} 条{display_name}活动到图谱 {self.graph_id}")
                logger.debug(f"批量内容预览: {combined_text[:200]}...")
                return
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"批量发送失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量发送失败，已重试{self.MAX_RETRIES}次: {e}")
                    self._failed_count += 1

    def _flush_remaining(self):
        """发送队列和缓冲区中剩余的活动"""
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break

        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"发送{display_name}平台剩余的 {len(buffer)} 条活动")
                    self._send_batch_activities(buffer, platform)
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class GraphMemoryManager:
    """
    管理多个模拟的图谱记忆更新器

    每个模拟可以有自己的更新器实例
    """

    _updaters: Dict[str, GraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> GraphMemoryUpdater:
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            updater = GraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            logger.info(f"创建图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[GraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止图谱记忆更新器: simulation_id={simulation_id}")

    _stop_all_done = False

    @classmethod
    def stop_all(cls):
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"停止更新器失败: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("已停止所有图谱记忆更新器")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }

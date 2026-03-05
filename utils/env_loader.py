import os
from pathlib import Path

from dotenv import load_dotenv


class EnvVars:
    """环境变量集中管理类"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EnvVars, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        load_dotenv()

        # 加载您已有的环境变量
        self.API_KEY = os.getenv("API_KEY", "")
        self.APP_ID = os.getenv("APP_ID", "")
        self.APP_SECRET = os.getenv("APP_SECRET", "")
        self.REDIS_PWD = os.getenv("REDIS_PWD", "")

        # 基本环境配置
        # self.DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')
        # self.SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-key-please-change-in-production')
        # self.ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

        # 验证关键环境变量
        self._validate_env_vars()

        # 标记初始化完成
        self._initialized = True

    def _validate_env_vars(self):
        """验证关键环境变量是否已设置"""

        # 其他关键环境变量验证
        if not self.API_KEY:
            raise ValueError("API_KEY 环境变量未设置！请在 .env 文件中设置 API 密钥。")
        if not self.APP_ID or not self.APP_SECRET:
            raise ValueError(
                "APP_ID 和 APP_SECRET 环境变量未设置！请在 .env 文件中设置应用 ID 和密钥。"
            )

    def get_celery_broker_url(self):
        """获取Celery Broker URL"""
        if self.REDIS_PWD:
            return f"redis://:{self.REDIS_PWD}@redis_docker:6379/0"
        return "redis://1Panel-redis-MpoS:6379/0"

    def get_celery_result_backend(self):
        """获取Celery Result Backend URL"""
        if self.REDIS_PWD:
            return f"redis://:{self.REDIS_PWD}@redis_docker:6379/0"
        return "redis://1Panel-redis-MpoS:6379/0"


# 创建单例实例
env_vars = EnvVars()

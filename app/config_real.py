"""向后兼容入口。真实环境字段现已合并进 :mod:`app.config`."""

from app.config import Settings, config

RealSettings = Settings
config_real = config

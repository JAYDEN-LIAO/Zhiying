"""
core/exceptions.py
═══════════════════════════════════════════════════════════
Zhiying 自定义异常体系 — 所有异常继承自 ZhiyingException。
"""


class ZhiyingException(Exception):
    """顶层基类 — 所有 Zhiying 业务异常的父类。"""
    pass


class ConfigurationError(ZhiyingException):
    """配置加载或校验失败。"""
    pass


class PluginLoadError(ZhiyingException):
    """插件加载失败（模块不存在 / 类缺失 / 实例化异常）。"""
    pass


class PipelineError(ZhiyingException):
    """Pipeline 执行异常。"""
    pass


class VideoNotFoundError(ZhiyingException):
    """视频资源不存在。"""
    pass


class SearchError(ZhiyingException):
    """搜索执行异常。"""
    pass


class ExportError(ZhiyingException):
    """导出操作失败。"""
    pass

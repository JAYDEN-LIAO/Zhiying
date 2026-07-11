"""
core/exceptions.py
═══════════════════════════════════════════════════════════
Cerno 自定义异常体系 — 所有异常继承自 CernoException。
"""


class CernoException(Exception):
    """顶层基类 — 所有 Cerno 业务异常的父类。"""
    pass


class ConfigurationError(CernoException):
    """配置加载或校验失败。"""
    pass


class PluginLoadError(CernoException):
    """插件加载失败（模块不存在 / 类缺失 / 实例化异常）。"""
    pass


class PipelineError(CernoException):
    """Pipeline 执行异常。"""
    pass


class VideoNotFoundError(CernoException):
    """视频资源不存在。"""
    pass


class SearchError(CernoException):
    """搜索执行异常。"""
    pass


class ExportError(CernoException):
    """导出操作失败。"""
    pass

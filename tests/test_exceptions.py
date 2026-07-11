"""
core/exceptions.py 测试
═════════════════════════════════════════════════════════════════
验证：所有异常可实例化、继承关系正确。
"""
import pytest

from core.exceptions import (
    CernoException,
    ConfigurationError,
    PluginLoadError,
    PipelineError,
    VideoNotFoundError,
    SearchError,
    ExportError,
)

ALL_EXCEPTIONS = [
    ConfigurationError,
    PluginLoadError,
    PipelineError,
    VideoNotFoundError,
    SearchError,
    ExportError,
]


class TestExceptionHierarchy:
    """所有异常必须继承自 CernoException。"""

    def test_all_inherit_from_cerno_exception(self):
        for exc_cls in ALL_EXCEPTIONS:
            assert issubclass(exc_cls, CernoException), f"{exc_cls.__name__} 应继承 CernoException"

    def test_cerno_exception_is_base(self):
        assert issubclass(CernoException, Exception)


class TestExceptionInstantiation:
    """所有异常可带 message 字符串正常实例化。"""

    @pytest.mark.parametrize("exc_cls", ALL_EXCEPTIONS)
    def test_instantiate_with_message(self, exc_cls):
        msg = f"Test {exc_cls.__name__} error message"
        exc = exc_cls(msg)
        assert str(exc) == msg
        assert isinstance(exc, CernoException)

    def test_default_message(self):
        exc = ConfigurationError()
        assert str(exc) == ""

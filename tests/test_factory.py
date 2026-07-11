"""
plugins/factory.py 测试
═════════════════════════════════════════════════════════════════
验证：合法 backend 返回插件实例、null 返回 None、不存在模块抛异常、params 传递。
"""
import pytest

from plugins.factory import load_plugin, CATEGORY_MAP, IMPL_CLASS_MAP
from core.exceptions import PluginLoadError


class TestFactoryLoadPlugin:
    """load_plugin 各种路径。"""

    @staticmethod
    def _qc_config(backend: str = "native_qc", **extra) -> dict:
        return {
            "plugins": {
                "qc": {"backend": backend, **extra},
            },
        }

    async def test_load_basic_qc(self):
        """native_qc → BasicQC 实例。"""
        config = self._qc_config()
        instance = await load_plugin(config, "qc")
        assert instance is not None
        from plugins.qc.basic_qc import BasicQC
        assert isinstance(instance, BasicQC)

    async def test_backend_null_returns_none(self):
        config = {"plugins": {"qc": {"backend": None}}}
        instance = await load_plugin(config, "qc")
        assert instance is None

    async def test_backend_empty_string_returns_none(self):
        config = {"plugins": {"qc": {"backend": ""}}}
        instance = await load_plugin(config, "qc")
        assert instance is None

    async def test_nonexistent_module_raises_error(self):
        config = {"plugins": {"qc": {"backend": "__no_such_module__"}}}
        with pytest.raises(PluginLoadError) as exc:
            await load_plugin(config, "qc")
        assert "__no_such_module__" in str(exc.value)

    async def test_unknown_category_raises_error(self):
        config = {"plugins": {"foo": {"backend": "bar"}}}
        with pytest.raises(PluginLoadError, match="Unknown plugin category"):
            await load_plugin(config, "foo")

    async def test_params_passed_to_constructor(self):
        """extra params 应传递给实现类的构造函数。"""
        config = self._qc_config(black_threshold=20, silent_threshold_db=-50)
        instance = await load_plugin(config, "qc")
        assert instance is not None
        assert instance.black_threshold == 20
        assert instance.silent_threshold_db == -50

    async def test_default_params_used(self):
        """不传 extra params 时使用构造函数的默认值。"""
        config = self._qc_config()
        instance = await load_plugin(config, "qc")
        assert instance is not None
        assert instance.black_threshold == 10  # BasicQC 默认值
        assert instance.silent_threshold_db == -40


class TestFactoryConstants:
    """CATEGORY_MAP 和 IMPL_CLASS_MAP 完整性。"""

    def test_all_categories_have_impl(self):
        assert set(CATEGORY_MAP.keys()) == set(IMPL_CLASS_MAP.keys())
        assert len(CATEGORY_MAP) == 9

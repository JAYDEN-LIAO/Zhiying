"""
Cerno 版本号单一事实来源（Single Source of Truth）。

约定（与 git tag 强绑定）：
  1. 发布前：改这里 __version__ → `git tag v<__version__> && git push origin v<__version__>`
  2. 版本号必须与 git tag 完全一致（tag 前带 `v`）。
  3. /health 返回本版本号，服务器拉取后可通过它确认实际运行的版本。

规则（SemVer, pre-1.0 用 0.MINOR.PATCH）：
  - MINOR 递增 = 新功能 / 大重构（发布级）
  - PATCH 递增 = 缺陷修复 / 小改动（热修级）
  升级流程见 docs/ 或 deploy/ 文档。
"""

__version__ = "0.24.0"

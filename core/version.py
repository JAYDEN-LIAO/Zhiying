"""
Zhiying 版本号单一事实来源（Single Source of Truth）。

约定（与 git tag 强绑定）：
  1. 发布前：改这里 __version__ → `git tag v<__version__> && git push origin v<__version__>`
  2. 版本号必须与 git tag 完全一致（tag 前带 `v`）。
  3. /health 返回本版本号，服务器拉取后可通过它确认实际运行的版本。

规则（两段式，与软件管家平台版本格式一致，如 0.90 / 0.91 / 1.00）：
  - 发版是手动动作：日常多次 commit 不发版，认为可以更新时才 ./bump（minor +0.01）
  - 也可 `./bump X.Y` 直接指定完整版本号
  升级流程见 docs/ 或 deploy/ 文档。
"""

__version__ = "0.90"

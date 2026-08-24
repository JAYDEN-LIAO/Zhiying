#!/usr/bin/env python3
"""
scripts/plot_training_curves.py
═══════════════════════════════════════════════════════════
训练 loss 曲线可视化（matplotlib）。

输入: models/Qwen2.5-3B-Instruct-zhiying-lora/checkpoint-270/trainer_state.json
输出: docs/assets/llm_loss_curves.png

用法:
    pip install matplotlib  # 一次性
    python scripts/plot_training_curves.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    import matplotlib
    matplotlib.use("Agg")  # 无 GUI 后端
    import matplotlib.pyplot as plt

    # 读训练日志
    state_path = PROJECT_ROOT / "models" / "Qwen2.5-3B-Instruct-zhiying-lora" / "checkpoint-270" / "trainer_state.json"
    state = json.load(open(state_path))
    log_history = state.get("log_history", [])

    train_loss = [(h["step"], h["loss"]) for h in log_history if "loss" in h and "eval_loss" not in h]
    eval_loss = [(h["step"], h["eval_loss"]) for h in log_history if "eval_loss" in h]

    # 画图
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # 左图：完整 loss 曲线
    train_steps, train_vals = zip(*train_loss)
    ax1.plot(train_steps, train_vals, "o-", color="#2E86AB", label="Train Loss", linewidth=2, markersize=6)
    eval_steps, eval_vals = zip(*eval_loss)
    ax1.plot(eval_steps, eval_vals, "s-", color="#E63946", label="Eval Loss", linewidth=2, markersize=10)
    ax1.set_xlabel("Step", fontsize=12)
    ax1.set_ylabel("Loss", fontsize=12)
    ax1.set_title("QLoRA Training: Qwen2.5-3B on Query Rewrite\n(1500 samples, 3 epochs, lr=1.5e-4)", fontsize=13)
    ax1.legend(fontsize=11, loc="upper right")
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 3.0)

    # 在最终点标注数字
    ax1.annotate(f"final = {train_vals[-1]:.2f}",
                 xy=(train_steps[-1], train_vals[-1]),
                 xytext=(train_steps[-1] - 80, train_vals[-1] + 0.3),
                 fontsize=10, color="#2E86AB",
                 arrowprops=dict(arrowstyle="->", color="#2E86AB", alpha=0.5))
    ax1.annotate(f"final = {eval_vals[-1]:.2f}",
                 xy=(eval_steps[-1], eval_vals[-1]),
                 xytext=(eval_steps[-1] - 80, eval_vals[-1] - 0.4),
                 fontsize=10, color="#E63946",
                 arrowprops=dict(arrowstyle="->", color="#E63946", alpha=0.5))

    # 右图：eval loss 单独 + 总览
    ax2.bar(["Epoch 1", "Epoch 2", "Epoch 3"], eval_vals, color=["#A8DADC", "#457B9D", "#1D3557"], alpha=0.85)
    for i, v in enumerate(eval_vals):
        ax2.text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Eval Loss", fontsize=12)
    ax2.set_title("Per-Epoch Evaluation Loss", fontsize=13)
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.set_ylim(0.4, 0.8)

    plt.tight_layout()

    # 保存
    output_dir = PROJECT_ROOT / "docs" / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "llm_loss_curves.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"✓ 图表已保存：{output_path}")

    # 也保存 markdown 引用片段
    print()
    print("Markdown 引用：")
    print(f"  ![loss_curves](../assets/llm_loss_curves.png)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
scripts/train_query_rewriter_lora.py
═══════════════════════════════════════════════════════════
Query 改写 LoRA 训练 CLI 封装。

基于 LLaMA-Factory 的 llamafactory-cli train 命令，封装常用选项：
  - 冒烟测试：1 epoch + max_samples=100
  - 完整训练：3 epochs
  - Dry-run：只打印命令不执行
  - JSON 输出：机器可读摘要

用法:
    # 冒烟测试（先跑通链路）
    python scripts/train_query_rewriter_lora.py --smoke

    # 完整训练
    python scripts/train_query_rewriter_lora.py

    # Dry-run 打印命令
    python scripts/train_query_rewriter_lora.py --dry-run

    # 自定义参数
    python scripts/train_query_rewriter_lora.py --epochs 5 --lr 1e-4

环境要求:
    - pip install llamafactory
    - models/Qwen/Qwen2.5-3B-Instruct 已下载
    - data/query_rewrite_dataset/train.jsonl 已生成
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_prerequisites(base_model: Path, data_file: Path) -> list[str]:
    """检查前置条件，返回缺失项列表"""
    missing = []
    if not base_model.exists():
        missing.append(f"底座模型未找到：{base_model}")
    elif not (base_model / "config.json").exists():
        missing.append(f"底座模型目录不完整：{base_model}/config.json 缺失")
    if not data_file.exists():
        missing.append(f"训练数据未找到：{data_file}")
    # 检查 llamafactory-cli
    if shutil.which("llamafactory-cli") is None:
        missing.append("llamafactory-cli 未安装（pip install llamafactory）")
    return missing


def build_lf_command(
    config_file: Path,
    output_dir: Path,
) -> list[str]:
    """构造 llamafactory-cli train 命令

    LLaMA-Factory 0.9.x 行为变更：只接受 --output_dir 一个 CLI 参数，
    其他超参（lr/epochs/max_samples）必须从 YAML 配置读取。
    """
    cmd = [
        "llamafactory-cli", "train", str(config_file),
        "--output_dir", str(output_dir),
    ]
    return cmd


def run_training(cmd: list[str], dry_run: bool) -> int:
    """执行训练命令"""
    print("\n执行命令：")
    print("  " + " ".join(cmd))
    if dry_run:
        print("\n[DRY-RUN] 不实际执行")
        return 0
    print()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Query 改写 LoRA 训练 CLI 封装",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "qwen25_3b_lora_zhiying.yaml",
        help="LLaMA-Factory 训练配置",
    )
    parser.add_argument(
        "--base-model",
        type=Path,
        default=PROJECT_ROOT / "models" / "Qwen" / "Qwen2.5-3B-Instruct",
        help="底座模型路径",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "query_rewrite_dataset" / "train.jsonl",
        help="训练数据 JSONL",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "models" / "Qwen2.5-3B-Instruct-zhiying-lora",
        help="adapter 输出目录",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="冒烟测试：max_samples=100 + 1 epoch",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="训练 epoch 数（覆盖配置）",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=None,
        help="学习率（覆盖配置）",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="最大样本数（用于小批量测试）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印命令不执行",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 摘要",
    )
    args = parser.parse_args()

    # ── 1. 前置检查 ──
    print("[1/3] 前置检查...")
    missing = check_prerequisites(args.base_model, args.data_file)
    if missing:
        print("\n[ERROR] 前置条件不满足：", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ 底座模型：{args.base_model}")
    print(f"  ✓ 训练数据：{args.data_file}")

    # ── 2. 解析参数 ──
    print("\n[2/3] 解析训练参数...")
    if args.smoke:
        epochs = 1
        max_samples = 100
        print("  模式：冒烟测试（1 epoch, 100 samples）")
    else:
        epochs = args.epochs if args.epochs else 3
        max_samples = args.max_samples
        print(f"  模式：完整训练（{epochs} epochs）")

    lr = args.lr if args.lr else 1.5e-4
    print(f"  学习率：{lr}")
    print(f"  输出目录：{args.output_dir}")

    # ── 3. 构造并执行命令 ──
    print("\n[3/3] 启动训练...")
    # 注：LLaMA-Factory 0.9.x 只接受 --output_dir 一个 CLI 参数
    # lr/epochs/max_samples 必须从 YAML 读取
    # 冒烟测试通过"覆盖配置文件"实现（生成临时 YAML）
    if args.smoke or max_samples:
        # 生成临时配置覆盖
        import yaml as _yaml
        with open(args.config) as f:
            cfg = _yaml.safe_load(f)
        if args.smoke:
            cfg["num_train_epochs"] = 1
            cfg["max_samples"] = 100
            cfg["output_dir"] = str(args.output_dir) + "-smoke"
        elif max_samples:
            cfg["max_samples"] = max_samples
        import tempfile
        tmp_config = Path(tempfile.mkstemp(suffix=".yaml", prefix="lf_smoke_")[1])
        with open(tmp_config, "w") as f:
            _yaml.dump(cfg, f)
        config_to_use = tmp_config
        print(f"  使用临时配置：{tmp_config}")
    else:
        config_to_use = args.config

    cmd = build_lf_command(config_to_use, args.output_dir)
    rc = run_training(cmd, args.dry_run)

    if args.json:
        summary = {
            "command": " ".join(cmd),
            "epochs": epochs,
            "lr": lr,
            "max_samples": max_samples,
            "output_dir": str(args.output_dir),
            "return_code": rc,
            "mode": "smoke" if args.smoke else "full",
        }
        print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))

    if rc != 0:
        print(f"\n[ERROR] 训练失败，退出码 {rc}", file=sys.stderr)
        sys.exit(rc)
    print(f"\n✓ 训练完成，adapter 位于：{args.output_dir}")


if __name__ == "__main__":
    main()

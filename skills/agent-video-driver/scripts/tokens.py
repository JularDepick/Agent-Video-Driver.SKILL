# -*- coding: utf-8 -*-
"""
统计 DSH 会话的 token 用量

用途: 扫描本次 DSH 会话的记录文件, 汇总 token 消耗, 供交付时汇报成本
口径: usage_blocks 与 inputTokens / outputTokens / totalTokens / cacheReadTokens / models
依赖: zstandard (会话记录是 zstd 压缩的 JSONL). 缺它就读不了记录, 脚本会提示后退出
限制: 只能在 DSH 会话内运行, 需要 DSH_SESSION_ID, 以及 DSH_HOME 或 ~/.dsh 下的会话目录

  python scripts/tokens.py
  python scripts/tokens.py --out temp/usage.json
"""
import argparse
import glob
import json
import os
import sys

# 会话记录的默认根目录, 环境变量 DSH_HOME 优先
DEFAULT_HOME = "~/.dsh"
# 默认输出路径, 相对当前工作目录, 与技能里其它中间产物一样落在 temp 下
DEFAULT_OUT = os.path.join("temp", "token_usage.json")
# 退出码: 2 表示环境或依赖不满足, 不是统计失败
EXIT_ENV = 2


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="统计当前 DSH 会话的 token 用量, 结果写 JSON 并打印")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help="结果 JSON 的输出路径, 缺省 %s (相对当前工作目录)" % DEFAULT_OUT)
    return p.parse_args(argv)


def import_zstandard():
    """延迟导入 zstandard, 缺包时返回 None 交给调用方提示"""
    try:
        import zstandard
    except ImportError:
        return None
    return zstandard


def session_dir():
    """定位本次 DSH 会话的记录目录, 环境不满足时返回 (None, 原因)"""
    sid = os.environ.get("DSH_SESSION_ID", "")
    if not sid:
        return None, "环境变量 DSH_SESSION_ID 为空"
    home = os.environ.get("DSH_HOME") or os.path.expanduser(DEFAULT_HOME)
    hits = glob.glob(os.path.join(home, "sessions", "*", sid))
    if not hits:
        return None, "在 %s 下找不到会话目录 %s" % (os.path.join(home, "sessions"), sid)
    return hits[0], ""


def read_records(d, zstandard):
    """逐行解析会话记录, 解析口径与改造前一致"""
    recs = []
    for name in os.listdir(d):
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = zstandard.ZstdDecompressor().stream_reader(fh).read()
        for ln in data.decode("utf-8", "replace").splitlines():
            if ln.strip():
                recs.append(json.loads(ln))
    return recs


def tally(recs):
    """汇总 usage 字段, 返回 (usage 段数, 各 token 合计, 模型集合)"""
    tot = dict(inputTokens=0, outputTokens=0, totalTokens=0, cacheReadTokens=0)
    n = 0
    models = set()
    for r in recs:
        if not isinstance(r, dict):
            continue
        d_ = r.get("data") or {}
        u = d_.get("usage")
        if isinstance(u, dict):
            n += 1
            for k in tot:
                v = u.get(k)
                if isinstance(v, (int, float)):
                    tot[k] += v
            m = d_.get("responseModel") or d_.get("model")
            if m:
                models.add(str(m))
    return n, tot, models


def main(argv=None):
    args = parse_args(argv)

    zstandard = import_zstandard()
    if zstandard is None:
        print("[缺失] 未安装 zstandard, 无法解压会话记录", file=sys.stderr)
        print("  它的用处: DSH 的会话记录是 zstd 压缩的 JSONL, 只有它能解压", file=sys.stderr)
        print("  失去的能力: 本脚本读不到任何记录, 拿不到 token 用量统计", file=sys.stderr)
        print("  可用 pip install zstandard 安装, 或改用 DSH 自带的用量面板查看", file=sys.stderr)
        return EXIT_ENV

    d, why = session_dir()
    if d is None:
        print("[跳过] 当前不在可识别的 DSH 会话环境中: %s" % why, file=sys.stderr)
        print("  本脚本只在 DSH 会话里可用, 它要读 %s 下的会话记录" % os.path.join("~/.dsh", "sessions"),
              file=sys.stderr)
        print("  若在普通终端里跑, 先确认 DSH_SESSION_ID 与 DSH_HOME 已由 DSH 注入", file=sys.stderr)
        return EXIT_ENV

    recs = read_records(d, zstandard)
    n, tot, models = tally(recs)

    print("usage blocks:", n)
    for k, v in tot.items():
        print("%s: %s" % (k, v))
    print("models:", models)
    # 顺带打印最后一条原始 usage, 便于核对字段有没有变
    for r in reversed(recs):
        u = ((r.get("data") or {}).get("usage"))
        if u:
            print("sample:", json.dumps(u, ensure_ascii=False))
            break

    out = {"usage_blocks": n, **tot, "models": sorted(models)}
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=2))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

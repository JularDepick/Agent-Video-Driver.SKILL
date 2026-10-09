# -*- coding: utf-8 -*-
"""
风格牌堆工具: 取候选, 指定牌面, 校验牌堆

  python scripts/style_lottery.py                     抽一张 (兜底路径)
  python scripts/style_lottery.py --pick 3            取三张差别大的候选, 交给用户挑
  python scripts/style_lottery.py --pick 3 --seed 7   可复现
  python scripts/style_lottery.py --list              看整副牌
  python scripts/style_lottery.py --tone light        只在轻的那一档里取
  python scripts/style_lottery.py --avoid riso-press,deep-space-neon
  python scripts/style_lottery.py --style swiss-editorial
  python scripts/style_lottery.py --pick 3 --write ..\\my-video   候选落成 STYLE_candidates.md
  python scripts/style_lottery.py --style swiss-editorial --write ..\\my-video
                                                      选定的牌落成项目里的 STYLE.md
  python scripts/style_lottery.py --check             校验牌堆两个来源是否一致

抽签的用途是取候选, 不是替用户定风格: 用户没有点名风格时先取三张候选(--pick 3), 各出一张样图,
附一句与题材绑定的推荐, 由用户挑定; 用户不想挑时才用单张抽签兜底. 抽签的目的是防单调
(放任自流时总是做最响的那一支), 不是收走用户的选型权.

只有两种情况跳过取候选: 用户点名了风格或参考片, 或者是在改一条已有的片.
"""
import argparse
import json
import os
import sys

import styles

STYLE_MD = "STYLE.md"
CANDIDATES_MD = "STYLE_candidates.md"
TONE_CN = {"loud": "响的", "steady": "稳的", "light": "轻的"}


def show(card, prefix=""):
    print("%s%s (%s)  [%s]" % (prefix, card["name"], card["id"], card["tone"]))
    print("%s  %s" % (prefix, card["idiom"]))
    print("%s  底板: %s" % (prefix, card["plate"]))
    print("%s  字体: %s" % (prefix, card["type"]))
    print("%s  配乐: %s" % (prefix, card["sound"]))
    print("%s  引擎: %s" % (prefix, card["engine"]))
    if card.get("delivery"):
        print("%s  注意: 这张牌靠细纹理吃饭, 要按交付尺寸排版" % prefix)
    print("%s  注意: %s" % (prefix, card["note"]))


def cmd_list(a):
    counts = styles.tone_counts()
    print("整副牌 %d 张   响 %d / 稳 %d / 轻 %d"
          % (len(styles.DECK), counts.get("loud", 0), counts.get("steady", 0),
             counts.get("light", 0)))
    print("-" * 66)
    for c in styles.all_cards():
        flag = "交付尺寸" if c.get("delivery") else "        "
        print("%-22s %-6s %s  %s" % (c["id"], c["tone"], flag, c["name"]))
        print("    %s" % c["idiom"])
    print("-" * 66)
    print("详细配色与参数见 references/styles.md; 取候选与换牌的纪律见该文档的选风格的方法一节")


def cmd_check(a):
    problems = styles.check_deck(a.md)
    if not problems:
        counts = styles.tone_counts()
        print("牌堆一致: %d 张, 响 %d / 稳 %d / 轻 %d, 与 %s 的 id, 名称与档位逐一对上"
              % (len(styles.DECK), counts.get("loud", 0), counts.get("steady", 0),
                 counts.get("light", 0), a.md))
        return 0
    print("牌堆不一致, 共 %d 处:" % len(problems))
    for p in problems:
        print("  - %s" % p)
    print("修法: 让 scripts/styles.py 与 references/styles.md 的牌堆总览表对齐, 再重跑 --check")
    return 1


def parse_avoid(a):
    avoid = [x.strip() for x in (a.avoid or "").split(",") if x.strip()]
    unknown = [x for x in avoid if styles.get(x) is None]
    if unknown:
        print("--avoid 里有不认识的牌 id: %s" % ", ".join(unknown))
        print("可用 id: %s" % ", ".join(styles.card_ids()))
        return None
    return avoid


def write_candidates(project, cards, seed, avoid):
    path = os.path.join(project, CANDIDATES_MD)
    lines = [
        "# 风格候选",
        "",
        "本文件是候选清单, 不是最终牌面. 用户挑定之后, 用 `--style <id> --write <项目目录>`",
        "把那一张落成 `%s` 再开工." % STYLE_MD,
        "",
    ]
    if seed is not None:
        lines += ["- 取候选种子: %s (用同一个种子可以复现这三张)" % seed, ""]
    if avoid:
        lines += ["- 本次排除: %s" % ", ".join(sorted(avoid)), ""]
    for i, c in enumerate(cards, 1):
        lines += [
            "## 候选 %d, %s (%s)  [%s]" % (i, c["name"], c["id"], c["tone"]),
            "",
            "- 一句话: %s" % c["idiom"],
            "- 底板: %s" % c["plate"],
            "- 字体: %s" % c["type"],
            "- 配乐: %s" % c["sound"],
            "- 引擎: %s" % c["engine"],
            "- 注意: %s" % c["note"],
            "",
            "样图: <这一张候选在阶段 3 出的样图路径, 两张起: 标题卡与典型演示屏>",
            "推荐与否: <填一句与题材绑定的推荐理由, 不评价风格高下>",
            "",
        ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return path


def cmd_pick(a):
    avoid = parse_avoid(a)
    if avoid is None:
        return 2
    cards = styles.draw_many(a.pick, seed=a.seed, avoid=avoid, tone=a.tone)
    if len(cards) < a.pick:
        print("取不满 %d 张候选: --tone %s 与 --avoid 把可选范围缩小到 %d 张"
              % (a.pick, a.tone, len(cards)))
        return 2
    print("=" * 66)
    print("取到 %d 张候选 (差别要看得出来, 各出一张样图交给用户挑)" % len(cards))
    print("=" * 66)
    for i, c in enumerate(cards, 1):
        print()
        print("--- 候选 %d, %s ---" % (i, TONE_CN.get(c["tone"], c["tone"])))
        show(c)
    if a.seed is not None:
        print()
        print("复现: python scripts/style_lottery.py --pick %d --seed %s" % (a.pick, a.seed))
    if a.write:
        project = os.path.abspath(a.write)
        if not os.path.isdir(project):
            print("目标目录不存在: %s, 先跑 scripts/new_project.py 起工程" % project)
            return 2
        print("wrote %s" % write_candidates(project, cards, a.seed, avoid))
    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as f:
            json.dump({"cards": cards, "seed": a.seed, "avoid": avoid}, f,
                      ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


def cmd_draw(a):
    avoid = parse_avoid(a)
    if avoid is None:
        return 2
    if a.style:
        card = styles.get(a.style)
        if card is None:
            print("不认识的牌 id: %s" % a.style)
            print("可用 id: %s" % ", ".join(styles.card_ids()))
            return 2
        if card["id"] in avoid:
            print("--style 指定的牌同时在 --avoid 里: %s" % card["id"])
            return 2
    else:
        card = styles.draw(seed=a.seed, avoid=avoid, tone=a.tone)
        if card is None:
            print("抽不到牌: --tone %s 与 --avoid 把可选范围清空了" % a.tone)
            return 2

    print("=" * 66)
    if a.style:
        print("指定牌面")
    else:
        print("抽到一张%s" % TONE_CN.get(card["tone"], ""))
    print("=" * 66)
    show(card)
    if a.seed is not None and not a.style:
        print()
        print("复现: python scripts/style_lottery.py --seed %s" % a.seed)

    if a.write:
        project = os.path.abspath(a.write)
        if not os.path.isdir(project):
            print("目标目录不存在: %s, 先跑 scripts/new_project.py 起工程" % project)
            return 2
        path = os.path.join(project, STYLE_MD)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(styles.style_md(card, seed=a.seed, avoided=avoid))
        print("wrote %s" % path)
    if a.json_path:
        parent = os.path.dirname(os.path.abspath(a.json_path))
        os.makedirs(parent, exist_ok=True)
        with open(a.json_path, "w", encoding="utf-8") as f:
            json.dump({"card": card, "seed": a.seed, "avoid": avoid}, f,
                      ensure_ascii=False, indent=2)
        print("wrote %s" % a.json_path)
    return 0


def main():
    ap = argparse.ArgumentParser(description="风格牌堆工具: 取候选, 指定牌面, 看整副牌, 校验牌堆")
    ap.add_argument("--list", action="store_true", help="打印整副牌")
    ap.add_argument("--pick", type=int, default=None, metavar="N",
                    help="取 N 张差别大的候选(尽量覆盖响稳轻三档), 交给用户挑")
    ap.add_argument("--check", action="store_true",
                    help="校验 scripts/styles.py 与 references/styles.md 的牌堆是否一致")
    ap.add_argument("--md", default=os.path.join("references", "styles.md"),
                    help="--check 要校验的人读牌堆路径, 缺省 references/styles.md")
    ap.add_argument("--seed", type=int, default=None, help="随机种子, 便于复现")
    ap.add_argument("--tone", choices=styles.TONE_ORDER, default=None,
                    help="只在某一档里取: loud 响 / steady 稳 / light 轻")
    ap.add_argument("--avoid", default=None, help="要排除的牌 id, 逗号分隔, 例如上一条用过的")
    ap.add_argument("--style", default=None, help="直接指定牌 id, 跳过取候选")
    ap.add_argument("--write", default=None, help="把候选或牌面写成该目录下的 md 文件")
    ap.add_argument("--json", dest="json_path", default=None, help="把结果写成 JSON 的路径")
    a = ap.parse_args()
    if a.check:
        return cmd_check(a)
    if a.list:
        cmd_list(a)
        return 0
    if a.pick:
        return cmd_pick(a)
    return cmd_draw(a)


if __name__ == "__main__":
    sys.exit(main())

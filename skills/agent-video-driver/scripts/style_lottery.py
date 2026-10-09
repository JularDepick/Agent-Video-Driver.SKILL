# -*- coding: utf-8 -*-
"""
抽一张风格牌

  python scripts/style_lottery.py                     抽一张
  python scripts/style_lottery.py --seed 7            可复现
  python scripts/style_lottery.py --list              看整副牌
  python scripts/style_lottery.py --tone light        只在轻的那一档里抽
  python scripts/style_lottery.py --avoid riso-press,deep-space-neon
  python scripts/style_lottery.py --style swiss-editorial
  python scripts/style_lottery.py --write ..\\my-video  把牌面落成项目里的 STYLE.md

为什么要抽签: 引擎能做的风格差别很大, 而放任自流时它总是做最响的那一支. 抽到哪张做哪张,
不要因为这张不够炫就换牌; 牌里一半是轻的, 轻的做干净了一样好看.

只有两种情况跳过抽签: 用户点名了风格或参考片, 或者是在改一条已有的片.
"""
import argparse
import json
import os
import sys

import styles

STYLE_MD = "STYLE.md"


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
    print("详细配色与参数见 references/styles.md; 抽签纪律见该文档的牌堆一节")


def cmd_draw(a):
    avoid = [x.strip() for x in (a.avoid or "").split(",") if x.strip()]
    unknown = [x for x in avoid if styles.get(x) is None]
    if unknown:
        print("--avoid 里有不认识的牌 id: %s" % ", ".join(unknown))
        print("可用 id: %s" % ", ".join(styles.card_ids()))
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
        print("抽到一张%s" % {"loud": "响的", "steady": "稳的", "light": "轻的"}.get(card["tone"], ""))
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
    ap = argparse.ArgumentParser(description="抽一张风格牌, 或看整副牌")
    ap.add_argument("--list", action="store_true", help="打印整副牌")
    ap.add_argument("--seed", type=int, default=None, help="随机种子, 便于复现")
    ap.add_argument("--tone", choices=styles.TONE_ORDER, default=None,
                    help="只在某一档里抽: loud 响 / steady 稳 / light 轻")
    ap.add_argument("--avoid", default=None, help="要排除的牌 id, 逗号分隔, 例如上一条抽过的")
    ap.add_argument("--style", default=None, help="直接指定牌 id, 跳过抽签")
    ap.add_argument("--write", default=None, help="把牌面写成该目录下的 STYLE.md")
    ap.add_argument("--json", dest="json_path", default=None, help="把抽签结果写成 JSON 的路径")
    a = ap.parse_args()
    if a.list:
        cmd_list(a)
        return 0
    return cmd_draw(a)


if __name__ == "__main__":
    sys.exit(main())

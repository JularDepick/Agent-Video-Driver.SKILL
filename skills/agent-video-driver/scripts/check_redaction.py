# -*- coding: utf-8 -*-
"""
交付反查: 从原始产物的元数据自动推导禁用词, 对目标目录做全文反查

  python scripts/check_redaction.py --meta 原始文档.docx --scan 交付目录
  python scripts/check_redaction.py --meta 原始文档.pptx --scan 交付目录 --report temp/redaction.md
  python scripts/check_redaction.py --words temp/words.json --scan out

职责边界: 它只做"交付物里是否残留敏感词"的反查, 不做去敏改写; 词表自动推导,
存在交付目录之外, 本脚本与其报告里都不回显任何命中原文, 只写形态, 长度与位置.

词表推导来源 (--meta 给定文件时):
  zip 类 (docx, pptx, xlsx, odt): docProps/core.xml 与 app.xml 的创建者, 修改者, 公司字段
  纯文本类: 全文按行扫描, 提取邮箱与拉丁姓名样式的字符串
词表也可以手工给: --words 指向一个 JSON 数组文件, 跳过推导.

退出码: 0 无命中; 1 用法错误; 2 有命中 (CI 与门禁用).
多编码探测: 文本文件按 utf-8, utf-16, gbk 依次尝试, 谁先成功用谁.
"""
import argparse
import json
import os
import re
import sys
import zipfile

TEXT_ENCODINGS = ("utf-8", "utf-16", "gbk")
TEXT_EXTS = (".md", ".txt", ".html", ".htm", ".xml", ".json", ".py", ".csv",
             ".srt", ".vtt", ".ass", ".mmd", ".yaml", ".yml")
SKIP_DIRS = ("__pycache__", ".git")
MAX_HINT = 64


def is_text_path(path):
    return os.path.splitext(path)[1].lower() in TEXT_EXTS


def read_text_guess(path):
    """按多编码依次尝试读文本, 全失败返回 None"""
    raw = open(path, "rb").read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        enc = "utf-16"
        return raw.decode(enc, errors="replace")
    for enc in TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


# ----------------------------------------------------------------- 词表推导
def words_from_zip_meta(path):
    """zip 容器里的元数据字段: 创建者, 修改者, 公司, 最后修改者"""
    words = set()
    try:
        with zipfile.ZipFile(path) as z:
            for name in ("docProps/core.xml", "docProps/app.xml"):
                if name not in z.namelist():
                    continue
                xml = z.read(name).decode("utf-8", errors="replace")
                for tag in ("creator", "lastModifiedBy", "Company", "Manager"):
                    for v in re.findall(r"<[^>]*%s[^>]*>([^<]+)</" % tag, xml):
                        v = v.strip()
                        if v:
                            words.add(v)
    except (zipfile.BadZipFile, OSError):
        pass
    return words


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 拉丁姓名样式: 两到三个首字母大写的词 (避免把普通英文单词整段收进来)
LATIN_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})(?:\s+([A-Z][a-z]{2,}))?\b")
META_KEYS = ("author", "creator", "by", "copyright", "contact")


def words_from_text(path):
    """纯文本素材: 邮箱, 拉丁姓名, 以及显式 meta 行的值"""
    words = set()
    text = read_text_guess(path)
    if text is None:
        return words
    for m in EMAIL_RE.finditer(text):
        words.add(m.group(0))
    for m in LATIN_NAME_RE.finditer(text):
        words.add(m.group(0))
    for line in text.splitlines():
        low = line.lower()
        for k in META_KEYS:
            idx = low.find(k + ":")
            if idx >= 0:
                v = line[idx + len(k) + 1:].strip()
                if v:
                    words.add(v)
    return words


def derive_words(meta):
    """从原始产物推导词表; 返回 (词表, 推导来源说明)"""
    words = set()
    srcs = []
    if os.path.splitext(meta)[1].lower() in (".docx", ".pptx", ".xlsx", ".odt", ".epub"):
        words |= words_from_zip_meta(meta)
        srcs.append("zip 元数据")
    if is_text_path(meta):
        words |= words_from_text(meta)
        srcs.append("文本扫描")
    words = {w.strip() for w in words if len(w.strip()) >= 2}
    return sorted(words, key=lambda s: (-len(s), s)), " + ".join(srcs) or "无"


def save_words(words, path):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)


def load_words(path):
    with open(path, "r", encoding="utf-8") as f:
        ws = json.load(f)
    if not isinstance(ws, list):
        raise ValueError("词表文件应是 JSON 数组")
    return [str(w) for w in ws if str(w).strip()]


# ----------------------------------------------------------------- 反查
def shape_hint(word):
    """命中词的形态描述, 不回显原文"""
    kinds = []
    if EMAIL_RE.fullmatch(word):
        kinds.append("邮箱")
    if re.fullmatch(r"[A-Za-z][A-Za-z@.\-_ ]*", word):
        kinds.append("拉丁字符串")
    if re.search(r"\d", word):
        kinds.append("含数字")
    if re.search(r"[\u4e00-\u9fff]", word):
        kinds.append("含中文")
    if not kinds:
        kinds.append("字符串")
    return "+".join(kinds)


def scan_file(path, words):
    """返回 [(词序号, 行号, 列), ...]; 词表条目按长度降序, 先长后短避免遮蔽"""
    text = read_text_guess(path) if is_text_path(path) else None
    if text is None:
        return []
    hits = []
    low = text.lower()
    for wi, w in enumerate(words):
        needle = w.lower()
        start = 0
        while True:
            idx = low.find(needle, start)
            if idx < 0:
                break
            line_no = text.count("\n", 0, idx) + 1
            col = idx - (text.rfind("\n", 0, idx) + 1) + 1
            hits.append((wi, line_no, col))
            start = idx + len(needle)
    return hits


def scan_dir(root, words):
    """反查目录下全部文本文件; 返回 {文件: hits}, 忽略二进制与跳过目录"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            if not is_text_path(p):
                continue
            hits = scan_file(p, words)
            if hits:
                out[p] = hits
    return out


def report(path, words, found):
    lines = ["# 去敏反查报告", "",
             "词表条目数: %d" % len(words),
             "命中文件数: %d" % len(found), ""]
    for p, hits in sorted(found.items()):
        lines.append("## %s" % p)
        lines.append("| 词表条目 | 形态 | 长度 | 行 | 列 |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|")
        for wi, ln, col in hits:
            lines.append("| #%d | %s | %d | %d | %d |"
                         % (wi, shape_hint(words[wi]), len(words[wi]), ln, col))
        lines.append("")
    lines.append("命中以形态与位置记录, 不回显原文; 处置流程见 references/desensitization.md")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="禁用词推导加交付目录反查")
    ap.add_argument("--meta", default=None, help="原始产物路径 (推导词表的来源)")
    ap.add_argument("--words", default=None, help="手工词表 (JSON 数组), 给了就跳过推导")
    ap.add_argument("--save-words", dest="save_words", default=None,
                    help="把推导出的词表存到该路径 (存交付目录之外)")
    ap.add_argument("--scan", required=True, help="要反查的目录或文件")
    ap.add_argument("--report", default=None, help="把命中清单写成 markdown 的路径")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if a.words:
        words = load_words(a.words)
        src = "手工词表 %s" % a.words
    elif a.meta:
        if not os.path.exists(a.meta):
            print("找不到原始产物: %s" % a.meta)
            return 1
        words, src = derive_words(a.meta)
    else:
        print("--meta 与 --words 至少给一个")
        return 1
    if not words:
        print("词表为空: 从 %s 推导不出禁用词 (%s), 检查素材是否真的带归属信息" % (a.meta, src))
        return 1
    if not os.path.exists(a.scan):
        print("找不到反查目标: %s" % a.scan)
        return 1

    if a.save_words:
        save_words(words, a.save_words)
        print("词表已存: %s (%d 条, 来源 %s)" % (a.save_words, len(words), src))
    else:
        print("词表: %d 条 (来源 %s)" % (len(words), src))

    targets = ([a.scan] if os.path.isfile(a.scan)
               else [os.path.join(dp, n) for dp, _, ns in os.walk(a.scan)
                     for n in sorted(ns)
                     if is_text_path(os.path.join(dp, n))
                     and not (set(os.path.relpath(os.path.join(dp, n), a.scan).split(os.sep))
                              & set(SKIP_DIRS))])
    found = {}
    n_files = 0
    for p in targets:
        n_files += 1
        hits = scan_file(p, words)
        if hits:
            found[p] = hits

    print("反查完成: %d 个文本文件, 命中 %d 个文件, 共 %d 处"
          % (n_files, len(found), sum(len(h) for h in found.values())))
    if a.report:
        report(a.report, words, found)
        print("wrote %s" % a.report)
    if found:
        for p, hits in sorted(found.items()):
            for wi, ln, col in hits[:MAX_HINT]:
                print("  命中: %s:%d:%d  词表#%d  形态=%s  长度=%d"
                      % (p, ln, col, wi, shape_hint(words[wi]), len(words[wi])))
        print("处置流程见 references/desensitization.md: 改掉后重跑, 连续两遍零命中才算通过")
        return 2
    print("反查通过: 无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())

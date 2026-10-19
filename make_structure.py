#!/usr/bin/env python3
"""
SH Test - structure builder (Python 3, no extra libraries needed)

Run it INSIDE your repo folder (the folder that has index.json and the book folders):
    python make_structure.py
or give the folder path:
    python make_structure.py /path/to/studyhelperbook
Skip question counting (faster):
    python make_structure.py --no-counts

What it does:
  1. Adds "categories" to every book in index.json (Class 10 / 11 / 12 / NEET / JEE / Other)
  2. Creates structure/<book_id>.json for every book (chapters + exercise files)
  3. Warns about any file bigger than GitHub's limit (100 MB)

Optional: create category_overrides.json to force categories for a book, e.g.
    { "Neev Biology Digital Module": ["NEET", "Class 11"] }
(the key is the book's folder_name or title)
"""
import json
import os
import re
import sys

CATEGORY_ORDER = ["Class 10", "Class 11", "Class 12", "NEET", "JEE", "Other"]
ROMAN = {"x": "Class 10", "xi": "Class 11", "xii": "Class 12",
         "10": "Class 10", "11": "Class 11", "12": "Class 12"}

CLASS_RE = re.compile(
    r"\bclass\s*[-:]?\s*((?:10|11|12|xii|xi|x)(?:th)?"
    r"(?:\s*(?:&|and|-|/|,|to)\s*(?:10|11|12|xii|xi|x)(?:th)?)*)\b", re.I)
TOKEN_RE = re.compile(r"xii|xi|x|10|11|12", re.I)
ORDINAL_RE = re.compile(r"\b(10|11|12)th\b", re.I)
NEET_RE = re.compile(r"\bneet\b", re.I)
JEE_RE = re.compile(r"\b(jee|iit)\b", re.I)

WARN_MB = 50
MAX_MB = 100


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def detect_categories(text):
    found = set()
    for m in CLASS_RE.finditer(text):
        for tok in TOKEN_RE.findall(m.group(1)):
            found.add(ROMAN[tok.lower()])
    for m in ORDINAL_RE.finditer(text):
        found.add(ROMAN[m.group(1)])
    if NEET_RE.search(text):
        found.add("NEET")
    if JEE_RE.search(text):
        found.add("JEE")
    if not found:
        found.add("Other")
    return [c for c in CATEGORY_ORDER if c in found]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    counts = "--no-counts" not in sys.argv
    root = os.path.abspath(args[0] if args else ".")
    index_path = os.path.join(root, "index.json")
    if not os.path.isfile(index_path):
        print("ERROR: index.json not found in", root)
        print("Run this script inside your repo folder, or pass the folder path.")
        sys.exit(1)

    data = load_json(index_path)
    books = data.get("books", [])
    overrides = {}
    ov_path = os.path.join(root, "category_overrides.json")
    if os.path.isfile(ov_path):
        overrides = load_json(ov_path)

    out_dir = os.path.join(root, "structure")
    os.makedirs(out_dir, exist_ok=True)

    cat_count = {c: 0 for c in CATEGORY_ORDER}
    other_books = []
    warnings = []

    for i, b in enumerate(books, 1):
        title = b.get("title") or b.get("book_name") or ""
        folder = b.get("folder_name") or title
        book_id = b.get("book_id")

        # ---- categories
        forced = overrides.get(folder) or overrides.get(title)
        cats = [c for c in CATEGORY_ORDER if c in forced] if forced else detect_categories(title + " " + folder)
        b["categories"] = cats
        for c in cats:
            cat_count[c] += 1
        if cats == ["Other"]:
            other_books.append(title)

        # ---- structure
        bdir = os.path.join(root, folder)
        if not os.path.isdir(bdir):
            warnings.append("Folder not found for book: %s  (folder_name: %s)" % (title, folder))
            continue
        if not book_id:
            warnings.append("No book_id for book: %s (structure file skipped)" % title)
            continue

        topics = []
        for tname in sorted(os.listdir(bdir), key=natural_key):
            tdir = os.path.join(bdir, tname)
            if tname.startswith(".") or not os.path.isdir(tdir):
                continue
            files = []
            for fname in sorted(os.listdir(tdir), key=natural_key):
                if not fname.lower().endswith(".json"):
                    continue
                entry = {"name": fname[:-5], "file": fname}
                if counts:
                    try:
                        d = load_json(os.path.join(tdir, fname))
                        qs = d.get("questions", []) if isinstance(d, dict) else []
                        entry["count"] = len(qs)
                        if d.get("exercise_name"):
                            entry["name"] = d["exercise_name"]
                    except Exception as e:
                        warnings.append("Cannot read %s/%s/%s (%s)" % (folder, tname, fname, e))
                files.append(entry)
            if files:
                topics.append({"topic_name": tname, "files": files})

        with open(os.path.join(out_dir, "%s.json" % book_id), "w", encoding="utf-8") as f:
            json.dump({"book_id": book_id, "folder_name": folder, "topics": topics},
                      f, ensure_ascii=False, separators=(",", ":"))
        print("[%d/%d] %s -> %d chapters" % (i, len(books), title, len(topics)))

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # ---- size check (GitHub rejects files over 100 MB)
    too_big, big = [], []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".git"]
        for n in fn:
            p = os.path.join(dp, n)
            try:
                mb = os.path.getsize(p) / (1024 * 1024)
            except OSError:
                continue
            rel = os.path.relpath(p, root)
            if mb > MAX_MB:
                too_big.append((rel, mb))
            elif mb > WARN_MB:
                big.append((rel, mb))

    print("\n===== CATEGORIES =====")
    for c in CATEGORY_ORDER:
        print("%-10s %d books" % (c, cat_count[c]))
    if other_books:
        print("\nBooks in 'Other' (check if any should be in a category):")
        for t in other_books:
            print("  -", t)

    if warnings:
        print("\n===== WARNINGS =====")
        for w in warnings:
            print("  !", w)

    if big:
        print("\n===== LARGE FILES (over %d MB, upload with git, not the browser) =====" % WARN_MB)
        for rel, mb in big:
            print("  %.1f MB  %s" % (mb, rel))
    if too_big:
        print("\n===== TOO BIG FOR GITHUB (over %d MB) - will NOT upload =====" % MAX_MB)
        for rel, mb in too_big:
            print("  %.1f MB  %s" % (mb, rel))
        print("Split or compress these files before pushing.")
    else:
        print("\nOK: no file is over %d MB." % MAX_MB)

    print("\nDone. Now upload/push: index.json and the structure/ folder.")


if __name__ == "__main__":
    main()

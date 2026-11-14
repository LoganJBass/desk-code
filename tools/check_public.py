"""check_public.py: refuse to publish this repo if anything private is in it. Run before every push.
python3 tools/check_public.py [--deny-file PATH]     exit 0 = clean, exit 1 = blocked (prints every finding)

Blocks: data files (json, csv, sqlite, xlsx...), email addresses, long digit runs (account numbers), UUIDs (broker
account ids), and, with --deny-file, any word from a private list kept OUTSIDE this repo (held tickers, account
names). The deny list is built fresh at publish time from SnapTrade holdings; it is never committed here."""
import os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ALLOWED_EXT = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml", ""}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}
PATTERNS = {
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "long digit run (account number?)": re.compile(r"(?<![\d.])\d{8,}(?![\d.])"),
    "UUID (broker account id?)": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
}
# OCC option tickers carry an 8-digit strike field ("ABBV 270115C00300000"); those are contract formats, not accounts
OCC_RE = re.compile(r"[A-Z.]+\s+\d{6}[CP]\d{8}")


def main(argv):
    deny = []
    if "--deny-file" in argv:
        p = argv[argv.index("--deny-file") + 1]
        deny = [w.strip() for w in open(p) if w.strip() and not w.startswith("#")]
    findings = []
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in files:
            path = os.path.join(dirpath, fn); rel = os.path.relpath(path, ROOT)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in ALLOWED_EXT:
                findings.append(f"{rel}: file type {ext} not allowed in the public repo"); continue
            text = open(path, encoding="utf-8", errors="replace").read()
            scan = OCC_RE.sub("OCC", text)
            for label, rx in PATTERNS.items():
                for m in rx.finditer(scan):
                    findings.append(f"{rel}: {label}: {m.group(0)[:40]}")
            for w in deny:
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", text):
                    findings.append(f"{rel}: private term from the deny list")
    if findings:
        print("BLOCKED: not safe to publish\n" + "\n".join(sorted(set(findings))))
        return 1
    print("clean: nothing private found" + (f" (deny list: {len(deny)} terms)" if deny else " (no deny list given)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

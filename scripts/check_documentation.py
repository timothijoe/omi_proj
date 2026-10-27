"""Check local Markdown links and anchors without starting project services.

External URLs and absolute machine paths are not fetched. Missing local/third-party
resources are reported separately from broken repository documentation links.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def without_code(text):
    lines, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            mark = match.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            lines.append('')
        else:
            lines.append('' if fence else line)
    return '\n'.join(lines)


def slug(title):
    title = re.sub(r'<[^>]+>', '', title)
    title = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', title)
    title = html.unescape(title).strip().lower()
    # GitHub heading IDs preserve CJK, underscores and hyphens, not punctuation.
    return ''.join(c for c in title if c in ' _-' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')


def anchors(text):
    text = without_code(text)
    result = set(re.findall(r'\b(?:id|name)=["\x27]([^"\x27]+)["\x27]', text))
    counts = {}
    lines = text.splitlines()
    titles = []
    for i, line in enumerate(lines):
        heading = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if heading:
            titles.append(heading.group(1))
        elif i and re.fullmatch(r' {0,3}(?:=+|-+)\s*', line) and lines[i-1].strip():
            titles.append(lines[i-1])
    for title in titles:
        base = slug(title)
        n = counts.get(base, 0)
        counts[base] = n+1
        result.add(base if n == 0 else f'{base}-{n}')
    return result


def links(text):
    """Yield target and line for inline links, reference definitions and HTML."""
    text = without_code(text)
    for n, line in enumerate(text.splitlines(), 1):
        line = re.sub(r'`+[^`]*`+', '', line)
        for match in re.finditer(r'!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+["\x27][^\n]*?["\x27])?\s*\)', line):
            yield match.group(1).strip('<>'), n
        definition = re.match(r'^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)', line)
        if definition:
            yield definition.group(1).strip('<>'), n
        for match in re.finditer(r'\b(?:href|src)=["\x27]([^"\x27]+)["\x27]', line):
            yield match.group(1), n


def markdown_files():
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.md'], cwd=ROOT
    ).decode().split('\0')
    return sorted(ROOT/name for name in set(names) if name and (ROOT/name).is_file()
                  and not name.startswith(('third_party/', 'local/')))


def check():
    broken, resources, skipped = [], [], []
    cache = {}
    count = 0
    files = markdown_files()
    for source in files:
        for target, line in links(source.read_text()):
            item = dict(source=str(source.relative_to(ROOT)), line=line, target=target)
            if urlsplit(target).scheme or target.startswith(('/', '//')):
                skipped.append(item)
                continue
            path, _, fragment = unquote(html.unescape(target)).partition('#')
            destination = (source.parent/path).resolve() if path else source
            try:
                rel = destination.relative_to(ROOT)
                external = rel.parts[0] in ('local', 'data', 'third_party')
            except ValueError:
                external = True
            count += 1
            if not destination.exists():
                item['reason'] = 'missing_path'
                (resources if external else broken).append(item)
            elif fragment and destination.suffix.lower() == '.md' and destination.is_file():
                if destination not in cache:
                    cache[destination] = anchors(destination.read_text())
                if fragment not in cache[destination]:
                    item['reason'] = 'missing_anchor'
                    (resources if external else broken).append(item)
    return dict(markdown_files=len(files), checked_links=count, broken=broken,
                missing_external_resources=resources, skipped_remote_or_absolute=skipped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = check()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f'{report["markdown_files"]} Markdown files, {report["checked_links"]} local links: '
          f'{len(report["broken"])} broken repository links, '
          f'{len(report["missing_external_resources"])} missing external-resource references.')
    for issue in report['broken'][:40]:
        print(f'{issue["source"]}:{issue["line"]}: {issue["reason"]}: {issue["target"]}')
    return bool(report['broken'])


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""检查指定路径的词表；未传参数时使用当前工作目录的专有名词.md。error 返回 1，warning 不阻断。
可选 pypinyin 用于中文分区和排序；不自动安装依赖。
"""
from __future__ import annotations
import re
import sys
from datetime import datetime
from pathlib import Path

FIELDS = ('释义', '特点', '出处', '易混点', '相关词汇', '收录', '修改')
RECORDERS = {'Michale', 'DeepSeek', '克劳德', 'GitHub Copilot', 'YuHaoran', '未知'}
TRIPLE = re.compile(r'^`([^`]+)` · `([^`]+)` · `([^`]+)`(?: 另义：(.+))?$')
FIELD = re.compile(r'^- \*\*(.+?)\*\*：(.*)$')
ANCHOR = re.compile(r'\[\[#([^\]]+)\]\]')
MATH = re.compile(r'\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)[^\n$]+\$(?!\$)')
try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


def chinese(title):
    return bool(title) and '\u4e00' <= title[0] <= '\u9fff'


def valid_date(value, fmt):
    try:
        return datetime.strptime(value, fmt).strftime(fmt) == value
    except ValueError:
        return False


def main(path: Path):
    errors, warnings = [], []
    text = path.read_text(encoding='utf-8')
    fm = re.match(r'\A---\n(.*?)\n---(?:\n|$)', text, re.S)
    if not fm:
        errors.append('缺少完整 YAML frontmatter')
    else:
        for key, fmt in [('created', '%Y-%m-%d'), ('updated', '%Y-%m-%d-%H:%M')]:
            values = re.findall(rf'^{key}:\s*(.*?)\s*$', fm[1], re.M)
            if len(values) != 1 or not valid_date(values[0], fmt):
                errors.append(f'frontmatter {key} 缺失、重复或日期无效')
    entries, sections = [], []
    current, active = None, None
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
            sections.append(current)
            active = None
            if not re.fullmatch('[A-Z]', current):
                errors.append(f'无效分区：{current}')
        elif line.startswith('### '):
            active = {'title': line[4:].strip(), 'letter': current, 'lines': []}
            entries.append(active)
            if current is None:
                errors.append(f'词条未放入字母分区：{active["title"]}')
        elif active is not None:
            active['lines'].append(line)
    if sections != sorted(set(sections)):
        errors.append('分区重复或未按 A–Z 排列')
    if not entries:
        errors.append('未发现词条')
    titles = [e['title'] for e in entries]
    for t in set(titles):
        if titles.count(t) > 1:
            errors.append(f'标题重复：{t}')
    if any(chinese(t) for t in titles) and lazy_pinyin is None:
        warnings.append('未安装 pypinyin，跳过中文分区及拼音排序检查')
    rel_map = {}
    for entry in entries:
        title, lines = entry['title'], entry['lines']
        tag = f'[{entry["letter"]}] {title}'
        def error(message):
            errors.append(f'{tag}: {message}')
        if not title or '`' in title:
            error('标题为空或含反引号')
        nonblank = [line for line in lines if line.strip()]
        triple = TRIPLE.fullmatch(nonblank[0]) if nonblank else None
        if not triple:
            error('首行三元组或另义格式无效')
        elif triple[4]:
            other = ANCHOR.findall(triple[4])
            if not other or ANCHOR.sub('', triple[4]).strip(' 、，,'):
                error('另义只能填写本文件锚点链接')
            for target in other:
                if target not in titles or target == title:
                    error(f'另义链接无效：{target}')
        fields, order, name = {}, [], None
        for line in lines[1:] if nonblank and lines and lines[0] == nonblank[0] else lines:
            match = FIELD.fullmatch(line)
            if match:
                name = match[1]
                order.append(name)
                fields[name] = match[2].strip()
            elif name and line.strip():
                fields[name] += '\n' + line
        if order != list(FIELDS):
            error('字段必须完整、唯一，并按释义/特点/出处/易混点/相关词汇/收录/修改排列')
        for key in FIELDS:
            if not fields.get(key, '').strip():
                error(f'字段为空或缺失：{key}')
        for key in ('释义', '特点', '易混点'):
            value = fields.get(key, '')
            prose = MATH.sub('', value)
            if key == '特点' and title.endswith('汇总'):
                prose = '\n'.join(line for line in prose.splitlines() if not line.strip().startswith('|'))
            if len(re.sub(r'\s', '', prose)) > 100:
                error(f'{key}说明文字超过 100 字符')
            if '$' in prose:
                error(f'{key}含未配对或不支持的数学定界符')
            if re.search(r'\\\(|\\\[|[²³⁻⁰¹⁴⁵⁶⁷⁸⁹ᵀ]', prose):
                error(f'{key}公式须改用 $…$ 或 $$…$$ LaTeX')
            for formula in re.findall(r'\$\$([\s\S]*?)\$\$', value):
                if '$' in formula:
                    error('行间公式内部不应再嵌套美元定界符')
                if not re.search(r'^\$\$\n' + re.escape(formula.strip()) + r'\n\$\$$', value, re.M):
                    error('行间公式须使用独占行的 $$ 定界符')
        src = fields.get('出处', '')
        links = len(re.findall(r'\[[^\]\n]+\]\([^\s)]+\)|\[\[[^\]\n]+\]\]|https?://[^\s<>]+', src))
        # Markdown URL 已由完整链接匹配消费，不重复计数。
        if links != 1 and not (links == 0 and re.fullmatch(r'（来源：.+，待补链接）', src)):
            error('出处须包含一个链接，或使用约定的待补链接说明')
        rel = fields.get('相关词汇', '')
        targets = ANCHOR.findall(rel)
        if rel != '无' and (not targets or ANCHOR.sub('', rel).strip(' 、，,')):
            error('相关词汇只能使用已有词条锚点，或填无')
        if len(targets) > 5 or len(targets) != len(set(targets)):
            error('相关词汇超过 5 个或存在重复')
        for target in targets:
            if target == title or target not in titles:
                error(f'相关词汇锚点无效：{target}')
        rel_map[title] = set(targets)
        previous = None
        for key in ('收录', '修改'):
            value = fields.get(key, '')
            if key == '修改' and value == '—':
                continue
            if key == '修改':
                history_lines = value.splitlines()
                if not history_lines or history_lines[0] != '' or any(
                    not line.startswith('  - ') for line in history_lines[1:]
                ) or len(history_lines) < 2:
                    error('修改记录须在字段下使用缩进两个空格的列表，每次独占一行')
                    continue
                records = [line[4:] for line in history_lines[1:]]
            else:
                records = [value]
            for record in records:
                pattern = r'(\d{4}-\d{2}-\d{2}-\d{2}:\d{2})（([^（）\n；]+)）'
                if key == '修改':
                    pattern += r'：([^\n]+)'
                match = re.fullmatch(pattern, record)
                if not match or not valid_date(match[1], '%Y-%m-%d-%H:%M'):
                    error(f'{key}须为有效的 YYYY-MM-DD-HH:mm（作者）' + ('：修改简述' if key == '修改' else ''))
                    continue
                moment, author = match[1], match[2]
                if key == '修改' and not 5 <= len(re.sub(r'\s', '', match[3])) <= 6:
                    error('修改简述须为 5–6 个字符（不计空白）')
                if previous is not None and moment < previous:
                    error('修改时间不得早于收录或前次修改时间')
                previous = moment
                if not author.strip():
                    error(f'{key}作者不能为空')
                elif author not in RECORDERS:
                    warnings.append(f'{tag}: 请确认作者「{author}」是否为工具原名')
        if title:
            initial = (lazy_pinyin(title)[0][0].upper() if lazy_pinyin else None) if chinese(title) else title[0].upper()
            if initial and initial != entry['letter']:
                error(f'应放入 {initial} 区')
    for letter in sections:
        names = [e['title'] for e in entries if e['letter'] == letter and e['title']]
        flags = [chinese(n) for n in names]
        if flags != sorted(flags):
            errors.append(f'[{letter}] 区须英文在前、中文在后')
        for cn in (False, True):
            subset = [n for n in names if chinese(n) == cn]
            if cn and lazy_pinyin is None:
                continue
            key = (lambda n: tuple(lazy_pinyin(n))) if cn else str.casefold
            if subset != sorted(subset, key=key):
                errors.append(f'[{letter}] 区{"中文拼音" if cn else "英文"}排序错误')
    for source, targets in rel_map.items():
        for target in targets:
            if target in rel_map and source not in rel_map[target]:
                warnings.append(f'单向链接：{source} → {target}')
    for warning in warnings:
        print('WARN ', warning)
    for error in errors:
        print('ERROR', error)
    print(f'\n共 {len(entries)} 条词条｜error {len(errors)}｜warning {len(warnings)}')
    return int(bool(errors))


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / '专有名词.md'
    if not target.is_file():
        print(f'ERROR 词表不存在：{target}；请传入词表路径。', file=sys.stderr)
        sys.exit(2)
    sys.exit(main(target))


'''
· Time / Lecture / Timetable：时间、课次、课表集合
· read_csv：从 CSV 读入（字段：课程名、星期几、开始时间、结束时间）
· output：打印「本周课表」文本视图（同一门课连续两节合并成一行，不出现碎片）
· output_free：按每天的可用时间范围（默认 08:00-22:00）算出空闲时段并打印；
  同一门课连续两节（课间不超过 gap 分钟）自动合并成一块，不会切出 09:45-09:55 这种碎片
'''

# lectures.py 用的是 "from timetable import *"，也就是把这张表里的名字全部拿过去。
# 注意：下划线开头的名字默认不会被 * 带走，写进 __all__ 才会 ——
# 所以以后入口要用新的内部函数（_xxx），把它加到下面这张表里就行。
__all__ = [
    "WEEKDAYS", "Time", "Lecture", "Timetable", "Slot",
    "DEFAULT_WINDOW", "MERGE_GAP",
    "parse_day", "parse_time", "parse_window",
    "read_csv", "choose_csv", "input_manual",
    "merge_lectures", "free_slots", "output", "output_free",
    "_ask", "_fmt",
]

import csv
import os
import sys
import unicodedata

try:  # Windows 控制台默认可能是 GBK，统一切到 UTF-8，避免中文打印报错
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ---- 星期几的各种写法 -> 1..7 ----------------------------------------------
_DAY_MAP = {}
for _i, _full in enumerate(WEEKDAYS, start=1):
    for _kw in (
        _full,                       # 星期一
        "周" + _full[-1],            # 周一
        "礼拜" + _full[-1],           # 礼拜一
        _full[-1],                   # 一
        str(_i),                     # 1
    ):
        _DAY_MAP[_kw] = _i
_DAY_MAP.update({
    "星期天": 7, "周天": 7, "礼拜天": 7, "日": 7, "天": 7,
    "mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3, "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "fri": 5, "friday": 5, "sat": 6, "saturday": 6, "sun": 7, "sunday": 7,
})

# ---- CSV 表头别名 ----------------------------------------------------------
_HEADER_ALIASES = {
    "name": {"课程名", "课程", "课名", "名称", "name", "course", "subject", "lecture"},
    "day": {"星期几", "星期", "周几", "周", "day", "weekday", "week"},
    "begin": {"开始时间", "开始", "起始时间", "start", "begin", "from"},
    "end": {"结束时间", "结束", "终止时间", "end", "finish", "to"},
}

_FULLWIDTH = str.maketrans("０１２３４５６７８９：．", "0123456789:.")


def _norm(s):
    """归一化：去空格、去全角空格、转小写，便于匹配表头和星期几。"""
    return str(s).strip().replace(" ", "").replace("\u3000", "").lower()


def parse_day(value):
    """把 '星期一' / '周一' / '1' / 'mon' 都转成 1..7。"""
    if isinstance(value, int):
        if 1 <= value <= 7:
            return value
        raise ValueError(f"星期只能是 1~7，收到：{value}")
    key = _norm(value)
    if key in _DAY_MAP:
        return _DAY_MAP[key]
    raise ValueError(f"无法识别的星期：{value!r}")


def parse_time(value):
    """把 '8:00' / '08：00' / '8.30' / '8点30' / '8' 转成 (hour, min)。

    中文习惯里 8.30 就是 8:30，所以 "." 和 "点" 都当分隔符；只有小时时分钟算 0。
    """
    s = (str(value).translate(_FULLWIDTH).strip()
         .replace("点", ":").replace("分", "")
         .replace(".", ":"))
    if not s:
        raise ValueError("时间不能为空")
    parts = [p for p in s.split(":") if p != ""]  # '8:' 这类落单的冒号直接忽略
    if len(parts) > 2:
        raise ValueError(f"无法识别的时间：{value!r}")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (IndexError, ValueError):
        raise ValueError(f"无法识别的时间：{value!r}")
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"时间超出范围：{value!r}")
    return hour, minute


class Time:
    def __init__(self, day, **t):
        self.day = parse_day(day)
        if "time" in t:
            self.hour, self.min = parse_time(t["time"])
        else:
            self.hour = int(t.get("hour", 0))
            self.min = int(t.get("min", 0))
        if not (0 <= self.hour < 24 and 0 <= self.min < 60):
            raise ValueError(f"时间超出范围：{self.hour}:{self.min}")

    @property
    def day_name(self):
        return WEEKDAYS[self.day - 1]

    def key(self):
        return (self.day, self.hour, self.min)

    def __str__(self):
        return f"{self.hour:02d}:{self.min:02d}"

    def __repr__(self):
        return self.__str__()

    def __lt__(self, other):
        return self.key() < other.key()

    def __eq__(self, other):
        return isinstance(other, Time) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __sub__(self, other):
        if self.day == other.day:
            return abs((self.hour - other.hour) * 60 + (self.min - other.min))
        raise ValueError("Day must be the same.")


class Lecture:
    def __init__(self, begin, end, name):
        self.begin = begin
        self.end = end
        self.name = name

    def key(self):
        #一次课的唯一标识：课程名 + 星期 + 起止时间。
        return (self.name, self.begin.key(), self.end.key())

    def __str__(self):
        return f"{self.name}（{self.begin.day_name} {self.begin}-{self.end}）"

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        return isinstance(other, Lecture) and self.key() == other.key()

    def __hash__(self):
        # 定义了 __eq__ 就必须定义 __hash__，否则 Lecture 不可放进 set
        return hash(self.key())


class Timetable:
    def __init__(self):
        self.lectures = []
        self._seen = set()

    def add(self, lec, quiet=False):
        """加一节课。已存在完全相同的课次时返回 False，不重复加入。"""
        if lec in self._seen:
            if not quiet:
                print(f"[提示] 重复课程，已跳过：{lec}")
            return False
        self._seen.add(lec)
        self.lectures.append(lec)
        return True

    def extend(self, lectures, quiet=False):
        """批量加入，返回真正加进去的条数。"""
        return sum(1 for lec in lectures if self.add(lec, quiet=quiet))

    def __iter__(self):
        return iter(self.lectures)

    def __len__(self):
        return len(self.lectures)


def read_csv(path):
    """
    容错点：自动尝试 utf-8-sig / utf-8 / gbk 编码；表头可缺省（此时按上面的字段顺序读）；
    表头支持中英文别名；个别坏行只警告、不中断整个文件。
    """
    rows = None
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, newline="", encoding=enc) as f:
                rows = [r for r in csv.reader(f) if any(str(c).strip() for c in r)]
            break
        except UnicodeDecodeError as e:
            last_err = e
    if rows is None:
        raise ValueError(f"无法解码文件 {path}（已尝试 utf-8-sig/utf-8/gbk）：{last_err}")
    if not rows:
        return []

    # 判断第一行是表头还是数据：第二列能不能当“星期几”解析
    first = rows[0]
    second = first[1] if len(first) > 1 else ""
    try:
        parse_day(second)
        has_header, data_rows = False, rows
    except ValueError:
        has_header, data_rows = True, rows[1:]

    idx = {"name": 0, "day": 1, "begin": 2, "end": 3}
    if has_header:
        for i, cell in enumerate(first):
            key = _norm(cell)
            for field, aliases in _HEADER_ALIASES.items():
                if key in aliases:
                    idx[field] = i

    lectures = []
    for line_no, row in enumerate(data_rows, start=2 if has_header else 1):
        if len(row) <= max(idx.values()):
            print(f"[警告] 第 {line_no} 行字段不足，已跳过：{row}")
            continue
        name = str(row[idx["name"]]).strip()
        if not name:
            print(f"[警告] 第 {line_no} 行课程名为空，已跳过")
            continue
        try:
            day = parse_day(row[idx["day"]])
            begin = Time(day, time=row[idx["begin"]])
            end = Time(day, time=row[idx["end"]])
        except ValueError as e:
            print(f"[警告] 第 {line_no} 行解析失败，已跳过：{e}")
            continue
        if end < begin:
            print(f"[警告] 第 {line_no} 行结束时间早于开始时间，已跳过：{name}")
            continue
        lectures.append(Lecture(begin, end, name))
    return lectures


# ---- 时间段工具：课表视图和空闲时段都要用 -----------------------------------
# 每天可用的时间范围（从 0 点起的分钟数）和「连堂」判定阈值
DEFAULT_WINDOW = (8 * 60, 22 * 60)
MERGE_GAP = 15


def _to_minutes(t):
    """Time -> 从 0 点起的分钟数。"""
    return t.hour * 60 + t.min


def _fmt(m):
    """分钟数 -> 'HH:MM'。1440 显示成 24:00（Time 的 hour 只能是 0~23，表示不了）。"""
    return f"{m // 60:02d}:{m % 60:02d}"


def _hm(m):
    """分钟数 -> '1 小时 20 分钟' 这种给人看的写法。"""
    h, mi = divmod(m, 60)
    if h and mi:
        return f"{h} 小时 {mi} 分钟"
    if h:
        return f"{h} 小时"
    return f"{mi} 分钟"


class Slot:
    """同一天里的一段时间。

    时间用「从 0 点起的分钟数」存，不用 Time：一是 08:00-24:00 这种右端点 Time 表示不了，
    二是做集合相减、合并时整数最直观（不用一路写 Time 的比较和临时对象）。
    names 为空表示这段是空闲；count 是这段里并进去的课次数量（用于显示「2 节合并」）。
    """

    def __init__(self, day, begin, end, names=(), count=0):
        if begin>end:
            raise ValueError("起始时间在结束时间之前")
        self.day = day
        self.begin = begin
        self.end = end
        self.names = list(names)
        self.count = count

    @property
    def minutes(self):
        return self.end - self.begin

    @property
    def is_free(self):
        return not self.names

    def __str__(self):
        return f"{_fmt(self.begin)}-{_fmt(self.end)}"

    def __repr__(self):
        return self.__str__()
    
    



def merge_lectures(lst, gap=MERGE_GAP):
    """把课次合并成若干时间段，返回 [Slot, ...]（按天、按时间排序）。

    两步走：
    1) 同一门课（同一天）按时间排序，两节之间只隔 ≤ gap 分钟就连起来；
       —— 这一步就是解决 09:00-09:45 + 09:55-10:40 被切成两块的问题；
    2) 不同课程之间真正重叠的部分再合并（同一天不可能同时上两门课，重叠就是排课冲突）。
    注意区分：第 1 步用 gap（有意的课间），第 2 步只看是否真的重叠，不会把两门不同的课
    用 gap 硬粘在一起。
    """
    by_key = {}
    for lec in lst:
        by_key.setdefault((lec.begin.day, lec.name), []).append(lec)

    blocks = []
    for (day, name), group in by_key.items():
        group.sort(key=lambda lec: lec.begin.key())
        start, stop, count = _to_minutes(group[0].begin), _to_minutes(group[0].end), 1
        for lec in group[1:]:
            b, e = _to_minutes(lec.begin), _to_minutes(lec.end)
            if b - stop <= gap:          # 上一节下课到这一节上课只隔 ≤ gap 分钟 -> 算连堂
                stop = max(stop, e)      # max 而不是直接覆盖：时间写重叠了也不会把区间吃回去
                count += 1
            else:
                blocks.append(Slot(day, start, stop, [name], count))
                start, stop, count = b, e, 1
        blocks.append(Slot(day, start, stop, [name], count))

    blocks.sort(key=lambda s: (s.day, s.begin))
    merged = []
    for s in blocks:
        last = merged[-1] if merged else None
        if last is not None and s.day == last.day and s.begin <= last.end:
            last.end = max(last.end, s.end)
            last.count += s.count
            last.names += [n for n in s.names if n not in last.names]
        else:
            merged.append(s)
    return merged


def _block_label(slot):
    """占用块怎么显示：课程名，连堂加「（2 节合并）」，撞车加「（时间冲突）」。"""
    label = "、".join(slot.names)
    if len(slot.names) > 1:
        return f"{label}（时间冲突）"
    if slot.count > 1:
        return f"{label}（{slot.count} 节合并）"
    return label


def _width(s):
    """字符串显示宽度：中日韩全角算 2。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _center(s, width):
    pad = max(0, width - _width(s))
    left = pad // 2
    return " " * left + s + " " * (pad - left)


def output(lst, gap=MERGE_GAP):
    line = "=" * 46
    print()
    print(line)
    print(_center("本 周 课 表",46))
    print(line)
    if not lst:
        print(_center("本周暂无课程",46))
        print(line)
        return

    lectures = sorted(lst, key=lambda lec: lec.begin.key())
    # 合计只算上课时间，不含连堂中间那点课间（所以合计可能比左边显示的时间跨度短）
    total_min = sum(lec.begin - lec.end for lec in lectures)
    for day in range(1, 8):
        todays = [lec for lec in lectures if lec.begin.day == day]
        print(WEEKDAYS[day - 1])
        if not todays:
            print("  （无课）")
            continue
        # 同一门课连续两节合并成一行，免得出现 09:00-09:45 / 09:55-10:40 这种碎片
        blocks = merge_lectures(todays, gap)
        for i, block in enumerate(blocks):
            branch = "└─" if i == len(blocks) - 1 else "├─"
            print(f"  {branch} {block}  {_block_label(block)}")
    print(line)
    print(f"共 {len(lectures)} 节课，合计 {total_min // 60} 小时 {total_min % 60} 分钟")


# ---- 需求二：空闲时段 -------------------------------------------------------
def parse_window(text):
    """把 '08:00-22:00' 解析成 (开始分钟, 结束分钟)。

    分隔符随便写：- ~ ～ — – 至 都认；结束写 24:00 或 00:00 表示到当天 24 点。
    """
    s = (str(text).translate(_FULLWIDTH).strip()
         .replace("—", "-").replace("–", "-").replace("～", "-")
         .replace("~", "-").replace("至", "-"))
    parts = [p.strip() for p in s.split("-") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"可用范围要写成「开始-结束」，例如 08:00-22:00，收到：{text!r}")
    begin = _to_minutes(Time(1, time=parts[0]))
    if _norm(parts[1]) in ("24", "24:00", "0", "0:00", "00:00"):
        end = 24 * 60  # 结束写 0 点/24 点都当「到当天 24 点」
    else:
        end = _to_minutes(Time(1, time=parts[1]))
        if end == 0:
            end = 24 * 60
    if end <= begin:
        raise ValueError(f"可用范围的结束时间要晚于开始时间：{text!r}")
    return begin, end


def _timeline(day, blocks, win_begin, win_end):
    """把占用块从可用范围里挖掉，得到一段段「占用 / 空闲」交替的时间轴。"""
    segments = []
    cursor = win_begin
    for b in blocks:
        if b.end <= win_begin or b.begin >= win_end:  # 整块都在可用范围外
            continue
        b_begin = max(b.begin, win_begin)
        b_end = min(b.end, win_end)
        if cursor < b_begin:                          # 两块之间才是空闲
            segments.append(Slot(day, cursor, b_begin))
        segments.append(Slot(day, b_begin, b_end, b.names, b.count))
        cursor = max(cursor, b_end)
    if cursor < win_end:                              # 最后一节课之后的空闲
        segments.append(Slot(day, cursor, win_end))
    return segments


def free_slots(lst, window=DEFAULT_WINDOW, gap=MERGE_GAP):
    """算空闲时段。返回 {星期几: [空闲 Slot, ...]}，时间递增。"""
    win_begin, win_end = window
    result = {}
    for day in range(1, 8):
        todays = [lec for lec in lst if lec.begin.day == day]
        segments = _timeline(day, merge_lectures(todays, gap), win_begin, win_end)
        result[day] = [s for s in segments if s.is_free]
    return result


def output_free(lst, window=DEFAULT_WINDOW, gap=MERGE_GAP):
    """打印「空闲时段」视图（每天一条时间轴），返回本周空闲总分钟数。"""
    win_begin, win_end = window
    lectures = list(lst)
    line = "=" * 46
    print()
    print(line)
    print(_center("空 闲 时 段", 46))
    print(line)
    print(f"可用范围：每天 {_fmt(win_begin)}-{_fmt(win_end)}"
          f"；同一门课间隔 ≤ {gap} 分钟算连堂")

    total_free = 0
    for day in range(1, 8):
        todays = [lec for lec in lectures if lec.begin.day == day]
        blocks = merge_lectures(todays, gap)
        segments = _timeline(day, blocks, win_begin, win_end)
        day_free = sum(s.minutes for s in segments if s.is_free)
        total_free += day_free
        print(line)
        print(f"{WEEKDAYS[day - 1]}　空闲 {_hm(day_free)}（{sum(1 for s in segments if s.is_free)} 段）")
        for i, s in enumerate(segments):
            branch = "└─" if i == len(segments) - 1 else "├─"
            if s.is_free:
                # 比 gap 还短的自由时间其实就是课间，标一下免得当成能用的空档
                tip = "（课间）" if s.minutes <= gap else ""
                print(f"  {branch} {s}  空闲 {_hm(s.minutes)}{tip}")
            else:
                print(f"  {branch} {s}  {_block_label(s)}")
        for b in blocks:  # 有课超出可用范围时给一句提示，免得算少了却不明白
            if b.begin < win_begin or b.end > win_end:
                print(f"  [提示] {b} {'、'.join(b.names)} 超出可用范围，只按范围内计算")
    print(line)
    print(f"本周空闲合计 {_hm(total_free)}（每天可用 {_hm(win_end - win_begin)}）")
    return total_free


def _ask(prompt):
    try:
        line = input(prompt)
    except EOFError:
        print()
        return None
    return line.replace("\ufeff", "").replace("\u200b", "").strip()


def choose_csv(initialdir=None):
    """让用户手动浏览挑一个 CSV。返回文件路径；用户取消或没得选时返回 None。

    优先弹系统文件选择框，用不了就退回控制台按编号选。
    """
    initialdir = initialdir or os.getcwd()
    path = _pick_file_gui(initialdir)
    if path is not None:
        return path or None  # 对话框里点“取消”拿到的是 ""，统一成 None
    return _pick_file_console(initialdir)


def _pick_file_gui(initialdir):
    """弹 tkinter 文件选择框。返回路径；用户取消返回 ""；用不了返回 None。"""
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as e:  # 没装 tkinter / 没有 Tcl
        print(f"[提示] 图形选择框不可用（{e}），改用控制台选择")
        return None
    try:
        root = tkinter.Tk()
        root.withdraw()  # 藏掉 Tk 那个多余的空白主窗口
        root.attributes("-topmost", True)  # 免得对话框被别的窗口挡在后面
        path = filedialog.askopenfilename(
            title="选择课表 CSV 文件",
            initialdir=initialdir,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        root.destroy()
        return path
    except Exception as e:  # 无显示环境（ssh、服务里跑）
        print(f"[提示] 图形选择框打不开（{e}），改用控制台选择")
        return None


def _pick_file_console(initialdir):
    """控制台兜底：列出目录里的 .csv，按编号选。返回路径或 None。"""
    try:
        names = sorted(n for n in os.listdir(initialdir) if n.lower().endswith(".csv"))
    except OSError as e:
        print(f"[错误] 无法列出目录 {initialdir}：{e}")
        return None
    if not names:
        print(f"[提示] {initialdir} 下没有 .csv 文件，请直接输入完整路径")
        return None
    print(f"{initialdir} 下的 CSV：")
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n}")
    ans = _ask("请输入编号（回车取消）：")
    if not ans:
        return None
    if ans.isdigit() and 1 <= int(ans) <= len(names):
        return os.path.join(initialdir, names[int(ans) - 1])
    print("[提示] 编号无效")
    return None


def input_manual(tt):
    print("每行按「课程名 星期几 开始时间 结束时间」输入，直接回车结束（课程名里不要带空格）")
    print("例如：高等数学 星期一 08:00 09:40")
    while True:
        raw = _ask("请输入：")
        if not raw:  # None = 输入流结束，"" = 用户直接回车
            break
        parts = raw.replace(",", " ").replace("，", " ").split()
        if len(parts) < 4:
            print("[提示] 需要 4 项：课程名 星期几 开始时间 结束时间")
            continue
        name, day_s, begin_s, end_s = parts[0], parts[1], parts[2], parts[3]
        try:
            begin = Time(day_s, time=begin_s)
            end = Time(day_s, time=end_s)
        except ValueError as e:
            print(f"[错误] {e}")
            continue
        if end < begin:
            print("[提示] 结束时间早于开始时间，请检查")
            continue
        if tt.add(Lecture(begin, end, name)):
            print(f"已添加：{name} {begin.day_name} {begin}-{end}")
    return tt

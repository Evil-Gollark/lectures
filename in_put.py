
'''
读入课表
· 支持手动录入或从 CSV 读入（字段：课程名、星期几、开始时间、结束时间）
· 打印出「本周课表」的文本视图

用法：
    python in_put.py                  # 交互模式：1 手动录入 / 2 从 CSV 读入 / 3 结束并打印
    python in_put.py --csv 课表.csv    # 直接读入 CSV 并打印

菜单里选 2 时地址留空（或 --csv 后面不给路径）会弹出文件选择框让你浏览挑选；
没有图形环境或没装 tkinter 时，自动退回「列出当前目录的 .csv，按编号选」。
'''
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


def _width(s):
    """字符串显示宽度：中日韩全角算 2。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _center(s, width):
    pad = max(0, width - _width(s))
    left = pad // 2
    return " " * left + s + " " * (pad - left)


def output(lst):
    line = "=" * 46
    print()
    print(line)
    print(_center("本 周 课 表", 46))
    print(line)
    if not lst:
        print(_center("本周暂无课程", 46))
        print(line)
        return

    lectures = sorted(lst, key=lambda lec: lec.begin.key())
    total_min = 0
    for day in range(1, 8):
        todays = [lec for lec in lectures if lec.begin.day == day]
        print(WEEKDAYS[day - 1])
        if not todays:
            print("  （无课）")
            continue
        for i, lec in enumerate(todays):
            branch = "└─" if i == len(todays) - 1 else "├─"
            print(f"  {branch} {lec.begin}-{lec.end}  {lec.name}")
            total_min += lec.begin - lec.end
    print(line)
    print(f"共 {len(lectures)} 节课，合计 {total_min // 60} 小时 {total_min % 60} 分钟")


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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tt = Timetable()

    # 非交互：python in_put.py --csv 课表.csv
    if "--csv" in argv:
        i = argv.index("--csv")
        path = argv[i + 1] if i + 1 < len(argv) else ""  # 后面没跟路径也算留空
        if not path:
            print("[提示] --csv 后面没给路径，打开文件选择框")
            path = choose_csv()
            if not path:
                print("[提示] 未选择文件")
                return 1
        try:
            tt.extend(read_csv(path))
        except (OSError, ValueError) as e:
            print(f"[错误] 读取失败：{e}")
            return 1
        output(tt)
        return 0

    while True:
        a = _ask("手动输入请按1，从csv读入请按2，退出输入请按3：")
        if a is None or a in ("3", "q", "Q", "quit", "exit",""):
            break
        if a == "":
            continue
        if a == "1":
            input_manual(tt)
        elif a == "2":
            path = _ask("请输入地址（直接回车 = 浏览选择文件）：")
            if path is None:
                break
            path = path.strip('"').strip("'")
            if not path:
                path = choose_csv()
            if not path:
                print("[提示] 未选择文件")
                continue
            try:
                new = read_csv(path)
            except (OSError, ValueError) as e:
                print(f"[错误] 读取失败：{e}")
                continue
            added = tt.extend(new)
            skipped = len(new) - added
            print(f"已从 {path} 读入 {added} 条记录" + (f"，跳过重复 {skipped} 条" if skipped else ""))
        else:
            print("[提示] 请输入 1 / 2 / 3")
    output(tt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

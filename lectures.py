
'''
课表程序的可执行入口：命令行参数解析 + 交互菜单。

数据结构（Time / Lecture / Timetable）、CSV 读入、课表和空闲时段两个视图
都在同目录的 timetable.py 里；这里只留 main()、参数解析和菜单这些「入口专属」的东西。
以后加新需求：视图和算法写进 timetable.py，菜单项加在这里。

用法：
    python lectures.py                  # 交互模式：1 手动录入 / 2 从 CSV 读入 / 3 打印课表 / 4 查看空闲时段 / 5 找共同空闲 / 6 结束
    python lectures.py --csv 课表.csv    # 直接读入 CSV 并打印课表
    python lectures.py --csv 课表.csv --free                            # 只打印空闲时段
    python lectures.py --csv 课表.csv --free --window 09:00-18:00 --gap 15
    python lectures.py --common --csv 张三.csv --csv 李四.csv           # 找两个人的共同空闲时段

选项：
    --csv [路径]        CSV 路径（可以给多次，一人一个文件；留空则弹文件选择框）
    --common            求多份课表的共同空闲时段，按长度从长到短列出来
    --free              打印「空闲时段」而不是「本周课表」
    --window 08:00-22:00  每天的可用范围（默认 08:00-22:00；结束写 24:00 表示到零点）
    --gap 15            同一门课两节之间休息 ≤ 这么多分钟就算连堂（默认 15；0 = 不合并）
                        课表和空闲时段两个视图都按这个间隔合并
    -h, --help          显示这段帮助

菜单里选 2 时地址留空（或 --csv 后面不给路径）会弹出文件选择框让你浏览挑选；
没有图形环境或没装tkinter 时，自动退回「列出当前目录的 .csv，按编号选」。
'''
import sys

from timetable import *  # noqa: F403
_USAGE = """用法：
  python lectures.py                              交互模式（1 手动录入 / 2 从csv读入 / 3 打印课表 / 4 查看空闲时段 / 5 找共同空闲 / 6 结束）
  python lectures.py --csv 课表.csv                 读入 CSV 并打印课表
  python lectures.py --csv 课表.csv --free          只打印空闲时段
  python lectures.py --csv 课表.csv --free --window 09:00-18:00 --gap 15
  python lectures.py --common --csv 张三.csv --csv 李四.csv   多人的共同空闲时段
选项：
  --csv [路径]          CSV 路径；可以给多次（一人一个文件）；留空或省略路径则弹出文件选择框
  --common              求多份课表的共同空闲时段，按长度从长到短列出
  --free                打印「空闲时段」而不是「本周课表」
  --window 08:00-22:00  每天的可用范围（默认 08:00-22:00；结束写 24:00 表示到零点）
  --gap 15              同一门课两节之间休息 ≤ 这么多分钟就算连堂（默认 15；0 = 不合并）
                        课表和空闲时段两个视图都按这个间隔合并
  -h, --help            显示本帮助"""


def _parse_args(argv):
    """解析命令行参数。返回 (opts, 错误信息)：错误信息非空表示参数有问题。

    opts["csv"] 是个列表：--csv 可以给多次（一人一个文件）。列表为空表示没给 --csv；
    里面某一项是 "" 表示「给了 --csv 但后面没跟路径（要弹选择框）」。
    """
    opts = {"csv": [], "common": False, "free": False,
            "window": DEFAULT_WINDOW, "gap": MERGE_GAP, "help": False}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
            i += 1
            continue
        if arg == "--free":
            opts["free"] = True
            i += 1
            continue
        if arg == "--common":
            opts["common"] = True
            i += 1
            continue
        if arg in ("--csv", "--window", "--gap"):
            # 后面那一项不以 -- 开头才当成本参数的值，否则视为「值留空」
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                value, i = argv[i + 1], i + 2
            else:
                value, i = "", i + 1
            if arg == "--csv":
                opts["csv"].append(value)
            elif arg == "--window":
                if not value:
                    return opts, "--window 后面要跟范围，例如 --window 08:00-22:00"
                try:
                    opts["window"] = parse_window(value)
                except ValueError as e:
                    return opts, f"--window 解析失败：{e}"
            else:
                try:
                    opts["gap"] = int(value)
                except ValueError:
                    return opts, f"--gap 需要整数分钟，收到：{value!r}"
                if opts["gap"] < 0:
                    return opts, "--gap 不能是负数"
            continue
        else:
            break
        #return opts, f"不认识的参数：{arg}（用 -h 看用法）"
    return opts, None


def _ask_free_options():
    """交互式地问「可用范围」和「连堂间隔」，回车就用默认值。返回 ((开始, 结束), gap)。"""
    while True:
        text = _ask(f"请输入每天可用范围（回车默认 {_fmt(DEFAULT_WINDOW[0])}-{_fmt(DEFAULT_WINDOW[1])}）：")
        if text is None:
            return None, None
        if not text:
            window = DEFAULT_WINDOW
            break
        try:
            window = parse_window(text)
            break
        except ValueError as e:
            print(f"[错误] {e}")
    while True:
        text = _ask(f"请输入连堂间隔分钟数（回车默认 {MERGE_GAP}）：")
        if text is None:
            return None, None
        if not text:
            gap = MERGE_GAP
            break
        try:
            gap = int(text)
            if gap < 0:
                raise ValueError("间隔不能是负数")
            break
        except ValueError as e:
            print(f"[错误] {e}")
    return window, gap

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tt = Timetable()
    print(argv)
    opts, err = _parse_args(argv)
    if err:
        print(f"[错误] {err}")
        print(_USAGE)
        return 2
    if opts["help"]:
        print(_USAGE)
        return 0

    # 非交互：给了 --csv / --free / --common 就直接算完打印
    if opts["csv"] or opts["free"] or opts["common"]:
        window, gap = opts["window"], opts["gap"]
        if opts["common"]:
            if not opts["csv"]:
                print("[错误] --common 至少要给一份课表：--common --csv 张三.csv --csv 李四.csv")
                return 2
            people, names = [], []
            for path in opts["csv"]:
                if not path:  # --csv 后面没跟路径（或跟的是另一个 -- 选项）
                    print("[提示] --csv 后面没给路径，打开文件选择框")
                    path = choose_csv()
                    if not path:
                        print("[提示] 未选择文件")
                        continue
                try:
                    name, one = load_timetable(path)
                except (OSError, ValueError) as e:
                    print(f"[错误] 读取 {path} 失败：{e}")
                    return 1
                names.append(name)
                people.append(one)
            if not people:
                print("[提示] 一份课表都没读入")
                return 1
            if len(people) == 1:
                print("[提示] 只给了一份课表，共同空闲就是这一个人的空闲时段")
            output_common(people, window, gap, names)
            return 0
        if not opts["csv"]:
            print("[提示] 没给 --csv，按空课表算空闲时段")
        else:
            if len(opts["csv"]) > 1:
                print("[错误] 给了多份课表；看共同空闲请加 --common，看单人课表请只给一份")
                return 2
            path = opts["csv"][0]
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
        if opts["free"]:
            output_free(tt, window, gap)
        else:
            output(tt, gap)
        return 0

    gap = MERGE_GAP  # 菜单 3 / 4 / 5 用的合并间隔；在 4 或 5 里改过 gap，后面打印课表就跟着用新的
    while True:
        a = _ask("1 手动录入 / 2 从csv读入 / 3 打印课表 / 4 查看空闲时段 / 5 找共同空闲 / 6 结束：")
        if a is None or a in ("6", "q", "Q", "quit", "exit", ""):
            break
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
        elif a == "3":
            output(tt, gap)
        elif a == "4":
            window, gap = _ask_free_options()
            if window is None:
                break
            output_free(tt, window, gap)
        elif a == "5":
            people, names = [], []
            print("把每个人的课表 CSV 依次输进来（一人一个文件）；直接回车 = 弹文件选择框，"
                  "在框里点取消（或输入 q）= 输完了")
            while True:
                path = _ask(f"第 {len(people) + 1} 个人的课表：")
                if path is None:
                    break
                path = path.strip('"').strip("'")
                if path in ("q", "Q"):
                    break
                if not path:
                    # 和菜单 2 一样：先弹图形选择框，没有图形环境就退回「按编号选」
                    path = choose_csv()
                    if not path:
                        print("[提示] 没有选文件，录入结束")
                        break
                try:
                    name, one = load_timetable(path)
                except (OSError, ValueError) as e:
                    print(f"[错误] 读取 {path} 失败：{e}")
                    continue
                names.append(name)
                people.append(one)
                print(f"已读入 {name}：{len(list(one))} 节课")
            if not people:
                print("[提示] 一份课表都没读入")
                continue
            window, gap = _ask_free_options()
            if window is None:
                break
            output_common(people, window, gap, names)
        else:
            print("[提示] 请输入 1 / 2 / 3 / 4 / 5 / 6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

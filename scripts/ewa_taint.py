#!/usr/bin/env python3
"""门禁 2c / 任务 B 共用的「外部目录写入点」AST 识别器。

设计要点
--------
1. **单一实现**：门禁 2c（静态拦截）与任务 B（运行时接线定位）共用本模块，
   避免两套判定口径打架。
2. **作用域隔离的污染分析**：污染集合按函数作用域隔离，模块级污染向内继承，
   函数内的局部污染**不会**泄漏到兄弟函数。这是为了避免 ``f`` / ``fh`` / ``p``
   这类短变量名在不同函数间复用时相互串味（实测未隔离时误报率约 60%）。
3. **路径污染与句柄污染分离**：``open(<外部路径>)`` 产生的是「脏句柄」，
   只有句柄型写调用（``json.dump`` 第 2 实参等）才看它；路径型写调用只看路径污染。
4. **仓库内路径识别**：``os.path.dirname(os.path.abspath(__file__))`` 派生出的
   路径视为仓库内，不判红——否则每个脚本写自己 eval/ 产物都要报警。
5. **fail-closed**：解析失败、编码异常一律判红，不静默放过。

判定为「外部写入」需同时满足：
  - 调用是已知写操作（``ARG_WRITE_CALLS`` / ``RECEIVER_WRITE_CALLS``）；
  - 其路径实参（或接收者、或句柄实参）被判定为指向外部目录。

命中后仍可豁免：
  - 同函数体内导入并调用了 ``require_backup_and_release``（status=guard）；
  - 该行带 ``# external-write-ok: <非空理由>`` 行内注释（status=comment）。
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path

# ---------------------------------------------------------------- 常量

#: 声明外部共享根目录的环境变量名。读取它们即视为污染源。
EXTERNAL_ENV_VARS: tuple[str, ...] = (
    "SKILL_CONTENT",
    "GLOBAL_MEMORY_DIR",
    "GLOBAL_SKILLS_DIR",
)

#: 字面量里出现这些片段即视为外部路径（兜底硬编码值，如「全局记忆目录」的 global_memory 片段）。
EXTERNAL_LITERAL_MARKERS: tuple[str, ...] = ("global_memory", "global_skills")

#: 运行时守卫模块名与放行函数名。
GUARD_MODULE: str = "external_write_guard"
GUARD_CALL: str = "require_backup_and_release"

#: 行内豁免标记，冒号后必须有非空理由。
EXEMPT_TOKEN: str = "# external-write-ok:"

#: 这些路径前缀下的文件不扫描（历史归档 / 报告 / 发布产物 / 第三方）。
SKIP_PREFIXES: tuple[str, ...] = (
    "archive/",
    "reports/",
    "publish/",
    ".venv/",
    "node_modules/",
)

#: 写调用 -> 路径参数所在的位置实参下标。
#: 例：``json.dump(obj, fp)`` 的文件在第 2 个实参，故为 ``(1,)``。
ARG_WRITE_CALLS: dict[str, tuple[int, ...]] = {
    "save": (0,),  # np.save / torch.save
    "savez": (0,),
    "savez_compressed": (0,),
    "save_npz": (0,),  # scipy.sparse.save_npz
    "savetxt": (0,),
    "to_csv": (0,),
    "to_json": (0,),
    "to_parquet": (0,),
    "dump": (1,),  # json/pickle.dump(obj, fp)
    "write_text": (0,),
    "write_bytes": (0,),
    "copy": (1,),  # shutil.copy(src, dst)
    "copy2": (1,),
    "copyfile": (1,),
    "copytree": (1,),
    "move": (1,),
    "rmtree": (0,),
    "makedirs": (0,),
    "mkdir": (0,),
    "remove": (0,),
    "unlink": (0,),
    "rename": (0, 1),
    "replace": (0, 1),
    "rmdir": (0,),
    "truncate": (0,),
    "touch": (0,),
    "write": (0,),
    # QA-ATK SA-32：本仓真实写调用族（faiss/torch/joblib/h5py/sqlite/PIL）
    "write_index": (1,),  # faiss.write_index(index, path)
    "write_table": (1,),  # pyarrow.parquet.write_table(table, path)
    "File": (0,),  # h5py.File(path, "w")
    "connect": (0,),  # sqlite3.connect(path)
    "memmap": (0,),  # np.memmap(path, mode="w+")
    "make_archive": (0,),  # shutil.make_archive(base_name, ...)
    "unpack_archive": (1,),  # shutil.unpack_archive(archive, extract_dir)
    "extractall": (0,),  # tarfile/zipfile .extractall(path)
    "chdir": (0,),  # SA-17：切到外部目录后写相对路径，等同外部写
}

#: 这些调用的「写目标」只出现在关键字实参里，需按名字取。
KEYWORD_PATH_ARGS: tuple[str, ...] = (
    "file",
    "fname",
    "dst",
    "path",
    "filename",
    "target",
    "base_name",
    "extract_dir",
    "out",
    "output",
    "dest",
)

#: SA-44：动态执行入口。实参引用外部路径即判红，静态分析无法看穿其内容。
DYNAMIC_EXEC_CALLS: frozenset[str] = frozenset({"exec", "eval", "compile"})

#: SA-45：外部进程入口。任一实参引用外部路径即判红。
SUBPROCESS_CALLS: frozenset[str] = frozenset(
    {"run", "call", "check_call", "check_output", "Popen", "system", "popen", "spawn"}
)

#: SA-30/31：以可写 mmap 模式打开 = 原地覆写，没有任何显式写调用。
MMAP_WRITE_MODES: frozenset[str] = frozenset({"r+", "w+", "c", "a"})

#: 返回标量/布尔而非路径的调用，污染到此为止（否则 len(root) 也会被判脏）。
SCALAR_RETURN_CALLS: frozenset[str] = frozenset(
    {
        "len",
        "int",
        "float",
        "bool",
        "sum",
        "min",
        "max",
        "any",
        "all",
        "isinstance",
        "exists",
        "isdir",
        "isfile",
        "islink",
        "getsize",
        "getmtime",
        "getctime",
        "print",
        "count",
        "index",
        "startswith",
        "endswith",
        "find",
        "rfind",
        "split",
        "rsplit",
        "strip",
        "lower",
        "upper",
        "encode",
        "decode",
        "hexdigest",
        "sha256",
        "md5",
        "repr",
    }
)

#: 只能以 ``os.<name>`` / ``shutil.<name>`` 形式出现才算写操作的模糊名。
#: 否则 ``list.remove(x)`` / ``str.replace(a, b)`` 会被误判为文件操作。
MODULE_QUALIFIED_ONLY: frozenset[str] = frozenset(
    {"remove", "unlink", "rename", "replace", "rmdir", "mkdir", "makedirs", "move", "copy"}
)

#: 允许出现在上述模糊名前的模块别名。
FILE_MODULES: frozenset[str] = frozenset({"os", "shutil", "pathlib", "Path", "path"})

#: 接收者型写调用：``<path_expr>.write_text(...)``——查接收者是否污染。
RECEIVER_WRITE_CALLS: frozenset[str] = frozenset(
    {"open", "write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "replace"}
)

#: 这些方法名在 pathlib 与 str/list 上同名，需靠实参数消歧（pathlib 版实参 <= 1）。
AMBIGUOUS_RECEIVER_CALLS: frozenset[str] = frozenset(
    {"replace", "rename", "write", "touch", "mkdir", "unlink", "rmdir"}
)

#: 句柄型写调用：第 N 实参是**已打开的文件句柄**而非路径。
#: 键为函数名，值为句柄所在实参下标（-1 表示接收者本身即句柄）。
HANDLE_WRITE_CALLS: dict[str, tuple[int, ...]] = {
    "dump": (1,),  # json.dump / pickle.dump / joblib.dump
    "save": (0,),  # np.save(handle, arr) 也接受句柄
    "savez": (0,),
    "write": (-1,),  # handle.write(...)
    "writelines": (-1,),
}

#: 纯字符串化、绝不落盘的调用，显式排除（防 json.dumps 之类误报）。
NEVER_WRITE_CALLS: frozenset[str] = frozenset({"dumps", "loads", "load", "read_text", "read_bytes"})


class Finding:
    """一条外部写入点记录。

    Attributes:
        path: 相对仓库根的文件路径（POSIX 分隔符）。
        line: 行号（1 起）。
        text: 该行去除首尾空白后的源码。
        status: ``hit`` 判红 / ``guard`` 已走守卫 / ``comment`` 行内豁免。
        reason: 豁免理由（仅 ``comment`` 状态非空）。
    """

    __slots__ = ("path", "line", "text", "status", "reason")

    def __init__(self, path: str, line: int, text: str, status: str, reason: str = "") -> None:
        self.path: str = path
        self.line: int = line
        self.text: str = text
        self.status: str = status
        self.reason: str = reason

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Finding({self.path}:{self.line} {self.status})"


# ---------------------------------------------------------------- 污染模型
class Taint:
    """单个作用域的污染集合。

    区分多类污染，避免「路径」与「已打开句柄」互相串味：
      - ``paths``：求值结果是外部目录路径的名字/属性。
      - ``handles``：由污染路径 ``open()`` 出来的文件句柄名字。
      - ``funcs``：返回值被污染的本模块函数名。
      - ``dirty_param_funcs``：``{函数名: {被污染的形参名}}``，跨函数传播用。
      - ``safe_paths``：明确判定为仓库内的名字，优先级高于 ``paths``。
    """

    __slots__ = ("paths", "handles", "funcs", "dirty_param_funcs", "safe_paths")

    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.handles: set[str] = set()
        self.funcs: set[str] = set()
        self.dirty_param_funcs: dict[str, set[str]] = {}
        self.safe_paths: set[str] = set()

    def copy(self) -> Taint:
        """返回浅拷贝，用于派生子作用域。"""
        clone = Taint()
        clone.paths = set(self.paths)
        clone.handles = set(self.handles)
        clone.funcs = set(self.funcs)
        clone.dirty_param_funcs = {k: set(v) for k, v in self.dirty_param_funcs.items()}
        clone.safe_paths = set(self.safe_paths)
        return clone


def _call_name(node: ast.AST) -> str:
    """取调用/属性表达式的最末名字，取不到返回空串。"""
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _receiver_module(node: ast.AST) -> str:
    """取 ``os.remove`` 形式中的模块名 ``os``；非该形式返回空串。"""
    if isinstance(node, ast.Call):
        return _receiver_module(node.func)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id
    return ""


def _dotted_name(node: ast.AST) -> str:
    """把 ``a.b.c`` 还原成字符串，失败返回空串。"""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _is_repo_anchor(node: ast.AST) -> bool:
    """表达式是否以当前源文件为基准（含 ``__file__``），即仓库内路径。"""
    return any(isinstance(sub, ast.Name) and sub.id == "__file__" for sub in ast.walk(node))


def _literal_is_external(value: str) -> bool:
    """字面量字符串是否指向外部目录。

    标记词（``global_memory`` / ``global_skills``）须作为「完整路径组件」出现才判红——
    即其后紧跟路径分隔符（``/`` 或 ``\\``）或处于字符串末尾（整段即该目录名）。
    这样可避免把仓库内合法镜像目录 ``global_memory_mirror`` 误判为外部目录。
    """
    lowered = value.replace("\\", "/").lower()
    for marker in EXTERNAL_LITERAL_MARKERS:
        idx = lowered.find(marker)
        while idx >= 0:
            after = lowered[idx + len(marker): idx + len(marker) + 1]
            if after in ("", "/", "\\"):
                return True
            idx = lowered.find(marker, idx + len(marker))
    return False


def expr_tainted(node: ast.AST | None, taint: Taint) -> bool:
    """保守判断表达式是否求值为外部目录路径。

    Args:
        node: 待判定的 AST 表达式节点，``None`` 视为不污染。
        taint: 当前作用域的污染集合。

    Returns:
        True 表示该表达式可能指向外部目录。
    """
    if node is None:
        return False

    # 仓库内锚点优先短路：含 __file__ 的路径一律视为仓库内。
    if _is_repo_anchor(node):
        return False

    if isinstance(node, ast.Call):
        return _call_tainted(node, taint)

    result = _leaf_tainted(node, taint)
    if result is not None:
        return result
    return _compound_tainted(node, taint)


def _leaf_tainted(node: ast.AST, taint: Taint) -> bool | None:
    """叶子节点（常量/名字/属性/下标）的污染判定；不识别该形状返回 None。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and _literal_is_external(node.value)
    if isinstance(node, ast.Name):
        if node.id in taint.safe_paths:
            return False
        return node.id in taint.paths
    if isinstance(node, ast.Attribute):
        return _attr_tainted(node, taint)
    if isinstance(node, ast.Subscript):
        return _subscript_tainted(node, taint)
    return None


def _attr_tainted(node: ast.Attribute, taint: Taint) -> bool:
    """属性链（``a.b.c``）的污染判定。"""
    dotted = _dotted_name(node)
    if dotted and dotted in taint.safe_paths:
        return False
    if dotted and dotted in taint.paths:
        return True
    if node.attr.upper() in EXTERNAL_ENV_VARS:
        return True
    return expr_tainted(node.value, taint) and node.attr not in ("name", "stem", "suffix")


def _subscript_tainted(node: ast.Subscript, taint: Taint) -> bool:
    """下标取值的污染判定（含 SA-20 的 os.environ["X"] 形式）。"""
    base = _dotted_name(node.value)
    if base.endswith("environ"):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value in EXTERNAL_ENV_VARS
        return True  # 键非字面量，保守判污染
    return expr_tainted(node.value, taint)


def _compound_tainted(node: ast.AST, taint: Taint) -> bool:
    """复合容器/表达式节点（dict/海象/f-string/二元/列表/条件）的污染判定。"""
    if isinstance(node, ast.Dict):
        # SA-03：容器中转 paths = {"idx": root + "/emb.npy"}
        return any(expr_tainted(v, taint) for v in node.values)
    if isinstance(node, ast.NamedExpr):
        # SA-09：海象运算符 (p := Path(root) / "x")
        return expr_tainted(node.value, taint)
    if isinstance(node, ast.JoinedStr):
        return _fstring_tainted(node, taint)
    if isinstance(node, ast.BinOp):
        return expr_tainted(node.left, taint) or expr_tainted(node.right, taint)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return any(expr_tainted(elt, taint) for elt in node.elts)
    if isinstance(node, ast.IfExp):
        return expr_tainted(node.body, taint) or expr_tainted(node.orelse, taint)
    return False


def _fstring_tainted(node: ast.JoinedStr, taint: Taint) -> bool:
    """f-string 的污染判定：任一格式化值污染即真，否则看字面量片段。"""
    if any(expr_tainted(v.value, taint) for v in node.values if isinstance(v, ast.FormattedValue)):
        return True
    return any(
        isinstance(v, ast.Constant) and isinstance(v.value, str) and _literal_is_external(v.value)
        for v in node.values
    )


def _call_tainted(node: ast.Call, taint: Taint) -> bool:
    """判断函数调用的返回值是否为外部路径。"""
    name = _call_name(node)

    # os.environ.get("SKILL_CONTENT", ...) / os.getenv(...) —— 污染源
    if name in ("get", "getenv", "environ"):
        return _env_arg_tainted(node, taint)

    # 路径拼接族：任一实参或接收者污染即传播
    if name in (
        "join",
        "abspath",
        "realpath",
        "normpath",
        "expanduser",
        "Path",
        "resolve",
        "joinpath",
    ):
        if any(expr_tainted(a, taint) for a in node.args):
            return True
        return isinstance(node.func, ast.Attribute) and expr_tainted(node.func.value, taint)

    # 本模块内返回污染值的函数
    if name in taint.funcs:
        return True

    # 兜底：任一实参污染即向外传播。
    # 必须有这条——实测 `for fpath in sorted(glob.glob(os.path.join(root,"*.json")))`
    # 会在 sorted() 处断链，导致 audit/fix_collisions.py 的真实写入点整片漏检。
    # 代价是可能过度污染，但对安全门禁而言「宁可多报不可漏报」。
    if name in SCALAR_RETURN_CALLS:
        return False
    return any(expr_tainted(a, taint) for a in node.args)


def _env_arg_tainted(node: ast.Call, taint: Taint) -> bool:
    """os.environ.get / os.getenv 等调用的环境变量实参污染判定。"""
    for arg in node.args:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and arg.value in EXTERNAL_ENV_VARS
        ):
            return True
    for arg in node.args[1:]:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and _literal_is_external(arg.value)
        ):
            return True
    return False


def _handle_tainted(node: ast.AST | None, taint: Taint) -> bool:
    """判断表达式是否为「由外部路径打开的文件句柄」。"""
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in taint.handles
    if isinstance(node, ast.Attribute):
        dotted = _dotted_name(node)
        return bool(dotted) and dotted in taint.handles
    if isinstance(node, ast.Call) and _call_name(node) == "open":
        # 内建 open(path, ...) 的路径在第 1 实参；接收者式 .open(...) 的路径是接收者本身。
        if isinstance(node.func, ast.Attribute) and expr_tainted(node.func.value, taint):
            return True
        return bool(node.args) and expr_tainted(node.args[0], taint)
    return False


# ---------------------------------------------------------------- 污染传播
def _record_target(target: ast.AST, value: ast.AST, taint: Taint) -> None:
    """把赋值语句左侧登记进污染集合（或安全集合）。"""
    names: list[str] = []
    if isinstance(target, ast.Name):
        names.append(target.id)
    elif isinstance(target, ast.Attribute):
        dotted = _dotted_name(target)
        if dotted:
            names.append(dotted)
    elif isinstance(target, ast.Tuple | ast.List):
        for elt in target.elts:
            _record_target(elt, value, taint)
        return
    if not names:
        return

    if isinstance(value, ast.Call) and _call_name(value) == "open":
        _record_open_target(names, value, taint)
        return

    _record_tainted_value(names, value, taint)


def _record_open_target(names: list[str], value: ast.Call, taint: Taint) -> None:
    """登记 open(...) 赋值：结果按句柄污染（或清洗旧标记）处理。"""
    # 句柄污染，不是路径污染：后续 json.dump(obj, handle) 才据此判定。
    # 内建 open(path, ...) 看第 1 实参；接收者式 Path.open(...) 看接收者
    # （其第 1 位置实参是 mode 而非路径，不能当路径判）。
    if isinstance(value.func, ast.Attribute) and expr_tainted(value.func.value, taint):
        dirty_handle = True
    else:
        dirty_handle = bool(value.args) and expr_tainted(value.args[0], taint)
    for n in names:
        if dirty_handle:
            taint.handles.add(n)
        else:
            # 干净重绑定必须清洗残留脏标记，否则同名短句柄（f/fh/handle）
            # 在「先读外部、后写仓库内」的脚本里会把干净写入点误判为外部写。
            taint.handles.discard(n)
        # open() 返回的是句柄而非路径，无论脏净都不应留在路径污染集合里。
        taint.paths.discard(n)


def _record_tainted_value(names: list[str], value: ast.AST, taint: Taint) -> None:
    """登记普通赋值：外部路径进入污染集合，仓库内锚点进入安全集合。"""
    if expr_tainted(value, taint):
        for n in names:
            taint.paths.add(n)
            taint.safe_paths.discard(n)
    elif _is_repo_anchor(value):
        for n in names:
            taint.safe_paths.add(n)
            taint.paths.discard(n)


def _collect_argparse(node: ast.AST, taint: Taint) -> None:
    """识别 add_argument 的污染 default，并污染对应的 args.<dest>。"""
    if not isinstance(node, ast.Call) or _call_name(node) != "add_argument":
        return
    dest = ""
    for arg in node.args:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and arg.value.startswith("--")
        ):
            dest = arg.value[2:].replace("-", "_")
            break
    dirty = False
    for kw in node.keywords:
        if kw.arg == "default" and expr_tainted(kw.value, taint):
            dirty = True
        if (
            kw.arg == "dest"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            dest = kw.value.value
    if dirty and dest:
        taint.paths.add(dest)
        taint.paths.add("args." + dest)


def _sweep_scope(body: Sequence[ast.stmt], taint: Taint) -> None:
    """在单个作用域内做一趟污染扫描（不下钻到嵌套函数/类定义）。"""
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue  # 嵌套定义单独处理，避免局部名泄漏到兄弟作用域

        if isinstance(stmt, ast.Assign | ast.AnnAssign | ast.AugAssign):
            _sweep_assignment_targets(stmt, taint)
            continue
        if isinstance(stmt, ast.Expr):
            _collect_argparse(stmt.value, taint)
            continue
        if isinstance(stmt, ast.With | ast.AsyncWith):
            for item in stmt.items:
                if item.optional_vars is not None:
                    _record_target(item.optional_vars, item.context_expr, taint)
        elif isinstance(stmt, ast.For | ast.AsyncFor):
            _record_target(stmt.target, stmt.iter, taint)
        _sweep_container(stmt, taint)


def _sweep_assignment_targets(
    stmt: ast.Assign | ast.AnnAssign | ast.AugAssign, taint: Taint
) -> None:
    """Assign / AnnAssign / AugAssign 的左侧污染登记。"""
    if isinstance(stmt, ast.Assign):
        for tgt in stmt.targets:
            _record_target(tgt, stmt.value, taint)
        return
    if stmt.value is not None and stmt.target is not None:
        _record_target(stmt.target, stmt.value, taint)


def _sweep_container(stmt: ast.stmt, taint: Taint) -> None:
    """递归下钻到复合语句的嵌套子块（with/for/if/while/try 共用）。"""
    for attr in ("body", "orelse", "finalbody"):
        _sweep_scope(getattr(stmt, attr, []), taint)
    if isinstance(stmt, ast.Try):
        for handler in stmt.handlers:
            _sweep_scope(handler.body, taint)


def _scope_taint_for(func: ast.AST, module_taint: Taint) -> Taint:
    """为函数体派生隔离的作用域污染集合。

    模块级污染向内继承（全局变量确实可见），但本函数内产生的局部污染只留在
    副本里，不会回流污染兄弟函数——这是消除短名（f / fh / p）串味的关键。

    Args:
        func: 函数定义节点。
        module_taint: 模块级污染集合。

    Returns:
        该函数作用域专属的 Taint 副本。
    """
    local = module_taint.copy()
    args = getattr(func, "args", None)
    if args is not None:
        all_pos = list(getattr(args, "posonlyargs", [])) + list(args.args)
        defaults = list(args.defaults)
        if defaults:
            for arg_node, default in zip(all_pos[-len(defaults) :], defaults, strict=False):
                if expr_tainted(default, module_taint):
                    local.paths.add(arg_node.arg)
        for kwarg, kwdefault in zip(args.kwonlyargs, args.kw_defaults, strict=False):
            if kwdefault is not None and expr_tainted(kwdefault, module_taint):
                local.paths.add(kwarg.arg)
        # 跨函数调用链登记的污染形参
        for pname in module_taint.dirty_param_funcs.get(getattr(func, "name", ""), set()):
            local.paths.add(pname)

    body = getattr(func, "body", [])
    for _ in range(10):
        before = (len(local.paths), len(local.handles), len(local.safe_paths))
        _sweep_scope(body, local)
        after = (len(local.paths), len(local.handles), len(local.safe_paths))
        if before == after:
            break
    return local


def _apply_dirty_params(
    holder: ast.AST,
    funcs: dict[str, ast.AST],
    scope: Taint,
    module_taint: Taint,
) -> bool:
    """扫描 holder 内对本模块函数的调用，登记被污染的形参名。

    Returns:
        本轮是否有新的污染形参被登记。
    """
    changed = False
    for sub in ast.walk(holder):
        if not isinstance(sub, ast.Call):
            continue
        callee = _call_name(sub)
        target = funcs.get(callee)
        if target is None:
            continue
        targs = getattr(target, "args", None)
        if targs is None:
            continue
        params = [a.arg for a in list(getattr(targs, "posonlyargs", [])) + list(targs.args)]
        bucket = module_taint.dirty_param_funcs.setdefault(callee, set())
        changed |= _register_positional(sub, params, bucket, scope)
        changed |= _register_keyword(sub, params, bucket, scope)
    return changed


def _register_positional(
    sub: ast.Call, params: Sequence[str], bucket: set[str], scope: Taint
) -> bool:
    """登记位置实参中被污染的形参名。"""
    changed = False
    for idx, actual in enumerate(sub.args):
        if idx < len(params) and expr_tainted(actual, scope) and params[idx] not in bucket:
            bucket.add(params[idx])
            changed = True
    return changed


def _register_keyword(sub: ast.Call, params: Sequence[str], bucket: set[str], scope: Taint) -> bool:
    """登记关键字实参中被污染的形参名。"""
    changed = False
    for kw in sub.keywords:
        if kw.arg and kw.arg in params and expr_tainted(kw.value, scope) and kw.arg not in bucket:
            bucket.add(kw.arg)
            changed = True
    return changed


def _collect_returning_funcs(tree: ast.Module, taint: Taint) -> None:
    """标记返回外部路径的本模块函数，供调用点判定。"""
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        local = _scope_taint_for(node, taint)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and expr_tainted(sub.value, local):
                taint.funcs.add(node.name)
                break


def build_module_taint(tree: ast.Module) -> Taint:
    """构建模块级污染集合并跑到不动点（含跨函数形参传播）。

    Args:
        tree: 已解析的模块 AST。

    Returns:
        模块级 Taint。
    """
    taint = Taint()
    funcs: dict[str, ast.AST] = {
        n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    top_level = [
        s
        for s in tree.body
        if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    top_module = ast.Module(body=top_level, type_ignores=[])

    for _ in range(20):
        snapshot = (
            len(taint.paths),
            len(taint.handles),
            len(taint.funcs),
            len(taint.safe_paths),
            sum(len(v) for v in taint.dirty_param_funcs.values()),
        )
        _sweep_scope(tree.body, taint)
        _collect_returning_funcs(tree, taint)
        _apply_dirty_params(top_module, funcs, taint, taint)
        for fn in funcs.values():
            scope = _scope_taint_for(fn, taint)
            _apply_dirty_params(fn, funcs, scope, taint)
        current = (
            len(taint.paths),
            len(taint.handles),
            len(taint.funcs),
            len(taint.safe_paths),
            sum(len(v) for v in taint.dirty_param_funcs.values()),
        )
        if snapshot == current:
            break
    return taint


# ---------------------------------------------------------------- 写入点判定
def _open_mode_position(node: ast.Call) -> int:
    """返回 open 调用模式实参的位置。

    内建 ``open(path, mode)`` 的模式在第 1 位置实参；接收者式
    ``Path.open(mode)`` 的模式在第 0 位置实参；但 ``tarfile.open(name, mode)``
    等模块型属性调用与内建 open 同构（模式在第 1 位置实参）。判定规则：
    func 为普通 Name（内建 open）→ 1；func 为 Attribute 且接收者是模块名
    （tarfile/zipfile/gzip/bz2/lzma 等）→ 1；其余 Attribute 接收者
    （Path 实例等）→ 0。
    """
    if not isinstance(node.func, ast.Attribute):
        return 1
    if isinstance(node.func.value, ast.Name) and node.func.value.id in (
        "tarfile",
        "zipfile",
        "gzip",
        "bz2",
        "lzma",
    ):
        return 1
    return 0


def _open_mode_is_write(node: ast.Call) -> bool:
    """判断 open(...) 的模式是否含写语义；模式缺省（只读）返回 False。

    兼容两种形态：内建 ``open(path, mode)`` 与接收者式 ``Path.open(mode)``
    （后者模式在第 0 位置实参，关键字 ``mode=`` 两种形态通用）。
    """
    mode = ""
    pos = _open_mode_position(node)
    mode_arg = node.args[pos] if pos < len(node.args) else None
    if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
        mode = mode_arg.value
    for kw in node.keywords:
        if (
            kw.arg == "mode"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            mode = kw.value.value
    if not mode:
        # SA-26：mode 由变量/表达式给出时无法静态确定，保守视为可能写。
        # 只有「显式写着字面量 'r' / 'rb'」才敢判定为只读。
        has_positional_mode = len(node.args) > pos
        has_kw_mode = any(kw.arg == "mode" for kw in node.keywords)
        return has_positional_mode or has_kw_mode
    return any(ch in mode for ch in ("w", "a", "x", "+"))


def _mmap_write_mode(node: ast.Call) -> bool:
    """SA-30/31：``np.load(p, mmap_mode="r+")`` / ``np.memmap(p, mode="w+")``
    没有任何显式写调用，却能原地覆写。此处按 mode 关键字判定。
    """
    for kw in node.keywords:
        if kw.arg in ("mmap_mode", "mode"):
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value in MMAP_WRITE_MODES
            return True  # 非字面量，保守
    return False


def _is_write_call(node: ast.Call, taint: Taint) -> bool:
    """判断一个调用是否为「写入外部目录」。

    三条通路，命中任一即为真：
      1. 路径型：已知写函数的指定位置实参指向外部路径。
      2. 接收者型：``<外部路径>.write_text(...)`` / 以写模式打开外部路径的调用。
      3. 句柄型：``json.dump(obj, <脏句柄>)``、``<脏句柄>.write(...)``。

    Args:
        node: 调用节点。
        taint: 当前作用域污染集合。

    Returns:
        是否判定为外部写入。
    """
    name = _call_name(node)
    if not name:
        return False

    hit = _dangerous_call_hits(node, taint)
    if hit is not None:
        return hit

    if not _module_qualified_ok(node, taint, _receiver_module(node)):
        return False

    if _handle_write_hits(node, taint):
        return True
    if _path_write_hits(node, taint):
        return True
    return _receiver_write_hits(node, taint)


def _dangerous_call_hits(node: ast.Call, taint: Taint) -> bool | None:
    """SA-44/45/30/31 与只读白名单的判定；None 表示不属于这些类别。"""
    name = _call_name(node)

    # SA-44：exec/eval/compile 内容对 AST 不可见，实参沾外部路径即判红。
    # 限定为「裸调用」（ast.Name）：内建 exec/eval/compile 才有任意执行能力。
    # 带模块限定的同名方法（re.compile / 自定义 obj.eval）语义完全不同，
    # 一律纳入会造成 re.compile(...) 这类纯正则编译被误判为写操作。
    if name in DYNAMIC_EXEC_CALLS and isinstance(node.func, ast.Name):
        return any(expr_tainted(a, taint) for a in node.args)

    # SA-45：subprocess / os.system / os.popen 把写操作外包给子进程。
    if name in SUBPROCESS_CALLS:
        if any(expr_tainted(a, taint) for a in node.args):
            return True
        return any(expr_tainted(kw.value, taint) for kw in node.keywords)

    # SA-30/31：np.load(..., mmap_mode="r+") 是读函数名，却能原地覆写。
    if name in ("load", "memmap"):
        return bool(node.args) and expr_tainted(node.args[0], taint) and _mmap_write_mode(node)

    if name in NEVER_WRITE_CALLS:
        return False
    return None


def _module_qualified_ok(node: ast.Call, taint: Taint, module_alias: str) -> bool:
    """模糊名保护：remove/replace/rename 等必须是 os.xxx / shutil.xxx 或 Path 对象方法。"""
    if _call_name(node) not in MODULE_QUALIFIED_ONLY:
        return True
    receiver_is_module = module_alias in FILE_MODULES
    receiver_is_path = False
    if isinstance(node.func, ast.Attribute):
        receiver_is_path = expr_tainted(node.func.value, taint)
    return receiver_is_module or receiver_is_path


def _handle_write_hits(node: ast.Call, taint: Taint) -> bool:
    """通路 3：句柄型写调用（json.dump(obj, 脏句柄) / 脏句柄.write(...)）。"""
    handle_slots = HANDLE_WRITE_CALLS.get(_call_name(node))
    if handle_slots is None:
        return False
    for slot in handle_slots:
        if slot == -1:
            if isinstance(node.func, ast.Attribute) and _handle_tainted(node.func.value, taint):
                return True
        elif slot < len(node.args) and _handle_tainted(node.args[slot], taint):
            return True
    return False


def _path_write_hits(node: ast.Call, taint: Taint) -> bool:
    """通路 1：路径型写调用（np.save 第 1 参、shutil.copy 第 2 参等）。"""
    slots = ARG_WRITE_CALLS.get(_call_name(node))
    if slots is None:
        return False
    for slot in slots:
        if slot < len(node.args) and expr_tainted(node.args[slot], taint):
            return True
    for kw in node.keywords:
        if kw.arg in KEYWORD_PATH_ARGS and expr_tainted(kw.value, taint):
            return True
    # SA-37：实参里有 *args 展开，无法定位路径位次，保守判红
    return any(isinstance(a, ast.Starred) for a in node.args)


def _receiver_write_hits(node: ast.Call, taint: Taint) -> bool:
    """通路 2：接收者型写调用（<外部路径>.write_text / 以写模式打开外部路径）。"""
    name = _call_name(node)
    if name not in RECEIVER_WRITE_CALLS:
        return False
    if name == "open":
        if node.args and expr_tainted(node.args[0], taint):
            return _open_mode_is_write(node)
        if isinstance(node.func, ast.Attribute) and expr_tainted(node.func.value, taint):
            return _open_mode_is_write(node)
        return False
    # 实参数区分 pathlib 与 str 方法：
    #   Path(p).replace(q) / Path(p).unlink()  -> 实参 <= 1，是文件操作
    #   s.replace(old, new)                    -> 实参 >= 2，是字符串操作
    # 不加这条，SKILL_CONTENT.replace("a","b") 会被误判为「重命名共享目录」。
    if name in AMBIGUOUS_RECEIVER_CALLS and len(node.args) > 1:
        return False
    return isinstance(node.func, ast.Attribute) and expr_tainted(node.func.value, taint)


# ---------------------------------------------------------------- 分析入口
def _exempt_reason(line_text: str) -> str | None:
    """提取行内豁免理由；无标记返回 None，理由为空返回空串。"""
    idx = line_text.find(EXEMPT_TOKEN)
    if idx < 0:
        return None
    return line_text[idx + len(EXEMPT_TOKEN) :].strip()


def _guard_imported(tree: ast.Module) -> bool:
    """模块是否导入了运行时守卫。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and GUARD_MODULE in node.module:
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if GUARD_MODULE in alias.name:
                    return True
    return False


def _guard_called_in(scope_node: ast.AST) -> bool:
    """该函数体（或模块顶层）内是否调用了 require_backup_and_release。"""
    for sub in ast.walk(scope_node):
        if isinstance(sub, ast.Call) and _call_name(sub) == GUARD_CALL:
            return True
    return False


def analyze_source(source: str, rel_path: str) -> list[Finding]:
    """分析单份源码，返回全部外部写入点记录。

    Args:
        source: Python 源码文本。
        rel_path: 用于展示的相对路径。

    Returns:
        Finding 列表。解析失败时返回一条 status=hit 的记录（fail-closed）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding(rel_path, exc.lineno or 1, f"<语法解析失败: {exc.msg}>", "hit")]

    lines = source.splitlines()
    module_taint = build_module_taint(tree)
    guard_ready = _guard_imported(tree)
    scopes = _collect_scopes(tree, module_taint)

    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()

    for scope_node, scope_taint in scopes:
        guarded_scope = guard_ready and _guard_called_in(scope_node)
        for sub in ast.walk(scope_node):
            if not isinstance(sub, ast.Call):
                continue
            if not _is_write_call(sub, scope_taint):
                continue
            key = (sub.lineno, sub.col_offset)
            if key in seen:
                continue
            seen.add(key)

            line_no = sub.lineno
            text = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
            prev_text = lines[line_no - 2].strip() if line_no - 2 >= 0 else ""
            findings.append(_classify_finding(text, prev_text, guarded_scope, rel_path, line_no))

    findings.sort(key=lambda f: f.line)
    return findings


def _collect_scopes(tree: ast.Module, module_taint: Taint) -> list[tuple[ast.AST, Taint]]:
    """建立「作用域节点 -> 该作用域污染集合」映射。"""
    top_level = [
        s
        for s in tree.body
        if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    scopes: list[tuple[ast.AST, Taint]] = [
        (ast.Module(body=top_level, type_ignores=[]), module_taint)
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            scopes.append((node, _scope_taint_for(node, module_taint)))
    return scopes


def _classify_finding(
    text: str, prev_text: str, guarded: bool, rel_path: str, line_no: int
) -> Finding:
    """按豁免标记/守卫状态把一行调用归为 comment/guard/hit。"""
    reason = _exempt_reason(text)
    if reason is None and prev_text.startswith("#"):
        reason = _exempt_reason(prev_text)
    if reason:
        return Finding(rel_path, line_no, text, "comment", reason)
    if guarded:
        return Finding(rel_path, line_no, text, "guard")
    # 理由为空的豁免标记 == 无效豁免，仍判红
    return Finding(rel_path, line_no, text, "hit")


def analyze_file(path: str, rel_path: str = "") -> list[Finding]:
    """读取并分析单个文件；读取失败按 fail-closed 判红。"""
    shown = rel_path or path.replace("\\", "/")
    try:
        with Path(path).open(encoding="utf-8") as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(shown, 1, f"<读取失败: {exc}>", "hit")]
    return analyze_source(source, shown)


def _should_skip(rel_path: str) -> bool:
    """是否属于免扫描目录。"""
    normalized = rel_path.replace("\\", "/").lstrip("./")
    return any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES)


def analyze_paths(paths: Iterable[str]) -> list[Finding]:
    """批量分析路径列表，自动跳过免扫描目录与不存在的文件。"""
    findings: list[Finding] = []
    for raw in paths:
        rel = raw.strip().replace("\\", "/")
        if not rel or not rel.endswith(".py"):
            continue
        if _should_skip(rel):
            continue
        if not Path(rel).is_file():
            continue
        findings.extend(analyze_file(rel, rel))
    return findings



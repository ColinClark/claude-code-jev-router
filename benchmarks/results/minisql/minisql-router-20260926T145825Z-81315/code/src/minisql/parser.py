"""Recursive-descent parser producing a small tuple-based AST.

Expression nodes:
    ("lit", value)
    ("col", table_or_None, name)
    ("colidx", index, affinity)            -- produced internally for `*` expansion
    ("neg", expr) / ("pos", expr)
    ("binop", op, left, right)             -- + - * / % ||
    ("cmp", op, left, right)               -- = != < <= > >=
    ("and", left, right) / ("or", left, right) / ("not", expr)
    ("is", left, right, negated)
    ("in", expr, [items], negated)
    ("between", expr, low, high, negated)
    ("like", expr, pattern, escape_or_None, negated)
    ("func", name_lower, [args], distinct, star)
    ("case", base_or_None, [(when, then)], else_or_None)
"""

from dataclasses import dataclass, field

from minisql.errors import SQLError
from minisql.lexer import Token, tokenize

INT_MAX = (1 << 63) - 1


@dataclass
class TableRef:
    name: str
    alias: str | None


@dataclass
class Join:
    kind: str  # "INNER" or "LEFT"
    table: TableRef
    on: tuple | None


@dataclass
class OrderTerm:
    expr: tuple
    desc: bool
    nulls_first: bool | None = None


@dataclass
class Select:
    distinct: bool
    items: list  # (expr, alias) or ("*", table_or_None)
    table: TableRef | None
    joins: list[Join] = field(default_factory=list)
    where: tuple | None = None
    group_by: list = field(default_factory=list)
    having: tuple | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
    limit: tuple | None = None
    offset: tuple | None = None


@dataclass
class CreateTable:
    name: str
    columns: list[tuple[str, str]]
    if_not_exists: bool


@dataclass
class DropTable:
    name: str
    if_exists: bool


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[tuple]] | None
    select: Select | None


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, tuple]]
    where: tuple | None


@dataclass
class Delete:
    table: str
    where: tuple | None


def parse(sql: str):
    return Parser(sql).parse_statement()


def parse_number(text: str):
    if not any(c in text for c in ".eE"):
        value = int(text)
        return value if value <= INT_MAX else float(text)
    return float(text)


class Parser:
    def __init__(self, sql: str):
        self.tokens = tokenize(sql)
        self.pos = 0

    # -- token helpers -------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, tok: Token | None = None):
        tok = tok or self.peek()
        if tok.kind == "eof":
            return SQLError("incomplete input")
        return SQLError(f'near "{tok.value}": syntax error')

    def at_kw(self, *kws: str) -> bool:
        tok = self.peek()
        return tok.kind == "kw" and tok.value in kws

    def accept_kw(self, kw: str) -> bool:
        if self.at_kw(kw):
            self.advance()
            return True
        return False

    def expect_kw(self, kw: str) -> None:
        if not self.accept_kw(kw):
            raise self.error()

    def at_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok.kind == "op" and tok.value in ops

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def ident(self) -> str:
        tok = self.peek()
        if tok.kind != "id":
            raise self.error()
        self.advance()
        return tok.value

    # -- statements ----------------------------------------------------
    def parse_statement(self):
        if self.at_kw("SELECT"):
            stmt = self.parse_select()
        elif self.at_kw("CREATE"):
            stmt = self.parse_create()
        elif self.at_kw("DROP"):
            stmt = self.parse_drop()
        elif self.at_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.at_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.at_kw("DELETE"):
            stmt = self.parse_delete()
        else:
            raise self.error()
        self.accept_op(";")
        if self.peek().kind != "eof":
            raise self.error()
        return stmt

    def parse_create(self) -> CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.ident()
        self.expect_op("(")
        columns = []
        while True:
            col = self.ident()
            type_words = []
            while self.peek().kind == "id":
                type_words.append(self.advance().value)
            if type_words and self.accept_op("("):
                self.parse_signed_number()
                if self.accept_op(","):
                    self.parse_signed_number()
                self.expect_op(")")
            columns.append((col, " ".join(type_words)))
            if self.accept_op(")"):
                break
            self.expect_op(",")
        return CreateTable(name, columns, if_not_exists)

    def parse_signed_number(self) -> None:
        if not self.accept_op("-"):
            self.accept_op("+")
        if self.peek().kind != "num":
            raise self.error()
        self.advance()

    def parse_drop(self) -> DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return DropTable(self.ident(), if_exists)

    def parse_insert(self) -> Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.ident()
        columns = None
        if self.accept_op("("):
            columns = [self.ident()]
            while self.accept_op(","):
                columns.append(self.ident())
            self.expect_op(")")
        if self.at_kw("SELECT"):
            return Insert(table, columns, None, self.parse_select())
        self.expect_kw("VALUES")
        rows = []
        while True:
            self.expect_op("(")
            rows.append(self.parse_expr_list())
            self.expect_op(")")
            if not self.accept_op(","):
                break
        return Insert(table, columns, rows, None)

    def parse_update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.ident()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.ident()
            if not (self.accept_op("=") or self.accept_op("==")):
                raise self.error()
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Update(table, assignments, where)

    def parse_delete(self) -> Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.ident()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Delete(table, where)

    def parse_select(self) -> Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        sel = Select(distinct, items, None)
        if self.accept_kw("FROM"):
            sel.table = self.parse_table_ref()
            sel.joins = self.parse_joins()
        if self.accept_kw("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            sel.group_by = self.parse_expr_list()
        if self.accept_kw("HAVING"):
            sel.having = self.parse_expr()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            sel.order_by = [self.parse_order_term()]
            while self.accept_op(","):
                sel.order_by.append(self.parse_order_term())
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.limit, sel.offset = first, self.parse_expr()
            elif self.accept_op(","):
                sel.offset, sel.limit = first, self.parse_expr()
            else:
                sel.limit = first
        return sel

    def parse_select_item(self):
        if self.accept_op("*"):
            return ("*", None)
        tok = self.peek()
        if tok.kind == "id" and self.peek(1) == Token("op", ".", self.peek(1).pos) and (
            self.peek(2).kind == "op" and self.peek(2).value == "*"
        ):
            self.pos += 3
            return ("*", tok.value)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            tok = self.peek()
            if tok.kind not in ("id", "str"):
                raise self.error()
            alias = self.advance().value
        elif self.peek().kind == "id":
            alias = self.advance().value
        return (expr, alias)

    def parse_table_ref(self) -> TableRef:
        name = self.ident()
        alias = None
        if self.accept_kw("AS"):
            alias = self.ident()
        elif self.peek().kind == "id":
            alias = self.advance().value
        return TableRef(name, alias)

    def parse_joins(self) -> list[Join]:
        joins = []
        while True:
            if self.accept_op(","):
                joins.append(Join("INNER", self.parse_table_ref(), None))
                continue
            if self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                kind = "LEFT"
            elif self.accept_kw("INNER") or self.accept_kw("CROSS"):
                kind = "INNER"
            elif self.at_kw("JOIN"):
                kind = "INNER"
            elif self.at_kw("RIGHT", "FULL", "NATURAL"):
                raise SQLError(f"unsupported join type: {self.peek().value}")
            else:
                return joins
            self.expect_kw("JOIN")
            ref = self.parse_table_ref()
            on = self.parse_expr() if self.accept_kw("ON") else None
            if self.at_kw("USING"):
                raise SQLError("USING is not supported")
            joins.append(Join(kind, ref, on))

    def parse_order_term(self) -> OrderTerm:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        tok = self.peek()
        if tok.kind == "id" and tok.value.upper() == "NULLS":
            self.advance()
            which = self.ident().upper()
            if which not in ("FIRST", "LAST"):
                raise self.error()
            nulls_first = which == "FIRST"
        return OrderTerm(expr, desc, nulls_first)

    # -- expressions ---------------------------------------------------
    def parse_expr_list(self) -> list:
        items = [self.parse_expr()]
        while self.accept_op(","):
            items.append(self.parse_expr())
        return items

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = ("or", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = ("and", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_kw("NOT"):
            return ("not", self.parse_not())
        return self.parse_equality()

    def parse_equality(self):
        left = self.parse_comparison()
        while True:
            if self.at_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ("cmp", op, left, self.parse_comparison())
                continue
            if self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                left = ("is", left, self.parse_comparison(), negated)
                continue
            if self.accept_kw("ISNULL"):
                left = ("is", left, ("lit", None), False)
                continue
            if self.accept_kw("NOTNULL"):
                left = ("is", left, ("lit", None), True)
                continue
            negated = False
            if self.at_kw("NOT"):
                nxt = self.peek(1)
                if nxt.kind == "kw" and nxt.value == "NULL":
                    self.pos += 2
                    left = ("is", left, ("lit", None), True)
                    continue
                if not (nxt.kind == "kw" and nxt.value in ("IN", "LIKE", "BETWEEN")):
                    return left
                self.advance()
                negated = True
            if self.accept_kw("IN"):
                self.expect_op("(")
                if self.at_kw("SELECT"):
                    raise SQLError("subqueries are not supported")
                items = [] if self.at_op(")") else self.parse_expr_list()
                self.expect_op(")")
                left = ("in", left, items, negated)
            elif self.accept_kw("LIKE"):
                pattern = self.parse_comparison()
                escape = self.parse_comparison() if self.accept_kw("ESCAPE") else None
                left = ("like", left, pattern, escape, negated)
            elif self.accept_kw("BETWEEN"):
                low = self.parse_comparison()
                self.expect_kw("AND")
                high = self.parse_comparison()
                left = ("between", left, low, high, negated)
            else:
                return left

    def parse_comparison(self):
        left = self.parse_additive()
        while self.at_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = ("cmp", op, left, self.parse_additive())
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = self.advance().value
            left = ("binop", op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_concat()
        while self.at_op("*", "/", "%"):
            op = self.advance().value
            left = ("binop", op, left, self.parse_concat())
        return left

    def parse_concat(self):
        left = self.parse_unary()
        while self.accept_op("||"):
            left = ("binop", "||", left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.accept_op("-"):
            tok = self.peek()
            if tok.kind == "num" and tok.value == str(INT_MAX + 1):
                self.advance()
                return ("lit", -(INT_MAX + 1))
            return ("neg", self.parse_unary())
        if self.accept_op("+"):
            return ("pos", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "num":
            self.advance()
            return ("lit", parse_number(tok.value))
        if tok.kind == "str":
            self.advance()
            return ("lit", tok.value)
        if tok.kind == "kw":
            if tok.value == "NULL":
                self.advance()
                return ("lit", None)
            if tok.value == "CASE":
                return self.parse_case()
            raise self.error()
        if tok.kind == "op" and tok.value == "(":
            self.advance()
            if self.at_kw("SELECT"):
                raise SQLError("subqueries are not supported")
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind == "id":
            self.advance()
            if self.accept_op("("):
                return self.parse_call(tok.value.lower())
            if self.accept_op("."):
                return ("col", tok.value, self.ident())
            return ("col", None, tok.value)
        raise self.error()

    def parse_call(self, name: str):
        if self.accept_op("*"):
            self.expect_op(")")
            return ("func", name, [], False, True)
        distinct = self.accept_kw("DISTINCT")
        args = [] if self.at_op(")") else self.parse_expr_list()
        self.expect_op(")")
        return ("func", name, args, distinct, False)

    def parse_case(self):
        self.expect_kw("CASE")
        base = None if self.at_kw("WHEN") else self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        default = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return ("case", base, whens, default)

"""Recursive-descent SQL parser producing a small AST."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import SQLError
from .tokenizer import Token, tokenize
from .values import INT_MAX

# ---------------------------------------------------------------- expressions


@dataclass(eq=False)
class Literal:
    value: object


@dataclass(eq=False)
class Column:
    table: str | None
    name: str


@dataclass(eq=False)
class Unary:
    op: str  # '-', '+', 'NOT'
    operand: object


@dataclass(eq=False)
class Binary:
    op: str
    left: object
    right: object


@dataclass(eq=False)
class IsNull:
    operand: object
    negated: bool


@dataclass(eq=False)
class InList:
    operand: object
    items: list
    negated: bool


@dataclass(eq=False)
class Between:
    operand: object
    low: object
    high: object
    negated: bool


@dataclass(eq=False)
class Like:
    operand: object
    pattern: object
    negated: bool


@dataclass(eq=False)
class Func:
    name: str  # upper-case
    args: list
    distinct: bool = False
    star: bool = False


@dataclass(eq=False)
class Case:
    operand: object | None
    whens: list  # [(cond, result)]
    else_: object | None


# ----------------------------------------------------------------- statements


@dataclass
class CreateTable:
    name: str
    columns: list  # [(name, type_name)]
    if_not_exists: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False


@dataclass
class Insert:
    table: str
    columns: list | None
    rows: list


@dataclass
class Update:
    table: str
    assignments: list  # [(col, expr)]
    where: object | None


@dataclass
class Delete:
    table: str
    where: object | None


@dataclass
class SelectItem:
    expr: object | None  # None means star
    alias: str | None = None
    star_table: str | None = None


@dataclass
class FromItem:
    table: str
    alias: str
    join: str  # 'FIRST', 'INNER', 'LEFT'
    on: object | None = None


@dataclass
class Select:
    distinct: bool
    items: list
    from_items: list = field(default_factory=list)
    where: object | None = None
    group_by: list = field(default_factory=list)
    having: object | None = None
    order_by: list = field(default_factory=list)  # [(expr, desc)]
    limit: object | None = None
    offset: object | None = None


AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"}


class Parser:
    def __init__(self, sql: str):
        self.tokens = tokenize(sql)
        self.i = 0

    # -------------------------------------------------------------- helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.tokens[min(self.i + k, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def is_kw(self, *words: str) -> bool:
        return self.tok.kind == "KW" and self.tok.value in words

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.value in ops

    def accept_kw(self, *words: str) -> bool:
        if self.is_kw(*words):
            self.advance()
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.is_op(op):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            self.error(f"expected {word}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            self.error(f"expected '{op}'")

    def error(self, msg: str):
        t = self.tok
        near = "end of input" if t.kind == "EOF" else repr(t.value)
        raise SQLError(f"syntax error near {near}: {msg}")

    def ident(self) -> str:
        if self.tok.kind == "ID":
            return self.advance().value
        self.error("expected identifier")

    # ------------------------------------------------------------ statements
    def parse_statement(self):
        if self.is_kw("SELECT"):
            stmt = self.parse_select()
        elif self.is_kw("CREATE"):
            stmt = self.parse_create()
        elif self.is_kw("DROP"):
            stmt = self.parse_drop()
        elif self.is_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.is_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.is_kw("DELETE"):
            stmt = self.parse_delete()
        else:
            self.error("expected a statement")
        while self.accept_op(";"):
            pass
        if self.tok.kind != "EOF":
            self.error("unexpected trailing input")
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
            while self.tok.kind == "ID":
                type_words.append(self.advance().value)
            if self.accept_op("("):  # e.g. VARCHAR(10)
                while not self.accept_op(")"):
                    if self.tok.kind == "EOF":
                        self.error("unterminated type")
                    self.advance()
            columns.append((col, " ".join(type_words)))
            if self.accept_op(")"):
                break
            self.expect_op(",")
        return CreateTable(name, columns, if_not_exists)

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
        self.expect_kw("VALUES")
        rows = []
        while True:
            self.expect_op("(")
            row = [self.parse_expr()]
            while self.accept_op(","):
                row.append(self.parse_expr())
            self.expect_op(")")
            rows.append(row)
            if not self.accept_op(","):
                break
        return Insert(table, columns, rows)

    def parse_update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.ident()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.ident()
            self.expect_op("=")
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
        sel = Select(distinct, items)
        if self.accept_kw("FROM"):
            sel.from_items = self.parse_from()
        if self.accept_kw("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            sel.group_by = [self.parse_expr()]
            while self.accept_op(","):
                sel.group_by.append(self.parse_expr())
        if self.accept_kw("HAVING"):
            sel.having = self.parse_expr()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                e = self.parse_expr()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                sel.order_by.append((e, desc))
                if not self.accept_op(","):
                    break
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.limit, sel.offset = first, self.parse_expr()
            elif self.accept_op(","):
                sel.offset, sel.limit = first, self.parse_expr()
            else:
                sel.limit = first
        return sel

    def parse_select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return SelectItem(None)
        if self.tok.kind == "ID" and self.peek().value == "." and self.peek(2).value == "*":
            if self.peek().kind == "OP" and self.peek(2).kind == "OP":
                table = self.advance().value
                self.advance()
                self.advance()
                return SelectItem(None, star_table=table)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            alias = self.ident_or_string()
        elif self.tok.kind in ("ID", "STR"):
            alias = self.advance().value
        return SelectItem(expr, alias)

    def ident_or_string(self) -> str:
        if self.tok.kind in ("ID", "STR"):
            return self.advance().value
        self.error("expected alias")

    def parse_table_ref(self) -> tuple[str, str]:
        name = self.ident()
        alias = name
        if self.accept_kw("AS"):
            alias = self.ident()
        elif self.tok.kind == "ID":
            alias = self.advance().value
        return name, alias

    def parse_from(self) -> list[FromItem]:
        name, alias = self.parse_table_ref()
        items = [FromItem(name, alias, "FIRST")]
        while True:
            if self.accept_op(","):
                name, alias = self.parse_table_ref()
                items.append(FromItem(name, alias, "INNER"))
                continue
            if self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            elif self.accept_kw("INNER"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("JOIN"):
                kind = "INNER"
            else:
                break
            name, alias = self.parse_table_ref()
            on = self.parse_expr() if self.accept_kw("ON") else None
            items.append(FromItem(name, alias, kind, on))
        return items

    # ----------------------------------------------------------- expressions
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = Binary("OR", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = Binary("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_kw("NOT"):
            return Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self):
        left = self.parse_relational()
        while True:
            if self.is_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = Binary(op, left, self.parse_relational())
            elif self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                if self.accept_kw("NULL"):
                    left = IsNull(left, negated)
                else:
                    left = Binary("ISNOT" if negated else "IS", left, self.parse_relational())
            elif self.accept_kw("ISNULL"):
                left = IsNull(left, False)
            elif self.accept_kw("NOTNULL"):
                left = IsNull(left, True)
            elif self.is_kw("NOT") and self.peek().kind == "KW" and self.peek().value in (
                "IN", "LIKE", "BETWEEN", "NULL"
            ):
                self.advance()
                left = self.parse_postfix(left, True)
            elif self.is_kw("IN", "LIKE", "BETWEEN"):
                left = self.parse_postfix(left, False)
            else:
                return left

    def parse_postfix(self, left, negated: bool):
        if self.accept_kw("NULL"):  # NOT NULL
            return IsNull(left, True)
        if self.accept_kw("IN"):
            self.expect_op("(")
            items = []
            if self.is_kw("SELECT"):
                self.error("subqueries are not supported")
            if not self.is_op(")"):
                items.append(self.parse_expr())
                while self.accept_op(","):
                    items.append(self.parse_expr())
            self.expect_op(")")
            return InList(left, items, negated)
        if self.accept_kw("LIKE"):
            return Like(left, self.parse_relational(), negated)
        self.expect_kw("BETWEEN")
        low = self.parse_relational()
        self.expect_kw("AND")
        high = self.parse_relational()
        return Between(left, low, high, negated)

    def parse_relational(self):
        left = self.parse_additive()
        while self.is_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.is_op("+", "-"):
            op = self.advance().value
            left = Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_concat()
        while self.is_op("*", "/", "%"):
            op = self.advance().value
            left = Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self):
        left = self.parse_unary()
        while self.is_op("||"):
            self.advance()
            left = Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.is_op("-"):
            self.advance()
            if self.tok.kind == "INT" and self.tok.value == INT_MAX + 1:
                self.advance()
                return Literal(-(INT_MAX + 1))
            return Unary("-", self.parse_unary())
        if self.is_op("+"):
            self.advance()
            return Unary("+", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.tok
        if t.kind == "INT":
            self.advance()
            return Literal(t.value if t.value <= INT_MAX else float(t.value))
        if t.kind == "REAL":
            self.advance()
            return Literal(t.value)
        if t.kind == "STR":
            self.advance()
            return Literal(t.value)
        if self.accept_kw("NULL"):
            return Literal(None)
        if self.accept_op("("):
            if self.is_kw("SELECT"):
                self.error("subqueries are not supported")
            e = self.parse_expr()
            self.expect_op(")")
            return e
        if self.accept_kw("CASE"):
            return self.parse_case()
        if t.kind == "ID":
            self.advance()
            if self.accept_op("("):
                return self.parse_call(t.value.upper())
            if self.accept_op("."):
                return Column(t.value, self.ident())
            return Column(None, t.value)
        self.error("expected expression")

    def parse_call(self, name: str) -> Func:
        if self.accept_op("*"):
            self.expect_op(")")
            if name != "COUNT":
                self.error(f"{name}(*) is not supported")
            return Func(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        args = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return Func(name, args, distinct=distinct)

    def parse_case(self) -> Case:
        operand = None
        if not self.is_kw("WHEN"):
            operand = self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            self.error("expected WHEN")
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return Case(operand, whens, else_)


def parse(sql: str):
    return Parser(sql).parse_statement()

"""Recursive-descent SQL parser."""

from __future__ import annotations

from . import ast
from .errors import SQLError
from .tokenizer import EOF, IDENT, KEYWORD, NUMBER, OP, STRING, Token, tokenize
from .values import INT_MAX, INT_MIN


def parse(sql: str):
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers ------------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != EOF:
            self.pos += 1
        return t

    def error(self, msg: str | None = None):
        t = self.tok
        if msg is None:
            near = "end of input" if t.kind == EOF else repr(t.value)
            msg = f"syntax error near {near}"
        raise SQLError(msg)

    def is_kw(self, *words: str) -> bool:
        return self.tok.kind == KEYWORD and self.tok.value in words

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == OP and self.tok.value in ops

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

    def expect_kw(self, word: str):
        if not self.accept_kw(word):
            self.error()

    def expect_op(self, op: str):
        if not self.accept_op(op):
            self.error()

    def ident(self) -> str:
        if self.tok.kind != IDENT:
            self.error()
        return self.advance().value

    # -- statements -----------------------------------------------------------

    def parse_statement(self):
        if self.is_kw("SELECT"):
            stmt = self.parse_select()
        elif self.is_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.is_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.is_kw("DELETE"):
            stmt = self.parse_delete()
        elif self.is_kw("CREATE"):
            stmt = self.parse_create()
        elif self.is_kw("DROP"):
            stmt = self.parse_drop()
        else:
            self.error()
        self.accept_op(";")
        if self.tok.kind != EOF:
            self.error()
        return stmt

    def parse_create(self) -> ast.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.ident()
        self.expect_op("(")
        columns = [self.parse_column_def()]
        while self.accept_op(","):
            columns.append(self.parse_column_def())
        self.expect_op(")")
        return ast.CreateTable(name, columns, if_not_exists)

    def parse_column_def(self) -> ast.ColumnDef:
        name = self.ident()
        words = []
        while self.tok.kind == IDENT:
            words.append(self.advance().value)
        if words and self.accept_op("("):
            while not self.is_op(")"):
                if self.tok.kind == EOF:
                    self.error()
                self.advance()
            self.advance()
        # Skip column constraints (PRIMARY KEY, NOT NULL, ...), which are not enforced.
        depth = 0
        while not (depth == 0 and self.is_op(",", ")")):
            if self.tok.kind == EOF:
                self.error()
            if self.is_op("("):
                depth += 1
            elif self.is_op(")"):
                depth -= 1
            self.advance()
        return ast.ColumnDef(name, " ".join(words))

    def parse_drop(self) -> ast.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return ast.DropTable(self.ident(), if_exists)

    def parse_insert(self) -> ast.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.ident()
        columns = None
        if self.accept_op("("):
            columns = [self.ident()]
            while self.accept_op(","):
                columns.append(self.ident())
            self.expect_op(")")
        if self.is_kw("SELECT"):
            return ast.Insert(table, columns, None, self.parse_select())
        self.expect_kw("VALUES")
        rows = [self.parse_value_row()]
        while self.accept_op(","):
            rows.append(self.parse_value_row())
        return ast.Insert(table, columns, rows)

    def parse_value_row(self) -> list[ast.Expr]:
        self.expect_op("(")
        row = [self.parse_expr()]
        while self.accept_op(","):
            row.append(self.parse_expr())
        self.expect_op(")")
        return row

    def parse_update(self) -> ast.Update:
        self.expect_kw("UPDATE")
        table = self.ident()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.ident()
            if not (self.accept_op("=") or self.accept_op("==")):
                self.error()
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return ast.Update(table, assignments, where)

    def parse_delete(self) -> ast.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.ident()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return ast.Delete(table, where)

    def parse_select(self) -> ast.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        sel = ast.Select(distinct, items, None)
        if self.accept_kw("FROM"):
            sel.from_table = self.parse_table_ref()
            self.parse_joins(sel)
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
            sel.order_by = [self.parse_order_item()]
            while self.accept_op(","):
                sel.order_by.append(self.parse_order_item())
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.limit, sel.offset = first, self.parse_expr()
            elif self.accept_op(","):
                sel.offset, sel.limit = first, self.parse_expr()
            else:
                sel.limit = first
        return sel

    def parse_select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(ast.Star(None), None)
        if self.tok.kind == IDENT and self.peek().kind == OP and self.peek().value == ".":
            nxt = self.peek(2)
            if nxt.kind == OP and nxt.value == "*":
                table = self.advance().value
                self.advance()
                self.advance()
                return ast.SelectItem(ast.Star(table), None)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            if self.tok.kind == STRING:
                alias = self.advance().value
            else:
                alias = self.ident()
        elif self.tok.kind == IDENT:
            alias = self.advance().value
        return ast.SelectItem(expr, alias)

    def parse_table_ref(self) -> ast.TableRef:
        name = self.ident()
        alias = None
        if self.accept_kw("AS"):
            alias = self.ident()
        elif self.tok.kind == IDENT:
            alias = self.advance().value
        return ast.TableRef(name, alias)

    def parse_joins(self, sel: ast.Select):
        while True:
            if self.accept_op(","):
                sel.joins.append(ast.Join("INNER", self.parse_table_ref(), None))
                continue
            if self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            elif self.accept_kw("INNER") or self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("JOIN"):
                kind = "INNER"
            else:
                return
            table = self.parse_table_ref()
            on = self.parse_expr() if self.accept_kw("ON") else None
            sel.joins.append(ast.Join(kind, table, on))

    def parse_order_item(self) -> ast.OrderItem:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        return ast.OrderItem(expr, desc)

    # -- expressions ----------------------------------------------------------

    def parse_expr(self) -> ast.Expr:
        return self.parse_or()

    def parse_or(self) -> ast.Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = ast.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> ast.Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = ast.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> ast.Expr:
        if self.accept_kw("NOT"):
            return ast.Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> ast.Expr:
        left = self.parse_relational()
        while True:
            if self.is_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ast.Binary(op, left, self.parse_relational())
            elif self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                if self.accept_kw("NULL"):
                    left = ast.IsNull(left, negated)
                else:
                    left = ast.Is(left, self.parse_relational(), negated)
            elif (
                self.is_kw("NOT")
                and self.peek().kind == KEYWORD
                and self.peek().value
                in (
                    "IN",
                    "BETWEEN",
                    "LIKE",
                    "NULL",
                )
            ):
                self.advance()
                left = self.parse_postfix_predicate(left, True)
            elif self.is_kw("IN", "BETWEEN", "LIKE"):
                left = self.parse_postfix_predicate(left, False)
            else:
                return left

    def parse_postfix_predicate(self, left: ast.Expr, negated: bool) -> ast.Expr:
        if self.accept_kw("NULL"):  # "expr NOT NULL"
            return ast.IsNull(left, True)
        if self.accept_kw("IN"):
            self.expect_op("(")
            items: list[ast.Expr] = []
            if not self.is_op(")"):
                items.append(self.parse_expr())
                while self.accept_op(","):
                    items.append(self.parse_expr())
            self.expect_op(")")
            return ast.InList(left, items, negated)
        if self.accept_kw("BETWEEN"):
            low = self.parse_relational()
            self.expect_kw("AND")
            high = self.parse_relational()
            return ast.Between(left, low, high, negated)
        self.expect_kw("LIKE")
        return ast.Like(left, self.parse_relational(), negated)

    def parse_relational(self) -> ast.Expr:
        left = self.parse_additive()
        while self.is_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> ast.Expr:
        left = self.parse_multiplicative()
        while self.is_op("+", "-"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> ast.Expr:
        left = self.parse_concat()
        while self.is_op("*", "/", "%"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> ast.Expr:
        left = self.parse_unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> ast.Expr:
        if self.accept_op("-"):
            if self.tok.kind == NUMBER and self.tok.value == INT_MAX + 1:
                self.advance()
                return ast.Literal(INT_MIN)
            return ast.Unary("-", self.parse_unary())
        if self.accept_op("+"):
            return ast.Unary("+", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        t = self.tok
        if t.kind == NUMBER:
            self.advance()
            v = t.value
            if isinstance(v, int) and v > INT_MAX:
                v = float(v)
            return ast.Literal(v)
        if t.kind == STRING:
            self.advance()
            return ast.Literal(t.value)
        if self.accept_kw("NULL"):
            return ast.Literal(None)
        if self.accept_op("("):
            e = self.parse_expr()
            self.expect_op(")")
            return e
        if self.accept_kw("CASE"):
            return self.parse_case()
        if t.kind == IDENT:
            self.advance()
            if self.accept_op("("):
                return self.parse_function(t.value.upper())
            if self.accept_op("."):
                return ast.Column(t.value, self.ident())
            return ast.Column(None, t.value)
        self.error()

    def parse_case(self) -> ast.Expr:
        operand = None if self.is_kw("WHEN") else self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            self.error()
        default = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return ast.Case(operand, whens, default)

    def parse_function(self, name: str) -> ast.Expr:
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.Func(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        args: list[ast.Expr] = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return ast.Func(name, args, distinct=distinct)

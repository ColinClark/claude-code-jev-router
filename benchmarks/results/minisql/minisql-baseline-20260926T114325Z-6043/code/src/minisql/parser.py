"""Recursive-descent SQL parser.

Operator precedence follows SQLite (lowest to highest):
OR, AND, NOT, equality (= == != <> IS IN LIKE BETWEEN), relational (< <= > >=),
additive (+ -), multiplicative (* / %), concatenation (||), unary (- +).
"""

from __future__ import annotations

from . import ast
from .errors import SQLError
from .tokenizer import Token, tokenize


def parse(sql: str) -> ast.Statement:
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ helpers

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, msg: str | None = None) -> SQLError:
        tok = self.tok
        if msg is None:
            near = "end of input" if tok.kind == "eof" else repr(tok.value)
            msg = f"syntax error near {near}"
        return SQLError(msg)

    def at_kw(self, *words: str) -> bool:
        return self.tok.kind == "kw" and self.tok.value in words

    def at_word(self, word: str) -> bool:
        """Match a keyword or a non-reserved word such as PRIMARY or KEY."""
        tok = self.tok
        return tok.kind in ("kw", "id") and str(tok.value).upper() == word

    def accept_kw(self, *words: str) -> bool:
        if self.at_kw(*words):
            self.advance()
            return True
        return False

    def accept_word(self, word: str) -> bool:
        if self.at_word(word):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error()

    def expect_word(self, word: str) -> None:
        if not self.accept_word(word):
            raise self.error()

    def at_op(self, *ops: str) -> bool:
        return self.tok.kind == "op" and self.tok.value in ops

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def identifier(self) -> str:
        tok = self.tok
        if tok.kind != "id":
            raise self.error()
        self.advance()
        return str(tok.value).lower()

    # ------------------------------------------------------------ statements

    def parse_statement(self) -> ast.Statement:
        if self.at_kw("SELECT"):
            stmt: ast.Statement = self.parse_select()
        elif self.at_kw("CREATE"):
            stmt = self.parse_create()
        elif self.at_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.at_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.at_kw("DELETE"):
            stmt = self.parse_delete()
        elif self.at_word("DROP"):
            stmt = self.parse_drop()
        else:
            raise self.error()
        while self.accept_op(";"):
            pass
        if self.tok.kind != "eof":
            raise self.error()
        return stmt

    def parse_create(self) -> ast.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_word("IF"):
            self.expect_kw("NOT")
            self.expect_word("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        columns = [self.parse_column_def()]
        while self.accept_op(","):
            columns.append(self.parse_column_def())
        self.expect_op(")")
        return ast.CreateTable(name, columns, if_not_exists)

    def parse_column_def(self) -> ast.ColumnDef:
        name = self.identifier()
        type_words = []
        while self.tok.kind == "id" and not self._at_constraint():
            type_words.append(str(self.advance().value).upper())
        if type_words and self.accept_op("("):
            self._signed_number()
            if self.accept_op(","):
                self._signed_number()
            self.expect_op(")")
        col = ast.ColumnDef(name, " ".join(type_words))
        while True:
            if self.accept_kw("NOT"):
                self.expect_kw("NULL")
                col.not_null = True
            elif self.accept_kw("NULL"):
                pass
            elif self.accept_word("PRIMARY"):
                self.expect_word("KEY")
                self.accept_kw("ASC", "DESC")
                col.primary_key = True
            elif self.accept_word("UNIQUE"):
                col.unique = True
            elif self.accept_word("DEFAULT"):
                if self.accept_op("("):
                    col.default = self.parse_expr()
                    self.expect_op(")")
                elif self.at_op("-", "+"):
                    sign = self.advance().value
                    num = self._number_literal()
                    col.default = ast.Unary(str(sign), num)
                else:
                    tok = self.advance()
                    if tok.kind in ("num", "str"):
                        col.default = ast.Literal(tok.value)
                    elif tok.kind == "kw" and tok.value == "NULL":
                        col.default = ast.Literal(None)
                    else:
                        raise SQLError("default value of column must be constant")
            else:
                break
        return col

    def _at_constraint(self) -> bool:
        return any(self.at_word(w) for w in ("PRIMARY", "UNIQUE", "DEFAULT"))

    def _number_literal(self) -> ast.Literal:
        tok = self.advance()
        if tok.kind != "num":
            raise self.error()
        return ast.Literal(tok.value)

    def _signed_number(self) -> None:
        if self.at_op("-", "+"):
            self.advance()
        self._number_literal()

    def parse_drop(self) -> ast.DropTable:
        self.expect_word("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_word("IF"):
            self.expect_word("EXISTS")
            if_exists = True
        return ast.DropTable(self.identifier(), if_exists)

    def parse_insert(self) -> ast.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.identifier()
        columns = None
        if self.accept_op("("):
            columns = [self.identifier()]
            while self.accept_op(","):
                columns.append(self.identifier())
            self.expect_op(")")
        self.expect_kw("VALUES")
        rows = [self._value_row()]
        while self.accept_op(","):
            rows.append(self._value_row())
        return ast.Insert(table, columns, rows)

    def _value_row(self) -> list[ast.Expr]:
        self.expect_op("(")
        values = [self.parse_expr()]
        while self.accept_op(","):
            values.append(self.parse_expr())
        self.expect_op(")")
        return values

    def parse_update(self) -> ast.Update:
        self.expect_kw("UPDATE")
        table = self.identifier()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.identifier()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return ast.Update(table, assignments, where)

    def parse_delete(self) -> ast.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.identifier()
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
        select = ast.Select(distinct, items, None)
        if self.accept_kw("FROM"):
            select.source = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    select.joins.append(ast.Join("CROSS", self.parse_table_ref(), None))
                    continue
                if self.accept_kw("CROSS"):
                    self.expect_kw("JOIN")
                    select.joins.append(ast.Join("CROSS", self.parse_table_ref(), None))
                    continue
                if self.accept_kw("LEFT"):
                    self.accept_kw("OUTER")
                    kind = "LEFT"
                elif self.accept_kw("INNER"):
                    kind = "INNER"
                elif self.at_kw("JOIN"):
                    kind = "INNER"
                else:
                    break
                self.expect_kw("JOIN")
                table = self.parse_table_ref()
                on = self.parse_expr() if self.accept_kw("ON") else None
                select.joins.append(ast.Join(kind, table, on))
        if self.accept_kw("WHERE"):
            select.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            select.group_by = [self.parse_expr()]
            while self.accept_op(","):
                select.group_by.append(self.parse_expr())
        if self.accept_kw("HAVING"):
            select.having = self.parse_expr()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            select.order_by = [self.parse_order_item()]
            while self.accept_op(","):
                select.order_by.append(self.parse_order_item())
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                select.limit, select.offset = first, self.parse_expr()
            elif self.accept_op(","):
                select.offset, select.limit = first, self.parse_expr()
            else:
                select.limit = first
        return select

    def parse_select_item(self) -> ast.StarItem | ast.ExprItem:
        if self.accept_op("*"):
            return ast.StarItem(None)
        tok, nxt = self.tok, self.tokens[self.pos + 1]
        if tok.kind == "id" and nxt.kind == "op" and nxt.value == ".":
            after = self.tokens[self.pos + 2]
            if after.kind == "op" and after.value == "*":
                self.pos += 3
                return ast.StarItem(str(tok.value).lower())
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            tok = self.advance()
            if tok.kind not in ("id", "str"):
                raise self.error()
            alias = str(tok.value).lower()
        elif self.tok.kind in ("id", "str"):
            alias = str(self.advance().value).lower()
        return ast.ExprItem(expr, alias)

    def parse_table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.tok.kind == "id":
            alias = self.identifier()
        return ast.TableRef(name, alias)

    def parse_order_item(self) -> ast.OrderItem:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        return ast.OrderItem(expr, desc)

    # ------------------------------------------------------------ expressions

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
            if self.at_op("=", "==", "!=", "<>"):
                op = str(self.advance().value)
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ast.Binary(op, left, self.parse_relational())
            elif self.accept_kw("ISNULL"):
                left = ast.Binary("IS", left, ast.Literal(None))
            elif self.accept_kw("NOTNULL"):
                left = ast.Binary("IS NOT", left, ast.Literal(None))
            elif (
                self.at_kw("NOT")
                and self.tokens[self.pos + 1].kind == "kw"
                and self.tokens[self.pos + 1].value == "NULL"
            ):
                self.pos += 2
                left = ast.Binary("IS NOT", left, ast.Literal(None))
            elif self.accept_kw("IS"):
                op = "IS NOT" if self.accept_kw("NOT") else "IS"
                left = ast.Binary(op, left, self.parse_relational())
            elif (
                self.at_kw("NOT")
                and self.tokens[self.pos + 1].kind == "kw"
                and self.tokens[self.pos + 1].value in ("IN", "BETWEEN", "LIKE")
            ):
                self.advance()
                left = self._parse_postfix(left, negated=True)
            elif self.at_kw("IN", "BETWEEN", "LIKE"):
                left = self._parse_postfix(left, negated=False)
            else:
                return left

    def _parse_postfix(self, left: ast.Expr, negated: bool) -> ast.Expr:
        kw = self.advance().value
        if kw == "IN":
            self.expect_op("(")
            items: list[ast.Expr] = []
            if not self.at_op(")"):
                items.append(self.parse_expr())
                while self.accept_op(","):
                    items.append(self.parse_expr())
            self.expect_op(")")
            return ast.InList(left, items, negated)
        if kw == "BETWEEN":
            low = self.parse_relational()
            self.expect_kw("AND")
            high = self.parse_relational()
            return ast.Between(left, low, high, negated)
        pattern = self.parse_relational()
        escape = self.parse_relational() if self.accept_kw("ESCAPE") else None
        return ast.Like(left, pattern, escape, negated)

    def parse_relational(self) -> ast.Expr:
        left = self.parse_additive()
        while self.at_op("<", "<=", ">", ">="):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> ast.Expr:
        left = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> ast.Expr:
        left = self.parse_concat()
        while self.at_op("*", "/", "%"):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> ast.Expr:
        left = self.parse_unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> ast.Expr:
        if self.at_op("-", "+"):
            op = str(self.advance().value)
            return ast.Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        tok = self.tok
        if tok.kind in ("num", "str"):
            self.advance()
            return ast.Literal(tok.value)
        if tok.kind == "kw" and tok.value == "NULL":
            self.advance()
            return ast.Literal(None)
        if self.accept_op("("):
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind == "id":
            self.advance()
            name = str(tok.value).lower()
            if self.accept_op("("):
                return self._parse_call(name)
            if self.accept_op("."):
                return ast.Column(name, self.identifier())
            return ast.Column(None, name, str(tok.value) if tok.double_quoted else None)
        raise self.error()

    def _parse_call(self, name: str) -> ast.Func:
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.Func(name, [], star=True)
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args: list[ast.Expr] = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return ast.Func(name, args, distinct=distinct)

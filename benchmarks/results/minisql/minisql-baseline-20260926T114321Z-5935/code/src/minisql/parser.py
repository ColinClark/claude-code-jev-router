"""Recursive-descent parser producing the syntax tree in :mod:`minisql.ast`."""

from __future__ import annotations

from . import ast
from .errors import SQLError
from .lexer import Token, tokenize
from .values import INT64_MAX, neg


def parse(sql: str):
    """Parse exactly one SQL statement (an optional trailing semicolon is allowed)."""
    return Parser(tokenize(sql)).parse_single()


def _is_false_literal(e: ast.Expr) -> bool:
    return isinstance(e, ast.Literal) and type(e.value) is int and e.value == 0


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
        if t.kind != "eof":
            self.pos += 1
        return t

    def error(self, msg: str | None = None) -> SQLError:
        t = self.tok
        if msg is None:
            if t.kind == "eof":
                msg = "incomplete input"
            else:
                shown = t.value if t.kind != "str" else f"'{t.value}'"
                msg = f'near "{shown}": syntax error'
        return SQLError(msg)

    def is_kw(self, *words: str) -> bool:
        t = self.tok
        return t.kind == "kw" and t.value in words

    def is_op(self, *ops: str) -> bool:
        t = self.tok
        return t.kind == "op" and t.value in ops

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
            raise self.error()

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def is_word(self, word: str) -> bool:
        """Match a non-reserved keyword such as NULLS or FIRST."""
        t = self.tok
        return t.kind == "ident" and str(t.value).upper() == word

    def identifier(self) -> str:
        t = self.tok
        if t.kind != "ident":
            raise self.error()
        self.advance()
        return str(t.value)

    # -- statements ---------------------------------------------------------

    def parse_single(self):
        while self.accept_op(";"):
            pass
        if self.tok.kind == "eof":
            raise SQLError("empty statement")
        stmt = self.statement()
        while self.accept_op(";"):
            pass
        if self.tok.kind != "eof":
            raise self.error()
        return stmt

    def statement(self):
        if self.is_kw("SELECT"):
            return self.select()
        if self.is_kw("CREATE"):
            return self.create_table()
        if self.is_kw("DROP"):
            return self.drop_table()
        if self.is_kw("INSERT"):
            return self.insert()
        if self.is_kw("UPDATE"):
            return self.update()
        if self.is_kw("DELETE"):
            return self.delete()
        raise self.error()

    def create_table(self) -> ast.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        columns = []
        while True:
            col = self.identifier()
            type_words = []
            while self.tok.kind == "ident":
                type_words.append(str(self.advance().value))
            if type_words and self.accept_op("("):
                # Size arguments such as VARCHAR(10) are accepted and ignored.
                depth = 1
                while depth:
                    t = self.advance()
                    if t.kind == "eof":
                        raise self.error()
                    if t.kind == "op" and t.value == "(":
                        depth += 1
                    elif t.kind == "op" and t.value == ")":
                        depth -= 1
            # Column constraints (PRIMARY KEY, NOT NULL, ...) are accepted and ignored.
            depth = 0
            while depth or not (self.is_op(",") or self.is_op(")")):
                t = self.advance()
                if t.kind == "eof":
                    raise self.error()
                if t.kind == "op" and t.value == "(":
                    depth += 1
                elif t.kind == "op" and t.value == ")":
                    depth -= 1
            columns.append(ast.ColumnDef(col, " ".join(type_words) or None))
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        return ast.CreateTable(name, columns, if_not_exists)

    def drop_table(self) -> ast.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return ast.DropTable(self.identifier(), if_exists)

    def insert(self) -> ast.Insert:
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
        rows = []
        while True:
            self.expect_op("(")
            row = [self.expr()]
            while self.accept_op(","):
                row.append(self.expr())
            self.expect_op(")")
            rows.append(row)
            if not self.accept_op(","):
                break
        return ast.Insert(table, columns, rows)

    def update(self) -> ast.Update:
        self.expect_kw("UPDATE")
        table = self.identifier()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.identifier()
            if not (self.accept_op("=") or self.accept_op("==")):
                raise self.error()
            assignments.append((col, self.expr()))
            if not self.accept_op(","):
                break
        where = self.expr() if self.accept_kw("WHERE") else None
        return ast.Update(table, assignments, where)

    def delete(self) -> ast.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.identifier()
        where = self.expr() if self.accept_kw("WHERE") else None
        return ast.Delete(table, where)

    def select(self) -> ast.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.select_item()]
        while self.accept_op(","):
            items.append(self.select_item())
        stmt = ast.Select(items, distinct)
        if self.accept_kw("FROM"):
            stmt.source = self.table_ref()
            self.joins(stmt)
        if self.accept_kw("WHERE"):
            stmt.where = self.expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            stmt.group_by = [self.expr()]
            while self.accept_op(","):
                stmt.group_by.append(self.expr())
        if self.accept_kw("HAVING"):
            stmt.having = self.expr()
        if self.is_kw("UNION", "EXCEPT", "INTERSECT"):
            raise SQLError(f"compound SELECT ({self.tok.value}) is not supported")
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            stmt.order_by = [self.order_item()]
            while self.accept_op(","):
                stmt.order_by.append(self.order_item())
        if self.accept_kw("LIMIT"):
            first = self.expr()
            if self.accept_kw("OFFSET"):
                stmt.limit = first
                stmt.offset = self.expr()
            elif self.accept_op(","):
                stmt.offset = first
                stmt.limit = self.expr()
            else:
                stmt.limit = first
        return stmt

    def select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(None)
        t = self.tok
        if t.kind == "ident" and self.peek().kind == "op" and self.peek().value == ".":
            nxt = self.peek(2)
            if nxt.kind == "op" and nxt.value == "*":
                self.pos += 3
                return ast.SelectItem(None, star_table=str(t.value))
        expr = self.expr()
        alias = None
        if self.accept_kw("AS"):
            if self.tok.kind in ("ident", "str"):
                alias = str(self.advance().value)
            else:
                raise self.error()
        elif self.tok.kind in ("ident", "str"):
            alias = str(self.advance().value)
        return ast.SelectItem(expr, alias)

    def table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS") or self.tok.kind == "ident":
            alias = self.identifier()
        return ast.TableRef(name, alias)

    def joins(self, stmt: ast.Select) -> None:
        while True:
            if self.accept_op(","):
                stmt.joins.append(ast.Join("CROSS", self.table_ref(), None))
                continue
            if self.is_kw("NATURAL", "RIGHT", "FULL"):
                raise SQLError(f"{self.tok.value} JOIN is not supported")
            if self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                kind = "CROSS"
            elif self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            elif self.accept_kw("INNER"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("JOIN"):
                kind = "INNER"
            else:
                return
            table = self.table_ref()
            on = None
            if self.accept_kw("ON"):
                on = self.expr()
            elif self.is_kw("USING"):
                raise SQLError("JOIN ... USING is not supported")
            stmt.joins.append(ast.Join(kind, table, on))

    def order_item(self) -> ast.OrderItem:
        expr = self.expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        if self.is_word("NULLS"):
            self.advance()
            if self.is_word("FIRST"):
                nulls_first = True
            elif self.is_word("LAST"):
                nulls_first = False
            else:
                raise self.error()
            self.advance()
        return ast.OrderItem(expr, desc, nulls_first)

    # -- expressions (lowest to highest precedence) -------------------------

    def expr(self) -> ast.Expr:
        return self.or_expr()

    def or_expr(self) -> ast.Expr:
        left = self.and_expr()
        while self.accept_kw("OR"):
            left = ast.Binary("OR", left, self.and_expr())
        return left

    def and_expr(self) -> ast.Expr:
        left = self.not_expr()
        while self.accept_kw("AND"):
            right = self.not_expr()
            if _is_false_literal(left) or _is_false_literal(right):
                # SQLite folds "0 AND x" to the constant 0 while parsing; this matters when
                # such a term is used as an ORDER BY / GROUP BY column position.
                left = ast.Literal(0)
            else:
                left = ast.Binary("AND", left, right)
        return left

    def not_expr(self) -> ast.Expr:
        if self.accept_kw("NOT"):
            return ast.Unary("NOT", self.not_expr())
        return self.equality()

    def equality(self) -> ast.Expr:
        left = self.relational()
        while True:
            if self.is_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ast.Binary(op, left, self.relational())
            elif self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                right = self.relational()
                if isinstance(right, ast.Literal) and right.value is None:
                    left = ast.IsNull(left, negated)
                else:
                    left = ast.Binary("IS NOT" if negated else "IS", left, right)
            elif self.accept_kw("ISNULL"):
                left = ast.IsNull(left, False)
            elif self.accept_kw("NOTNULL"):
                left = ast.IsNull(left, True)
            elif self.is_kw("NOT") and self.peek().kind == "kw" and self.peek().value == "NULL":
                self.pos += 2
                left = ast.IsNull(left, True)
            elif self.is_kw("IN", "LIKE", "BETWEEN") or (
                self.is_kw("NOT")
                and self.peek().kind == "kw"
                and self.peek().value in ("IN", "LIKE", "BETWEEN")
            ):
                negated = self.accept_kw("NOT")
                op = self.advance().value
                if op == "IN":
                    left = ast.InList(left, self.in_list(), negated)
                elif op == "LIKE":
                    pattern = self.relational()
                    escape = self.relational() if self.accept_kw("ESCAPE") else None
                    left = ast.Like(left, pattern, escape, negated)
                else:
                    low = self.relational()
                    self.expect_kw("AND")
                    high = self.relational()
                    left = ast.Between(left, low, high, negated)
            else:
                return left

    def in_list(self) -> list[ast.Expr]:
        self.expect_op("(")
        if self.is_kw("SELECT"):
            raise SQLError("subqueries are not supported")
        items: list[ast.Expr] = []
        if self.accept_op(")"):
            return items
        items.append(self.expr())
        while self.accept_op(","):
            items.append(self.expr())
        self.expect_op(")")
        return items

    def relational(self) -> ast.Expr:
        left = self.additive()
        while self.is_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = ast.Binary(op, left, self.additive())
        return left

    def additive(self) -> ast.Expr:
        left = self.multiplicative()
        while self.is_op("+", "-"):
            op = self.advance().value
            left = ast.Binary(op, left, self.multiplicative())
        return left

    def multiplicative(self) -> ast.Expr:
        left = self.concat()
        while self.is_op("*", "/", "%"):
            op = self.advance().value
            left = ast.Binary(op, left, self.concat())
        return left

    def concat(self) -> ast.Expr:
        left = self.unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self.unary())
        return left

    def unary(self) -> ast.Expr:
        if self.is_op("-"):
            self.advance()
            t = self.tok
            if t.kind == "int" and t.value == INT64_MAX + 1:
                self.advance()
                return ast.Literal(-(INT64_MAX + 1))
            operand = self.unary()
            if isinstance(operand, ast.Literal) and isinstance(operand.value, (int, float)):
                # Fold negative numeric literals (SQLite treats "-1" as a constant integer,
                # e.g. for ORDER BY positions).
                return ast.Literal(neg(operand.value))
            return ast.Unary("-", operand)
        if self.accept_op("+"):
            operand = self.unary()
            if isinstance(operand, ast.Literal) and isinstance(operand.value, (int, float)):
                return operand
            return ast.Unary("+", operand)
        return self.primary()

    def primary(self) -> ast.Expr:
        t = self.tok
        if t.kind == "int":
            self.advance()
            v = t.value
            return ast.Literal(float(v) if v > INT64_MAX else v)
        if t.kind in ("float", "str"):
            self.advance()
            return ast.Literal(t.value)
        if t.kind == "kw":
            if t.value == "NULL":
                self.advance()
                return ast.Literal(None)
            if t.value == "CASE":
                return self.case_expr()
            if t.value == "CAST":
                return self.cast_expr()
            raise self.error()
        if t.kind == "op" and t.value == "(":
            self.advance()
            if self.is_kw("SELECT"):
                raise SQLError("subqueries are not supported")
            e = self.expr()
            self.expect_op(")")
            return e
        if t.kind == "ident":
            self.advance()
            name = str(t.value)
            if self.is_op("("):
                return self.function_call(name)
            if self.accept_op("."):
                col = self.identifier()
                return ast.Column(name.lower(), col.lower())
            return ast.Column(None, name.lower())
        raise self.error()

    def function_call(self, name: str) -> ast.Func:
        self.expect_op("(")
        fn = ast.Func(name.lower(), [])
        if self.accept_op("*"):
            fn.star = True
            self.expect_op(")")
            return fn
        if self.accept_op(")"):
            return fn
        if self.accept_kw("DISTINCT"):
            fn.distinct = True
        else:
            self.accept_kw("ALL")
        fn.args.append(self.expr())
        while self.accept_op(","):
            fn.args.append(self.expr())
        self.expect_op(")")
        return fn

    def case_expr(self) -> ast.Case:
        self.expect_kw("CASE")
        operand = None if self.is_kw("WHEN") else self.expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.expr()
            self.expect_kw("THEN")
            whens.append((cond, self.expr()))
        if not whens:
            raise self.error()
        default = self.expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return ast.Case(operand, whens, default)

    def cast_expr(self) -> ast.Cast:
        self.expect_kw("CAST")
        self.expect_op("(")
        operand = self.expr()
        self.expect_kw("AS")
        words = []
        while self.tok.kind == "ident":
            words.append(str(self.advance().value))
        if not words:
            raise self.error()
        if self.accept_op("("):
            while not self.accept_op(")"):
                if self.advance().kind == "eof":
                    raise self.error()
        self.expect_op(")")
        return ast.Cast(operand, " ".join(words))

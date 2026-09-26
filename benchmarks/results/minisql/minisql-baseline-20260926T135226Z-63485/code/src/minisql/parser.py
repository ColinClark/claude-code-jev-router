"""Recursive-descent parser producing the AST in :mod:`minisql.ast`."""

from __future__ import annotations

from . import ast
from .errors import SQLError
from .lexer import INT64_MAX, INT64_MIN, Token, tokenize

EQUALITY_OPS = {"=": "=", "==": "=", "!=": "!=", "<>": "!="}
RELATIONAL_OPS = ("<", "<=", ">", ">=")


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
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def at_kw(self, *words: str) -> bool:
        tok = self.tok
        return tok.kind == "KW" and tok.value in words

    def at_op(self, *ops: str) -> bool:
        tok = self.tok
        return tok.kind == "OP" and tok.value in ops

    def accept_kw(self, *words: str) -> bool:
        if self.at_kw(*words):
            self.advance()
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            self.error(f"expected {word}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            self.error(f"expected {op!r}")

    def error(self, msg: str = "syntax error"):
        tok = self.tok
        near = "end of input" if tok.kind == "EOF" else repr(tok.value)
        raise SQLError(f"{msg} near {near}")

    def identifier(self) -> str:
        tok = self.tok
        if tok.kind != "ID":
            self.error("expected identifier")
        self.advance()
        return str(tok.value)

    # --------------------------------------------------------- statements

    def parse_statement(self) -> ast.Statement:
        if self.at_kw("SELECT"):
            stmt: ast.Statement = self.parse_select()
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
            self.error()
        while self.accept_op(";"):
            pass
        if self.tok.kind != "EOF":
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
        name = self.identifier()
        self.expect_op("(")
        columns = []
        while True:
            col = self.identifier()
            type_words = []
            while self.tok.kind == "ID":
                type_words.append(self.identifier())
            type_name = " ".join(type_words)
            if self.accept_op("("):
                size = [self.parse_signed_number()]
                if self.accept_op(","):
                    size.append(self.parse_signed_number())
                self.expect_op(")")
                type_name += "(" + ",".join(size) + ")"
            columns.append(ast.ColumnDef(col, type_name))
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return ast.CreateTable(name, columns, if_not_exists)

    def parse_signed_number(self) -> str:
        sign = ""
        if self.at_op("+", "-"):
            sign = str(self.advance().value)
        if self.tok.kind != "NUM":
            self.error("expected number")
        return sign + str(self.advance().value)

    def parse_drop(self) -> ast.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
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
        if self.at_kw("SELECT"):
            return ast.Insert(table, columns, select=self.parse_select())
        self.expect_kw("VALUES")
        rows = []
        while True:
            self.expect_op("(")
            rows.append(self.parse_expr_list())
            self.expect_op(")")
            if not self.accept_op(","):
                break
        return ast.Insert(table, columns, rows=rows)

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
        stmt = ast.Select(items, distinct)
        if self.accept_kw("FROM"):
            stmt.from_ = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    stmt.joins.append(ast.Join("CROSS", self.parse_table_ref(), None))
                    continue
                if self.accept_kw("CROSS"):
                    self.expect_kw("JOIN")
                    stmt.joins.append(ast.Join("CROSS", self.parse_table_ref(), None))
                    continue
                if self.at_kw("JOIN", "INNER", "LEFT"):
                    kind = "INNER"
                    if self.accept_kw("LEFT"):
                        kind = "LEFT"
                        self.accept_kw("OUTER")
                    else:
                        self.accept_kw("INNER")
                    self.expect_kw("JOIN")
                    table = self.parse_table_ref()
                    on = None
                    if self.accept_kw("ON"):
                        on = self.parse_expr()
                    stmt.joins.append(ast.Join(kind, table, on))
                    continue
                break
        if self.accept_kw("WHERE"):
            stmt.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            stmt.group_by = self.parse_expr_list()
        if self.accept_kw("HAVING"):
            stmt.having = self.parse_expr()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                expr = self.parse_expr()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                stmt.order_by.append(ast.OrderTerm(expr, desc))
                if not self.accept_op(","):
                    break
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                stmt.limit, stmt.offset = first, self.parse_expr()
            elif self.accept_op(","):
                stmt.offset, stmt.limit = first, self.parse_expr()
            else:
                stmt.limit = first
        return stmt

    def parse_select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(ast.Star())
        if (
            self.tok.kind == "ID"
            and self.tokens[self.pos + 1].kind == "OP"
            and self.tokens[self.pos + 1].value == "."
            and self.tokens[self.pos + 2].kind == "OP"
            and self.tokens[self.pos + 2].value == "*"
        ):
            table = self.identifier()
            self.pos += 2
            return ast.SelectItem(ast.Star(table))
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            if self.tok.kind == "STR":
                alias = str(self.advance().value)
            else:
                alias = self.identifier()
        elif self.tok.kind == "ID":
            alias = self.identifier()
        return ast.SelectItem(expr, alias)

    def parse_table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.tok.kind == "ID":
            alias = self.identifier()
        return ast.TableRef(name, alias)

    # -------------------------------------------------------- expressions

    def parse_expr_list(self) -> list[ast.Expr]:
        items = [self.parse_expr()]
        while self.accept_op(","):
            items.append(self.parse_expr())
        return items

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
            tok = self.tok
            if tok.kind == "OP" and tok.value in EQUALITY_OPS:
                self.advance()
                left = ast.Binary(EQUALITY_OPS[tok.value], left, self.parse_relational())
            elif self.accept_kw("IS"):
                op = "IS NOT" if self.accept_kw("NOT") else "IS"
                left = ast.Binary(op, left, self.parse_relational())
            elif self.accept_kw("ISNULL"):
                left = ast.Binary("IS", left, ast.Literal(None))
            elif self.accept_kw("NOTNULL"):
                left = ast.Binary("IS NOT", left, ast.Literal(None))
            elif self.at_kw("NOT") and self.tokens[self.pos + 1].kind == "KW" and (
                self.tokens[self.pos + 1].value in ("IN", "BETWEEN", "LIKE", "NULL")
            ):
                self.advance()
                if self.accept_kw("NULL"):
                    left = ast.Binary("IS NOT", left, ast.Literal(None))
                else:
                    left = self.parse_postfix(left, negated=True)
            elif self.at_kw("IN", "BETWEEN", "LIKE"):
                left = self.parse_postfix(left, negated=False)
            else:
                return left

    def parse_postfix(self, left: ast.Expr, negated: bool) -> ast.Expr:
        if self.accept_kw("IN"):
            self.expect_op("(")
            if self.at_kw("SELECT"):
                self.error("subqueries are not supported")
            items: list[ast.Expr] = []
            if not self.at_op(")"):
                items = self.parse_expr_list()
            self.expect_op(")")
            return ast.InList(left, tuple(items), negated)
        if self.accept_kw("BETWEEN"):
            low = self.parse_relational()
            self.expect_kw("AND")
            high = self.parse_relational()
            return ast.Between(left, low, high, negated)
        self.expect_kw("LIKE")
        pattern = self.parse_relational()
        escape = self.parse_relational() if self.accept_kw("ESCAPE") else None
        return ast.Like(left, pattern, escape, negated)

    def parse_relational(self) -> ast.Expr:
        left = self.parse_additive()
        while self.at_op(*RELATIONAL_OPS):
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
            tok = self.tok
            if op == "-" and tok.kind == "NUM" and tok.value == INT64_MAX + 1:
                self.advance()
                return ast.Literal(INT64_MIN)
            return ast.Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        tok = self.tok
        if tok.kind == "NUM":
            self.advance()
            value = tok.value
            if isinstance(value, int) and value > INT64_MAX:
                value = float(value)
            return ast.Literal(value)
        if tok.kind == "STR":
            self.advance()
            return ast.Literal(tok.value)
        if tok.kind == "KW":
            if tok.value == "NULL":
                self.advance()
                return ast.Literal(None)
            if tok.value == "CASE":
                return self.parse_case()
            if tok.value == "CAST":
                self.advance()
                self.expect_op("(")
                operand = self.parse_expr()
                self.expect_kw("AS")
                words = [self.identifier()]
                while self.tok.kind == "ID":
                    words.append(self.identifier())
                if self.accept_op("("):
                    self.parse_signed_number()
                    if self.accept_op(","):
                        self.parse_signed_number()
                    self.expect_op(")")
                self.expect_op(")")
                return ast.Cast(operand, " ".join(words))
            self.error()
        if tok.kind == "OP" and tok.value == "(":
            self.advance()
            if self.at_kw("SELECT"):
                self.error("subqueries are not supported")
            expr = self.parse_expr()
            if self.at_op(","):
                self.error("row values are not supported")
            self.expect_op(")")
            return expr
        if tok.kind == "ID":
            name = self.identifier()
            if self.accept_op("("):
                return self.parse_call(name)
            if self.accept_op("."):
                return ast.Column(name, self.identifier())
            return ast.Column(None, name)
        self.error()

    def parse_call(self, name: str) -> ast.Func:
        upper = name.upper()
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.Func(upper, (), star=True)
        if self.accept_op(")"):
            return ast.Func(upper, ())
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args = self.parse_expr_list()
        self.expect_op(")")
        return ast.Func(upper, tuple(args), distinct=distinct)

    def parse_case(self) -> ast.Case:
        self.expect_kw("CASE")
        operand = None
        if not self.at_kw("WHEN"):
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
        return ast.Case(operand, tuple(whens), else_)

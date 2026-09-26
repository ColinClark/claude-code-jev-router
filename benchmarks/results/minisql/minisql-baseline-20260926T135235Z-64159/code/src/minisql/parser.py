"""Recursive-descent SQL parser producing minisql.ast nodes."""

from __future__ import annotations

from minisql import ast
from minisql.errors import SQLError
from minisql.tokenizer import EOF, ID, NUM, OP, QID, STR, Token, tokenize
from minisql.values import INT_MAX

# Keywords that cannot be used as bare identifiers or implicit aliases.
RESERVED = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST CREATE CROSS DELETE DESC DISTINCT DROP ELSE END EXISTS
    FROM FULL GROUP HAVING IN INNER INSERT INTO IS ISNULL JOIN LEFT LIKE LIMIT NATURAL NOT
    NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT SELECT SET TABLE THEN UNION UPDATE USING
    VALUES WHEN WHERE
    """.split()
)


def parse(sql: str):
    return Parser(sql).parse_statement()


class Parser:
    def __init__(self, sql: str):
        self.tokens = tokenize(sql)
        self.i = 0

    # ---- token helpers ----

    def peek(self, offset: int = 0) -> Token:
        if offset:
            return self.tokens[min(self.i + offset, len(self.tokens) - 1)]
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != EOF:
            self.i += 1
        return tok

    def error(self, msg: str | None = None):
        tok = self.peek()
        near = tok.value if tok.kind != EOF else "end of input"
        raise SQLError(msg or f"syntax error near {near!r}")

    def at_kw(self, *words: str) -> bool:
        return self.peek().is_kw(*words)

    def accept_kw(self, *words: str) -> bool:
        if self.at_kw(*words):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str):
        if not self.accept_kw(word):
            self.error()

    def at_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok.kind == OP and tok.value in ops

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str):
        if not self.accept_op(op):
            self.error()

    def at_identifier(self) -> bool:
        tok = self.peek()
        return tok.kind == QID or (tok.kind == ID and tok.upper not in RESERVED)

    def identifier(self) -> str:
        if not self.at_identifier():
            self.error()
        return self.advance().value

    # ---- statements ----

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
            self.error()
        self.accept_op(";")
        if self.peek().kind != EOF:
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
            while self.peek().kind == ID and not self.at_kw(*RESERVED):
                type_words.append(self.advance().value)
            if type_words and self.accept_op("("):
                self.parse_signed_number()
                if self.accept_op(","):
                    self.parse_signed_number()
                self.expect_op(")")
            columns.append((col, " ".join(type_words)))
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return ast.CreateTable(name, columns, if_not_exists)

    def parse_signed_number(self):
        if self.at_op("+", "-"):
            self.advance()
        if self.peek().kind != NUM:
            self.error()
        self.advance()

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
            return ast.Insert(table, columns, None, self.parse_select())
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
        return ast.Insert(table, columns, rows)

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
        sel = ast.Select(items=[])
        if self.accept_kw("DISTINCT"):
            sel.distinct = True
        else:
            self.accept_kw("ALL")
        sel.items.append(self.parse_select_item())
        while self.accept_op(","):
            sel.items.append(self.parse_select_item())
        if self.accept_kw("FROM"):
            sel.from_ = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    sel.joins.append(ast.Join("INNER", self.parse_table_ref(), None))
                    continue
                if self.accept_kw("LEFT"):
                    self.accept_kw("OUTER")
                    kind = "LEFT"
                elif self.accept_kw("INNER") or self.accept_kw("CROSS"):
                    kind = "INNER"
                elif self.at_kw("JOIN"):
                    kind = "INNER"
                else:
                    break
                self.expect_kw("JOIN")
                table = self.parse_table_ref()
                on = self.parse_expr() if self.accept_kw("ON") else None
                sel.joins.append(ast.Join(kind, table, on))
        if self.accept_kw("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            sel.group_by = self.parse_expr_list()
        if self.accept_kw("HAVING"):
            sel.having = self.parse_expr()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                expr = self.parse_expr()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                sel.order_by.append(ast.OrderItem(expr, desc))
                if not self.accept_op(","):
                    break
        if self.accept_kw("LIMIT"):
            sel.limit = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.offset = self.parse_expr()
            elif self.accept_op(","):
                sel.offset = sel.limit
                sel.limit = self.parse_expr()
        return sel

    def parse_select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(None)
        if (
            self.at_identifier()
            and self.peek(1).kind == OP
            and self.peek(1).value == "."
            and self.peek(2).kind == OP
            and self.peek(2).value == "*"
        ):
            table = self.advance().value
            self.advance()
            self.advance()
            return ast.SelectItem(None, star_table=table)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            if self.peek().kind == STR:
                alias = self.advance().value
            else:
                alias = self.identifier()
        elif self.at_identifier() or self.peek().kind == STR:
            alias = self.advance().value
        return ast.SelectItem(expr, alias)

    def parse_table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.at_identifier():
            alias = self.advance().value
        return ast.TableRef(name, alias)

    def parse_expr_list(self) -> list[ast.Expr]:
        items = [self.parse_expr()]
        while self.accept_op(","):
            items.append(self.parse_expr())
        return items

    # ---- expressions (lowest to highest precedence) ----

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
        left = self.parse_comparison()
        while True:
            if self.at_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ast.Binary(op, left, self.parse_comparison())
            elif self.accept_kw("IS"):
                op = "IS NOT" if self.accept_kw("NOT") else "IS"
                left = ast.Binary(op, left, self.parse_comparison())
            elif self.accept_kw("ISNULL"):
                left = ast.Binary("IS", left, ast.Literal(None))
            elif self.accept_kw("NOTNULL"):
                left = ast.Binary("IS NOT", left, ast.Literal(None))
            elif self.at_kw("NOT") and self.peek(1).is_kw("NULL"):
                self.advance()
                self.advance()
                left = ast.Binary("IS NOT", left, ast.Literal(None))
            elif self.at_kw("IN", "LIKE", "BETWEEN") or (
                self.at_kw("NOT") and self.peek(1).is_kw("IN", "LIKE", "BETWEEN")
            ):
                negated = self.accept_kw("NOT")
                kw = self.advance().value.upper()
                if kw == "IN":
                    self.expect_op("(")
                    items = [] if self.at_op(")") else self.parse_expr_list()
                    self.expect_op(")")
                    left = ast.InList(left, items, negated)
                elif kw == "LIKE":
                    left = ast.Like(left, self.parse_comparison(), negated)
                else:
                    low = self.parse_comparison()
                    self.expect_kw("AND")
                    high = self.parse_comparison()
                    left = ast.Between(left, low, high, negated)
            else:
                return left

    def parse_comparison(self) -> ast.Expr:
        left = self.parse_additive()
        while self.at_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> ast.Expr:
        left = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> ast.Expr:
        left = self.parse_concat()
        while self.at_op("*", "/", "%"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> ast.Expr:
        left = self.parse_unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> ast.Expr:
        if self.at_op("-", "+"):
            op = self.advance().value
            operand = self.parse_unary()
            if op == "-" and isinstance(operand, ast.Literal) and operand.value == INT_MAX + 1:
                return ast.Literal(-(INT_MAX + 1))
            return ast.Unary(op, operand)
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        tok = self.peek()
        if tok.kind == NUM:
            self.advance()
            text = tok.value
            if "." in text or "e" in text or "E" in text:
                return ast.Literal(float(text))
            value = int(text)
            # Keep INT_MAX + 1 exact so that a leading minus can form INT_MIN.
            return ast.Literal(value if value <= INT_MAX + 1 else float(value))
        if tok.kind == STR:
            self.advance()
            return ast.Literal(tok.value)
        if self.accept_op("("):
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.is_kw("NULL"):
            self.advance()
            return ast.Literal(None)
        if tok.is_kw("CASE"):
            return self.parse_case()
        if tok.is_kw("CAST"):
            self.advance()
            self.expect_op("(")
            expr = self.parse_expr()
            self.expect_kw("AS")
            words = []
            while self.peek().kind == ID:
                words.append(self.advance().value)
            if not words:
                self.error()
            if self.accept_op("("):
                self.parse_signed_number()
                if self.accept_op(","):
                    self.parse_signed_number()
                self.expect_op(")")
            self.expect_op(")")
            return ast.Cast(expr, " ".join(words))
        if tok.kind == ID and self.peek(1).kind == OP and self.peek(1).value == "(":
            if tok.upper in RESERVED:
                self.error()
            return self.parse_function()
        if self.at_identifier():
            self.advance()
            if self.accept_op("."):
                name_tok = self.peek()
                name = self.identifier()
                return ast.Column(tok.value, name, quoted=name_tok.kind == QID)
            return ast.Column(None, tok.value, quoted=tok.kind == QID)
        self.error()

    def parse_function(self) -> ast.Func:
        name = self.advance().value.upper()
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.Func(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        args = [] if self.at_op(")") else self.parse_expr_list()
        self.expect_op(")")
        return ast.Func(name, args, distinct=distinct)

    def parse_case(self) -> ast.Case:
        self.expect_kw("CASE")
        base = None if self.at_kw("WHEN") else self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return ast.Case(base, whens, else_)

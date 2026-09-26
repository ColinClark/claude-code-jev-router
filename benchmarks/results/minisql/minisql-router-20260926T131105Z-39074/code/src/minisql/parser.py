"""Recursive-descent parser producing :mod:`minisql.ast` nodes.

Binary operator precedence follows SQLite, from loosest to tightest::

    OR
    AND
    NOT (prefix)
    = == != <> IS [NOT] IN LIKE BETWEEN ISNULL NOTNULL
    < <= > >=
    + -
    * / %
    ||
    unary - +
"""

from __future__ import annotations

from . import ast
from .errors import SQLError
from .tokenizer import Token, TokenKind, tokenize

COMPARISON_OPS = ("<", "<=", ">", ">=")
EQUALITY_OPS = ("=", "==", "!=", "<>")


def parse(sql: str) -> ast.Statement:
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ utilities

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        if token.kind is not TokenKind.EOF:
            self.pos += 1
        return token

    def error(self, message: str | None = None) -> SQLError:
        token = self.tok
        if message is None:
            near = "end of input" if token.kind is TokenKind.EOF else repr(str(token.value))
            message = f"syntax error near {near}"
        return SQLError(message)

    def accept_keyword(self, *words: str) -> bool:
        if self.tok.is_keyword(*words):
            self.advance()
            return True
        return False

    def expect_keyword(self, word: str) -> None:
        if not self.accept_keyword(word):
            raise self.error()

    def accept_op(self, *ops: str) -> bool:
        if self.tok.is_op(*ops):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def identifier(self) -> str:
        token = self.tok
        if token.kind is not TokenKind.IDENT:
            raise self.error()
        self.advance()
        return str(token.value).lower()

    # ----------------------------------------------------------- statements

    def parse_statement(self) -> ast.Statement:
        token = self.tok
        if token.is_keyword("SELECT"):
            stmt: ast.Statement = self.parse_select()
        elif token.is_keyword("INSERT"):
            stmt = self.parse_insert()
        elif token.is_keyword("UPDATE"):
            stmt = self.parse_update()
        elif token.is_keyword("DELETE"):
            stmt = self.parse_delete()
        elif token.is_keyword("CREATE"):
            stmt = self.parse_create()
        elif token.is_keyword("DROP"):
            stmt = self.parse_drop()
        else:
            raise self.error()
        self.accept_op(";")
        if self.tok.kind is not TokenKind.EOF:
            raise self.error()
        return stmt

    def parse_create(self) -> ast.CreateTable:
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        if_not_exists = False
        if self.accept_keyword("IF"):
            self.expect_keyword("NOT")
            self.expect_keyword("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        columns = [self.parse_column_def()]
        while self.accept_op(","):
            columns.append(self.parse_column_def())
        self.expect_op(")")
        return ast.CreateTable(name, tuple(columns), if_not_exists)

    def parse_column_def(self) -> ast.ColumnDef:
        name = self.identifier()
        words: list[str] = []
        while self.tok.kind is TokenKind.IDENT:
            words.append(str(self.advance().value))
        if words and self.accept_op("("):
            # Size arguments such as VARCHAR(20) or DECIMAL(10, 2) are ignored.
            self.parse_signed_number()
            if self.accept_op(","):
                self.parse_signed_number()
            self.expect_op(")")
        return ast.ColumnDef(name, " ".join(words).upper())

    def parse_signed_number(self) -> None:
        self.accept_op("+", "-")
        if self.tok.kind not in (TokenKind.INTEGER, TokenKind.REAL):
            raise self.error()
        self.advance()

    def parse_drop(self) -> ast.DropTable:
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        if_exists = False
        if self.accept_keyword("IF"):
            self.expect_keyword("EXISTS")
            if_exists = True
        return ast.DropTable(self.identifier(), if_exists)

    def parse_insert(self) -> ast.Insert:
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.identifier()
        columns: tuple[str, ...] | None = None
        if self.accept_op("("):
            names = [self.identifier()]
            while self.accept_op(","):
                names.append(self.identifier())
            self.expect_op(")")
            columns = tuple(names)
        self.expect_keyword("VALUES")
        rows = [self.parse_value_row()]
        while self.accept_op(","):
            rows.append(self.parse_value_row())
        return ast.Insert(table, columns, tuple(rows))

    def parse_value_row(self) -> tuple[ast.Expr, ...]:
        self.expect_op("(")
        values = self.parse_expr_list()
        self.expect_op(")")
        return values

    def parse_update(self) -> ast.Update:
        self.expect_keyword("UPDATE")
        table = self.identifier()
        self.expect_keyword("SET")
        assignments = [self.parse_assignment()]
        while self.accept_op(","):
            assignments.append(self.parse_assignment())
        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        return ast.Update(table, tuple(assignments), where)

    def parse_assignment(self) -> tuple[str, ast.Expr]:
        name = self.identifier()
        self.expect_op("=")
        return name, self.parse_expr()

    def parse_delete(self) -> ast.Delete:
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.identifier()
        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        return ast.Delete(table, where)

    # --------------------------------------------------------------- SELECT

    def parse_select(self) -> ast.Select:
        self.expect_keyword("SELECT")
        distinct = False
        if self.accept_keyword("DISTINCT"):
            distinct = True
        else:
            self.accept_keyword("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())

        source: ast.TableRef | None = None
        joins: list[ast.Join] = []
        if self.accept_keyword("FROM"):
            source = self.parse_table_ref()
            while (join := self.parse_join()) is not None:
                joins.append(join)

        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        group_by: tuple[ast.Expr, ...] = ()
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by = self.parse_expr_list()
        having = self.parse_expr() if self.accept_keyword("HAVING") else None

        order_by: list[ast.OrderItem] = []
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by.append(self.parse_order_item())
            while self.accept_op(","):
                order_by.append(self.parse_order_item())

        limit = offset = None
        if self.accept_keyword("LIMIT"):
            limit = self.parse_expr()
            if self.accept_keyword("OFFSET"):
                offset = self.parse_expr()
            elif self.accept_op(","):
                # SQLite's "LIMIT offset, count" form.
                offset, limit = limit, self.parse_expr()

        return ast.Select(
            items=tuple(items),
            distinct=distinct,
            source=source,
            joins=tuple(joins),
            where=where,
            group_by=group_by,
            having=having,
            order_by=tuple(order_by),
            limit=limit,
            offset=offset,
        )

    def parse_select_item(self) -> ast.SelectItem | ast.Star:
        if self.accept_op("*"):
            return ast.Star(None)
        if self.tok.kind is TokenKind.IDENT and self.peek().is_op(".") and self.peek(2).is_op("*"):
            table = self.identifier()
            self.advance()
            self.advance()
            return ast.Star(table)
        expr = self.parse_expr()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.identifier_or_string()
        elif self.tok.kind is TokenKind.IDENT:
            alias = self.identifier()
        return ast.SelectItem(expr, alias)

    def identifier_or_string(self) -> str:
        if self.tok.kind is TokenKind.STRING:
            return str(self.advance().value).lower()
        return self.identifier()

    def parse_table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = name
        if self.accept_keyword("AS") or self.tok.kind is TokenKind.IDENT:
            alias = self.identifier()
        return ast.TableRef(name, alias)

    def parse_join(self) -> ast.Join | None:
        if self.accept_op(","):
            return ast.Join("CROSS", self.parse_table_ref(), None)
        if self.accept_keyword("CROSS"):
            self.expect_keyword("JOIN")
            return ast.Join("CROSS", self.parse_table_ref(), None)
        if self.accept_keyword("LEFT"):
            self.accept_keyword("OUTER")
            self.expect_keyword("JOIN")
            kind = "LEFT"
        elif self.accept_keyword("INNER"):
            self.expect_keyword("JOIN")
            kind = "INNER"
        elif self.accept_keyword("JOIN"):
            kind = "INNER"
        else:
            return None
        table = self.parse_table_ref()
        condition = self.parse_expr() if self.accept_keyword("ON") else None
        return ast.Join(kind, table, condition)

    def parse_order_item(self) -> ast.OrderItem:
        expr = self.parse_expr()
        descending = False
        if self.accept_keyword("DESC"):
            descending = True
        else:
            self.accept_keyword("ASC")
        return ast.OrderItem(expr, descending)

    # ----------------------------------------------------------- expressions

    def parse_expr_list(self) -> tuple[ast.Expr, ...]:
        exprs = [self.parse_expr()]
        while self.accept_op(","):
            exprs.append(self.parse_expr())
        return tuple(exprs)

    def parse_expr(self) -> ast.Expr:
        return self.parse_or()

    def parse_or(self) -> ast.Expr:
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = ast.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> ast.Expr:
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = ast.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> ast.Expr:
        if self.accept_keyword("NOT"):
            return ast.Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> ast.Expr:
        left = self.parse_comparison()
        while True:
            token = self.tok
            if token.is_op(*EQUALITY_OPS):
                self.advance()
                op = "=" if token.value == "==" else ("!=" if token.value == "<>" else token.value)
                left = ast.Binary(str(op), left, self.parse_comparison())
            elif token.is_keyword("IS"):
                self.advance()
                if self.accept_keyword("NOT"):
                    left = self.parse_is_rhs(left, negated=True)
                else:
                    left = self.parse_is_rhs(left, negated=False)
            elif token.is_keyword("ISNULL"):
                self.advance()
                left = ast.IsNull(left, negated=False)
            elif token.is_keyword("NOTNULL"):
                self.advance()
                left = ast.IsNull(left, negated=True)
            elif token.is_keyword("NOT") and self.peek().is_keyword("NULL"):
                self.advance()
                self.advance()
                left = ast.IsNull(left, negated=True)
            elif token.is_keyword("NOT") and self.peek().is_keyword("IN", "LIKE", "BETWEEN"):
                self.advance()
                left = self.parse_postfix_predicate(left, negated=True)
            elif token.is_keyword("IN", "LIKE", "BETWEEN"):
                left = self.parse_postfix_predicate(left, negated=False)
            else:
                return left

    def parse_is_rhs(self, left: ast.Expr, negated: bool) -> ast.Expr:
        if self.accept_keyword("NULL"):
            return ast.IsNull(left, negated=negated)
        right = self.parse_comparison()
        return ast.Binary("IS NOT" if negated else "IS", left, right)

    def parse_postfix_predicate(self, left: ast.Expr, negated: bool) -> ast.Expr:
        if self.accept_keyword("IN"):
            self.expect_op("(")
            items: tuple[ast.Expr, ...] = ()
            if not self.tok.is_op(")"):
                if self.tok.is_keyword("SELECT"):
                    raise self.error("subqueries are not supported")
                items = self.parse_expr_list()
            self.expect_op(")")
            return ast.InList(left, items, negated)
        if self.accept_keyword("LIKE"):
            return ast.Like(left, self.parse_comparison(), negated)
        self.expect_keyword("BETWEEN")
        low = self.parse_comparison()
        self.expect_keyword("AND")
        high = self.parse_comparison()
        return ast.Between(left, low, high, negated)

    def parse_comparison(self) -> ast.Expr:
        left = self.parse_additive()
        while self.tok.is_op(*COMPARISON_OPS):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> ast.Expr:
        left = self.parse_multiplicative()
        while self.tok.is_op("+", "-"):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> ast.Expr:
        left = self.parse_concat()
        while self.tok.is_op("*", "/", "%"):
            op = str(self.advance().value)
            left = ast.Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> ast.Expr:
        left = self.parse_unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> ast.Expr:
        if self.accept_op("-"):
            return ast.Unary("-", self.parse_unary())
        if self.accept_op("+"):
            return ast.Unary("+", self.parse_unary())
        if self.tok.is_keyword("NOT"):
            return self.parse_not()
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        token = self.tok
        kind = token.kind
        if kind in (TokenKind.INTEGER, TokenKind.REAL, TokenKind.STRING):
            self.advance()
            return ast.Literal(token.value)
        if token.is_keyword("NULL"):
            self.advance()
            return ast.Literal(None)
        if token.is_op("("):
            self.advance()
            if self.tok.is_keyword("SELECT"):
                raise self.error("subqueries are not supported")
            inner = self.parse_expr()
            self.expect_op(")")
            return ast.Paren(inner)
        if kind is TokenKind.IDENT:
            name = self.identifier()
            if self.tok.is_op("("):
                return self.parse_call(name)
            if self.accept_op("."):
                return ast.ColumnRef(name, self.identifier())
            return ast.ColumnRef(None, name)
        raise self.error()

    def parse_call(self, name: str) -> ast.FuncCall:
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.FuncCall(name, (), star=True)
        distinct = self.accept_keyword("DISTINCT")
        if not distinct:
            self.accept_keyword("ALL")
        args: tuple[ast.Expr, ...] = ()
        if not self.tok.is_op(")"):
            args = self.parse_expr_list()
        self.expect_op(")")
        return ast.FuncCall(name, args, distinct=distinct)

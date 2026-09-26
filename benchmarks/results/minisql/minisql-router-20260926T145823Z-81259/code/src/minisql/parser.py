"""Recursive-descent parser producing the syntax tree in :mod:`minisql.ast`."""

from . import ast
from .errors import SQLError
from .tokenizer import Token, tokenize

# Words that can never be used as a bare identifier or implicit alias.
RESERVED = frozenset(
    """
    ADD ALL AND AS ASC BETWEEN BY CASE CAST CREATE CROSS DELETE DESC DISTINCT DROP ELSE END
    EXISTS FROM FULL GROUP HAVING IN INNER INSERT INTO IS ISNULL JOIN LEFT LIMIT LIKE NOT
    NOTNULL NULL NULLS OFFSET ON OR ORDER OUTER RIGHT SELECT SET TABLE THEN UNION UPDATE
    USING VALUES WHEN WHERE
    """.split()
)

COMPARISON_OPS = ("<", "<=", ">", ">=")
EQUALITY_OPS = ("=", "==", "!=", "<>")


def type_affinity(type_name: str) -> str:
    """Map a declared column type to its SQLite affinity."""
    t = type_name.upper()
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if "BLOB" in t or not t:
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    return "NUMERIC"


def parse(sql: str):
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ helpers

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, tok: Token | None = None) -> SQLError:
        tok = tok or self.tok
        if tok.kind == "eof":
            return SQLError("incomplete input")
        return SQLError(f'near "{tok.value}": syntax error')

    @staticmethod
    def is_kw(tok: Token, *words: str) -> bool:
        return tok.kind == "id" and tok.value.upper() in words

    def at_kw(self, *words: str) -> bool:
        return self.is_kw(self.tok, *words)

    def accept_kw(self, *words: str) -> bool:
        if self.at_kw(*words):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
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

    def at_identifier(self) -> bool:
        tok = self.tok
        return tok.kind == "qid" or (tok.kind == "id" and tok.value.upper() not in RESERVED)

    def identifier(self) -> str:
        if not self.at_identifier():
            raise self.error()
        return self.advance().value.lower()

    # ------------------------------------------------------------ statements

    def parse_statement(self):
        if self.at_kw("SELECT"):
            stmt = self.parse_select()
        elif self.at_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.at_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.at_kw("DELETE"):
            stmt = self.parse_delete()
        elif self.at_kw("CREATE"):
            stmt = self.parse_create()
        elif self.at_kw("DROP"):
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
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        columns = []
        while True:
            col_name = self.identifier()
            type_words = []
            while self.tok.kind == "id" and self.tok.value.upper() not in RESERVED:
                type_words.append(self.advance().value)
            if type_words and self.accept_op("("):
                # Size arguments such as VARCHAR(10) are accepted and ignored.
                while not self.accept_op(")"):
                    if self.tok.kind == "eof":
                        raise self.error()
                    self.advance()
            columns.append(ast.ColumnDef(col_name, type_affinity(" ".join(type_words))))
            if self.accept_op(")"):
                break
            self.expect_op(",")
        return ast.CreateTable(name, columns, if_not_exists)

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
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        select = ast.Select(items, distinct)

        if self.accept_kw("FROM"):
            select.from_table = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    select.joins.append(ast.Join("INNER", self.parse_table_ref(), None))
                    continue
                kind = None
                if self.accept_kw("LEFT"):
                    self.accept_kw("OUTER")
                    kind = "LEFT"
                elif self.accept_kw("INNER"):
                    kind = "INNER"
                elif self.accept_kw("CROSS"):
                    kind = "CROSS"
                elif self.at_kw("JOIN"):
                    kind = "INNER"
                if kind is None:
                    break
                self.expect_kw("JOIN")
                table = self.parse_table_ref()
                on = None
                if self.accept_kw("ON"):
                    on = self.parse_expr()
                elif kind == "LEFT":
                    raise self.error()
                select.joins.append(ast.Join("LEFT" if kind == "LEFT" else "INNER", table, on))

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
            select.order_by = [self.parse_order_term()]
            while self.accept_op(","):
                select.order_by.append(self.parse_order_term())
        if self.accept_kw("LIMIT"):
            select.limit = self.parse_expr()
            if self.accept_kw("OFFSET"):
                select.offset = self.parse_expr()
            elif self.accept_op(","):
                # "LIMIT offset, count"
                select.offset = select.limit
                select.limit = self.parse_expr()
        return select

    def parse_select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(None, is_star=True)
        if (
            self.tok.kind in ("id", "qid")
            and self.peek().kind == "op"
            and self.peek().value == "."
            and self.peek(2).kind == "op"
            and self.peek(2).value == "*"
        ):
            table = self.identifier()
            self.advance()
            self.advance()
            return ast.SelectItem(None, star_table=table, is_star=True)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            alias = self.alias_name()
        elif self.at_identifier() or self.tok.kind == "str":
            alias = self.alias_name()
        return ast.SelectItem(expr, alias)

    def alias_name(self) -> str:
        if self.tok.kind == "str":
            return self.advance().value.lower()
        return self.identifier()

    def parse_table_ref(self) -> ast.TableRef:
        name = self.identifier()
        alias = name
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.at_identifier():
            alias = self.identifier()
        return ast.TableRef(name, alias)

    def parse_order_term(self) -> ast.OrderTerm:
        expr = self.parse_expr()
        descending = False
        if self.accept_kw("DESC"):
            descending = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        if self.accept_kw("NULLS"):
            if self.accept_kw("FIRST"):
                nulls_first = True
            else:
                self.expect_kw("LAST")
                nulls_first = False
        return ast.OrderTerm(expr, descending, nulls_first)

    # ------------------------------------------------------------ expressions
    # Precedence, lowest first: OR; AND; NOT; = == != <> IS IN LIKE BETWEEN;
    # < <= > >=; + -; * / %; ||; unary - +.

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
            if self.at_op(*EQUALITY_OPS):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = ast.Binary(op, left, self.parse_comparison())
            elif self.accept_kw("ISNULL"):
                left = ast.IsNull(left, False)
            elif self.accept_kw("NOTNULL"):
                left = ast.IsNull(left, True)
            elif self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                if self.accept_kw("NULL"):
                    left = ast.IsNull(left, negated)
                else:
                    right = self.parse_comparison()
                    left = ast.Binary("IS NOT" if negated else "IS", left, right)
            elif self.at_kw("NOT") and self.is_kw(self.peek(), "NULL"):
                self.advance()
                self.advance()
                left = ast.IsNull(left, True)
            elif self.at_kw("IN", "LIKE", "BETWEEN") or (
                self.at_kw("NOT") and self.is_kw(self.peek(), "IN", "LIKE", "BETWEEN")
            ):
                negated = self.accept_kw("NOT")
                word = self.advance().value.upper()
                if word == "IN":
                    left = ast.InList(left, self.parse_in_list(), negated)
                elif word == "LIKE":
                    left = ast.Like(left, self.parse_comparison(), negated)
                else:
                    low = self.parse_comparison()
                    self.expect_kw("AND")
                    high = self.parse_comparison()
                    left = ast.Between(left, low, high, negated)
            else:
                return left

    def parse_in_list(self) -> list[ast.Expr]:
        self.expect_op("(")
        items: list[ast.Expr] = []
        if self.accept_op(")"):
            return items
        if self.at_kw("SELECT"):
            raise SQLError("subqueries are not supported")
        items.append(self.parse_expr())
        while self.accept_op(","):
            items.append(self.parse_expr())
        self.expect_op(")")
        return items

    def parse_comparison(self) -> ast.Expr:
        left = self.parse_additive()
        while self.at_op(*COMPARISON_OPS):
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
            if op == "-" and isinstance(operand, ast.Literal) and operand.value == 2**63:
                return ast.Literal(-(2**63))
            return ast.Unary(op, operand)
        return self.parse_primary()

    def parse_primary(self) -> ast.Expr:
        tok = self.tok
        if tok.kind == "num":
            self.advance()
            return ast.Literal(tok.value)
        if tok.kind == "str":
            self.advance()
            return ast.Literal(tok.value)
        if self.accept_op("("):
            if self.at_kw("SELECT"):
                raise SQLError("subqueries are not supported")
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if self.accept_kw("NULL"):
            return ast.Literal(None)
        if self.accept_kw("CAST"):
            self.expect_op("(")
            operand = self.parse_expr()
            self.expect_kw("AS")
            type_words = []
            while self.tok.kind == "id" and not self.at_kw("AS"):
                type_words.append(self.advance().value)
            self.expect_op(")")
            return ast.Cast(operand, type_affinity(" ".join(type_words)))
        if tok.kind == "id" and self.peek().kind == "op" and self.peek().value == "(":
            if tok.value.upper() in RESERVED:
                raise self.error()
            return self.parse_function()
        if self.at_identifier():
            name = self.identifier()
            if self.accept_op("."):
                return ast.Column(name, self.identifier())
            return ast.Column(None, name)
        raise self.error()

    def parse_function(self) -> ast.Func:
        name = self.advance().value.lower()
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.Func(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        args: list[ast.Expr] = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return ast.Func(name, args, distinct)

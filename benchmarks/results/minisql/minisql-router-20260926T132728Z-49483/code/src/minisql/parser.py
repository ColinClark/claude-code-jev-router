"""Recursive-descent parser producing :mod:`minisql.nodes` ASTs.

Expression precedence (lowest to highest), following SQLite:

    OR
    AND
    NOT (prefix)
    = == != <> IS [NOT] [NOT] IN [NOT] LIKE [NOT] GLOB [NOT] BETWEEN ISNULL NOTNULL
    < <= > >=
    & | << >>
    + -
    * / %
    ||
    unary - + ~
"""

from __future__ import annotations

from .errors import SQLError
from .lexer import EOF, FLOAT, IDENT, INTEGER, KEYWORD, OP, STRING, Token, tokenize
from .nodes import (
    Between,
    BinaryOp,
    Case,
    Cast,
    ColumnDef,
    ColumnRef,
    CreateTable,
    Delete,
    DropTable,
    Expr,
    ExprItem,
    FunctionCall,
    InList,
    Insert,
    IsNull,
    Join,
    Like,
    Literal,
    OrderItem,
    Select,
    SelectItem,
    StarItem,
    Statement,
    TableRef,
    UnaryOp,
    Update,
)


def parse(sql: str) -> Statement:
    """Parse exactly one SQL statement (an optional trailing ';' is allowed)."""
    return Parser(tokenize(sql)).parse_single()


def parse_expression(sql: str) -> Expr:
    """Parse a standalone expression (useful for tests)."""
    p = Parser(tokenize(sql))
    expr = p.parse_expr()
    p.expect_eof()
    return expr


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers -----------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != EOF:
            self.pos += 1
        return tok

    def error(self, tok: Token | None = None) -> SQLError:
        tok = tok or self.tok
        if tok.kind == EOF:
            return SQLError("incomplete input")
        return SQLError(f'near "{tok.text}": syntax error')

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

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error()

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def expect_ident(self) -> str:
        tok = self.tok
        if tok.kind == IDENT:
            self.advance()
            return tok.value  # type: ignore[return-value]
        # SQLite allows string literals as identifiers in some positions.
        if tok.kind == STRING:
            self.advance()
            return tok.value  # type: ignore[return-value]
        raise self.error()

    def expect_eof(self) -> None:
        while self.accept_op(";"):
            pass
        if self.tok.kind != EOF:
            raise self.error()

    # -- statements ----------------------------------------------------------

    def parse_single(self) -> Statement:
        while self.accept_op(";"):
            pass
        if self.tok.kind == EOF:
            raise SQLError("empty statement")
        stmt = self.parse_statement()
        self.expect_eof()
        return stmt

    def parse_statement(self) -> Statement:
        if self.is_kw("SELECT"):
            return self.parse_select()
        if self.is_kw("CREATE"):
            return self.parse_create()
        if self.is_kw("DROP"):
            return self.parse_drop()
        if self.is_kw("INSERT"):
            return self.parse_insert()
        if self.is_kw("UPDATE"):
            return self.parse_update()
        if self.is_kw("DELETE"):
            return self.parse_delete()
        raise self.error()

    def parse_create(self) -> CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.expect_ident()
        self.expect_op("(")
        cols: list[ColumnDef] = []
        while True:
            col_name = self.expect_ident()
            type_parts: list[str] = []
            while self.tok.kind == IDENT:
                type_parts.append(self.advance().text)
            type_name = " ".join(type_parts)
            if self.accept_op("("):
                args = [self.parse_signed_number_text()]
                if self.accept_op(","):
                    args.append(self.parse_signed_number_text())
                self.expect_op(")")
                type_name += "(" + ",".join(args) + ")"
            cols.append(ColumnDef(col_name, type_name))
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return CreateTable(name, tuple(cols), if_not_exists)

    def parse_signed_number_text(self) -> str:
        sign = ""
        if self.is_op("+", "-"):
            sign = self.advance().value  # type: ignore[assignment]
        if self.tok.kind not in (INTEGER, FLOAT):
            raise self.error()
        return sign + self.advance().text

    def parse_drop(self) -> DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return DropTable(self.expect_ident(), if_exists)

    def parse_insert(self) -> Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.expect_ident()
        columns: tuple[str, ...] | None = None
        if self.accept_op("("):
            names = [self.expect_ident()]
            while self.accept_op(","):
                names.append(self.expect_ident())
            self.expect_op(")")
            columns = tuple(names)
        self.expect_kw("VALUES")
        rows: list[tuple[Expr, ...]] = []
        while True:
            self.expect_op("(")
            values = [self.parse_expr()]
            while self.accept_op(","):
                values.append(self.parse_expr())
            self.expect_op(")")
            rows.append(tuple(values))
            if not self.accept_op(","):
                break
        return Insert(table, columns, tuple(rows))

    def parse_update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.expect_ident()
        self.expect_kw("SET")
        assignments: list[tuple[str, Expr]] = []
        while True:
            col = self.expect_ident()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Update(table, tuple(assignments), where)

    def parse_delete(self) -> Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.expect_ident()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Delete(table, where)

    # -- SELECT ------------------------------------------------------------

    def parse_select(self) -> Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        columns = [self.parse_select_item()]
        while self.accept_op(","):
            columns.append(self.parse_select_item())

        from_table: TableRef | None = None
        joins: list[Join] = []
        if self.accept_kw("FROM"):
            from_table = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    joins.append(Join("CROSS", self.parse_table_ref()))
                    continue
                kind = None
                if self.is_kw("JOIN"):
                    kind = "INNER"
                elif self.is_kw("INNER"):
                    self.advance()
                    kind = "INNER"
                elif self.is_kw("CROSS"):
                    self.advance()
                    kind = "CROSS"
                elif self.is_kw("LEFT"):
                    self.advance()
                    self.accept_kw("OUTER")
                    kind = "LEFT"
                if kind is None:
                    break
                self.expect_kw("JOIN")
                table = self.parse_table_ref()
                on = self.parse_expr() if self.accept_kw("ON") else None
                if on is None and kind == "LEFT":
                    raise self.error()
                joins.append(Join(kind, table, on))

        where = self.parse_expr() if self.accept_kw("WHERE") else None

        group_by: list[Expr] = []
        having = None
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            group_by.append(self.parse_expr())
            while self.accept_op(","):
                group_by.append(self.parse_expr())
        if self.accept_kw("HAVING"):
            having = self.parse_expr()

        order_by: list[OrderItem] = []
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                expr = self.parse_expr()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                order_by.append(OrderItem(expr, desc))
                if not self.accept_op(","):
                    break

        limit = offset = None
        if self.accept_kw("LIMIT"):
            limit = self.parse_expr()
            if self.accept_kw("OFFSET"):
                offset = self.parse_expr()
            elif self.accept_op(","):
                # LIMIT <offset>, <count>
                offset, limit = limit, self.parse_expr()

        return Select(
            columns=tuple(columns),
            from_table=from_table,
            joins=tuple(joins),
            where=where,
            group_by=tuple(group_by),
            having=having,
            order_by=tuple(order_by),
            limit=limit,
            offset=offset,
            distinct=distinct,
        )

    def parse_select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return StarItem(None)
        if (
            self.tok.kind == IDENT
            and self.peek().kind == OP
            and self.peek().value == "."
            and self.peek(2).kind == OP
            and self.peek(2).value == "*"
        ):
            table = self.advance().value
            self.advance()
            self.advance()
            return StarItem(table)  # type: ignore[arg-type]
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            alias = self.expect_ident()
        elif self.tok.kind in (IDENT, STRING):
            alias = self.advance().value
        return ExprItem(expr, alias)  # type: ignore[arg-type]

    def parse_table_ref(self) -> TableRef:
        name = self.expect_ident()
        alias = None
        if self.accept_kw("AS"):
            alias = self.expect_ident()
        elif self.tok.kind == IDENT:
            alias = self.advance().value
        return TableRef(name, alias)  # type: ignore[arg-type]

    # -- expressions -------------------------------------------------------

    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = BinaryOp("OR", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = BinaryOp("AND", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.accept_kw("NOT"):
            return UnaryOp("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> Expr:
        left = self.parse_comparison()
        while True:
            if self.is_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)  # type: ignore[arg-type]
                left = BinaryOp(op, left, self.parse_comparison())  # type: ignore[arg-type]
                continue
            if self.accept_kw("ISNULL"):
                left = IsNull(left, False)
                continue
            if self.accept_kw("NOTNULL"):
                left = IsNull(left, True)
                continue
            if self.is_kw("IS"):
                self.advance()
                negated = self.accept_kw("NOT")
                if self.accept_kw("NULL"):
                    left = IsNull(left, negated)
                else:
                    right = self.parse_comparison()
                    left = BinaryOp("IS NOT" if negated else "IS", left, right)
                continue
            negated = False
            if self.is_kw("NOT") and self.peek().kind == KEYWORD and self.peek().value in (
                "IN", "LIKE", "GLOB", "BETWEEN", "NULL",
            ):
                self.advance()
                negated = True
                if self.accept_kw("NULL"):
                    left = IsNull(left, True)
                    continue
            if self.accept_kw("IN"):
                self.expect_op("(")
                items: list[Expr] = []
                if not self.is_op(")"):
                    items.append(self.parse_expr())
                    while self.accept_op(","):
                        items.append(self.parse_expr())
                self.expect_op(")")
                left = InList(left, tuple(items), negated)
                continue
            if self.is_kw("LIKE", "GLOB"):
                op = self.advance().value
                pattern = self.parse_comparison()
                escape = None
                if self.accept_kw("ESCAPE"):
                    escape = self.parse_comparison()
                left = Like(left, pattern, escape, negated, op)  # type: ignore[arg-type]
                continue
            if self.accept_kw("BETWEEN"):
                low = self.parse_comparison()
                self.expect_kw("AND")
                high = self.parse_comparison()
                left = Between(left, low, high, negated)
                continue
            if negated:
                raise self.error()
            return left

    def parse_comparison(self) -> Expr:
        left = self.parse_bitwise()
        while self.is_op("<", "<=", ">", ">="):
            op = self.advance().value
            left = BinaryOp(op, left, self.parse_bitwise())  # type: ignore[arg-type]
        return left

    def parse_bitwise(self) -> Expr:
        left = self.parse_additive()
        while self.is_op("&", "|", "<<", ">>"):
            op = self.advance().value
            left = BinaryOp(op, left, self.parse_additive())  # type: ignore[arg-type]
        return left

    def parse_additive(self) -> Expr:
        left = self.parse_multiplicative()
        while self.is_op("+", "-"):
            op = self.advance().value
            left = BinaryOp(op, left, self.parse_multiplicative())  # type: ignore[arg-type]
        return left

    def parse_multiplicative(self) -> Expr:
        left = self.parse_concat()
        while self.is_op("*", "/", "%"):
            op = self.advance().value
            left = BinaryOp(op, left, self.parse_concat())  # type: ignore[arg-type]
        return left

    def parse_concat(self) -> Expr:
        left = self.parse_unary()
        while self.is_op("||"):
            self.advance()
            left = BinaryOp("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        if self.is_op("-"):
            self.advance()
            # -9223372036854775808 is a valid integer literal.
            if self.tok.kind == FLOAT and self.tok.text == "9223372036854775808":
                self.advance()
                return Literal(-(2**63))
            return UnaryOp("-", self.parse_unary())
        if self.is_op("+"):
            self.advance()
            return UnaryOp("+", self.parse_unary())
        if self.is_op("~"):
            self.advance()
            return UnaryOp("~", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.tok
        if tok.kind in (INTEGER, FLOAT, STRING):
            self.advance()
            return Literal(tok.value)
        if tok.kind == KEYWORD:
            if tok.value == "NULL":
                self.advance()
                return Literal(None)
            if tok.value == "CASE":
                return self.parse_case()
            if tok.value == "CAST":
                return self.parse_cast()
            raise self.error()
        if tok.kind == OP and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind == IDENT:
            self.advance()
            name: str = tok.value  # type: ignore[assignment]
            if self.is_op("("):
                return self.parse_function_call(name)
            if self.accept_op("."):
                col = self.expect_ident()
                return ColumnRef(col, name)
            quoted = tok.text[:1] in ("\"", "`", "[")
            if not quoted and name.upper() in ("TRUE", "FALSE"):
                return Literal(1 if name.upper() == "TRUE" else 0)
            return ColumnRef(name)
        raise self.error()

    def parse_function_call(self, name: str) -> FunctionCall:
        self.expect_op("(")
        uname = name.upper()
        if self.accept_op("*"):
            self.expect_op(")")
            if uname != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name}()")
            return FunctionCall(uname, (), False, True)
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args: list[Expr] = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        elif distinct:
            raise self.error()
        self.expect_op(")")
        return FunctionCall(uname, tuple(args), distinct, False)

    def parse_case(self) -> Case:
        self.expect_kw("CASE")
        operand = None
        if not self.is_kw("WHEN"):
            operand = self.parse_expr()
        whens: list[tuple[Expr, Expr]] = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return Case(operand, tuple(whens), else_)

    def parse_cast(self) -> Cast:
        self.expect_kw("CAST")
        self.expect_op("(")
        operand = self.parse_expr()
        self.expect_kw("AS")
        parts: list[str] = []
        while self.tok.kind == IDENT:
            parts.append(self.advance().text)
        if not parts:
            raise self.error()
        type_name = " ".join(parts)
        if self.accept_op("("):
            args = [self.parse_signed_number_text()]
            if self.accept_op(","):
                args.append(self.parse_signed_number_text())
            self.expect_op(")")
            type_name += "(" + ",".join(args) + ")"
        self.expect_op(")")
        return Cast(operand, type_name)

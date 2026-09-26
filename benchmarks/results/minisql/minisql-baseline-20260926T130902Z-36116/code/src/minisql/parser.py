from __future__ import annotations

from .ast_nodes import (
    Between,
    BinaryOp,
    ColumnDef,
    ColumnRef,
    CreateTable,
    Delete,
    Expr,
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
    Star,
    TableRef,
    UnaryOp,
    Update,
)
from .errors import SQLError
from .lexer import Token, tokenize

_COMPARISON_OPS = {"=", "==", "!=", "<>", "<", "<=", ">", ">="}
_TYPE_NAMES = {"integer", "real", "text"}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---- token helpers ----

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _is_kw(self, kw: str) -> bool:
        tok = self._peek()
        return tok.kind == "KEYWORD" and tok.value == kw

    def _is_op(self, op: str) -> bool:
        tok = self._peek()
        return tok.kind == "OP" and tok.value == op

    def _eat_kw(self, kw: str) -> None:
        if not self._is_kw(kw):
            raise SQLError(f"Expected keyword {kw!r} at position {self._peek().pos}")
        self._advance()

    def _eat_op(self, op: str) -> None:
        if not self._is_op(op):
            raise SQLError(f"Expected {op!r} at position {self._peek().pos}")
        self._advance()

    def _eat_ident(self) -> str:
        tok = self._peek()
        if tok.kind != "IDENT":
            raise SQLError(f"Expected identifier at position {tok.pos}")
        self._advance()
        return tok.value

    def _try_kw(self, kw: str) -> bool:
        if self._is_kw(kw):
            self._advance()
            return True
        return False

    def _try_op(self, op: str) -> bool:
        if self._is_op(op):
            self._advance()
            return True
        return False

    def _name_or_kw_as_ident(self) -> str:
        """Accept an identifier, used for table/column/alias names."""
        tok = self._peek()
        if tok.kind == "IDENT":
            self._advance()
            return tok.value
        raise SQLError(f"Expected identifier at position {tok.pos}")

    # ---- top-level ----

    def parse_statement(self):
        if self._is_kw("select"):
            stmt = self.parse_select()
        elif self._is_kw("insert"):
            stmt = self.parse_insert()
        elif self._is_kw("update"):
            stmt = self.parse_update()
        elif self._is_kw("delete"):
            stmt = self.parse_delete()
        elif self._is_kw("create"):
            stmt = self.parse_create_table()
        else:
            raise SQLError(f"Unexpected token at position {self._peek().pos}")
        if self._peek().kind != "EOF":
            raise SQLError(f"Unexpected trailing tokens at position {self._peek().pos}")
        return stmt

    # ---- CREATE TABLE ----

    def parse_create_table(self) -> CreateTable:
        self._eat_kw("create")
        self._eat_kw("table")
        name = self._name_or_kw_as_ident()
        self._eat_op("(")
        columns = []
        while True:
            col_name = self._name_or_kw_as_ident()
            type_tok = self._peek()
            if type_tok.kind == "KEYWORD" and type_tok.value in _TYPE_NAMES:
                self._advance()
                col_type = type_tok.value.upper()
            else:
                raise SQLError(f"Expected column type at position {type_tok.pos}")
            columns.append(ColumnDef(col_name, col_type))
            if self._try_op(","):
                continue
            break
        self._eat_op(")")
        return CreateTable(name, columns)

    # ---- INSERT ----

    def parse_insert(self) -> Insert:
        self._eat_kw("insert")
        self._eat_kw("into")
        table = self._name_or_kw_as_ident()
        columns = None
        if self._is_op("("):
            self._advance()
            columns = [self._name_or_kw_as_ident()]
            while self._try_op(","):
                columns.append(self._name_or_kw_as_ident())
            self._eat_op(")")
        self._eat_kw("values")
        rows = [self._parse_value_tuple()]
        while self._try_op(","):
            rows.append(self._parse_value_tuple())
        return Insert(table, columns, rows)

    def _parse_value_tuple(self) -> list[Expr]:
        self._eat_op("(")
        values = [self.parse_expr()]
        while self._try_op(","):
            values.append(self.parse_expr())
        self._eat_op(")")
        return values

    # ---- UPDATE ----

    def parse_update(self) -> Update:
        self._eat_kw("update")
        table = self._name_or_kw_as_ident()
        self._eat_kw("set")
        assignments = [self._parse_assignment()]
        while self._try_op(","):
            assignments.append(self._parse_assignment())
        where = None
        if self._try_kw("where"):
            where = self.parse_expr()
        return Update(table, assignments, where)

    def _parse_assignment(self) -> tuple[str, Expr]:
        col = self._name_or_kw_as_ident()
        self._eat_op("=")
        value = self.parse_expr()
        return (col, value)

    # ---- DELETE ----

    def parse_delete(self) -> Delete:
        self._eat_kw("delete")
        self._eat_kw("from")
        table = self._name_or_kw_as_ident()
        where = None
        if self._try_kw("where"):
            where = self.parse_expr()
        return Delete(table, where)

    # ---- SELECT ----

    def parse_select(self) -> Select:
        self._eat_kw("select")
        distinct = self._try_kw("distinct")
        items = [self._parse_select_item()]
        while self._try_op(","):
            items.append(self._parse_select_item())
        self._eat_kw("from")
        from_table = self._parse_table_ref()
        joins = []
        while True:
            kind = None
            if self._try_kw("inner"):
                self._eat_kw("join")
                kind = "INNER"
            elif self._try_kw("left"):
                self._try_kw("outer")
                self._eat_kw("join")
                kind = "LEFT"
            elif self._try_kw("join"):
                kind = "INNER"
            else:
                break
            table = self._parse_table_ref()
            self._eat_kw("on")
            on_expr = self.parse_expr()
            joins.append(Join(kind, table, on_expr))

        where = None
        if self._try_kw("where"):
            where = self.parse_expr()

        group_by: list[Expr] = []
        if self._try_kw("group"):
            self._eat_kw("by")
            group_by.append(self.parse_expr())
            while self._try_op(","):
                group_by.append(self.parse_expr())

        having = None
        if self._try_kw("having"):
            having = self.parse_expr()

        order_by: list[OrderItem] = []
        if self._try_kw("order"):
            self._eat_kw("by")
            order_by.append(self._parse_order_item())
            while self._try_op(","):
                order_by.append(self._parse_order_item())

        limit = None
        offset = None
        if self._try_kw("limit"):
            limit = self._parse_int_literal()
            if self._try_kw("offset"):
                offset = self._parse_int_literal()

        return Select(
            distinct=distinct,
            items=items,
            from_table=from_table,
            joins=joins,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def _parse_int_literal(self) -> int:
        tok = self._peek()
        if tok.kind == "NUMBER" and isinstance(tok.value, int):
            self._advance()
            return tok.value
        raise SQLError(f"Expected integer literal at position {tok.pos}")

    def _parse_select_item(self) -> SelectItem:
        if self._is_op("*"):
            self._advance()
            return SelectItem(Star(), None)
        # alias.* lookahead
        if (
            self._peek().kind == "IDENT"
            and self.tokens[self.pos + 1].kind == "OP"
            and self.tokens[self.pos + 1].value == "."
            and self.tokens[self.pos + 2].kind == "OP"
            and self.tokens[self.pos + 2].value == "*"
        ):
            table = self._advance().value
            self._advance()
            self._advance()
            return SelectItem(Star(table), None)
        expr = self.parse_expr()
        alias = None
        if self._try_kw("as"):
            alias = self._name_or_kw_as_ident()
        elif self._peek().kind == "IDENT":
            alias = self._advance().value
        return SelectItem(expr, alias)

    def _parse_table_ref(self) -> TableRef:
        name = self._name_or_kw_as_ident()
        alias = None
        if self._try_kw("as"):
            alias = self._name_or_kw_as_ident()
        elif self._peek().kind == "IDENT":
            alias = self._advance().value
        return TableRef(name, alias)

    def _parse_order_item(self) -> OrderItem:
        expr = self.parse_expr()
        desc = False
        if self._try_kw("asc"):
            desc = False
        elif self._try_kw("desc"):
            desc = True
        return OrderItem(expr, desc)

    # ---- Expressions (precedence climbing) ----

    def parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._try_kw("or"):
            right = self._parse_and()
            left = BinaryOp("OR", left, right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while self._try_kw("and"):
            right = self._parse_not()
            left = BinaryOp("AND", left, right)
        return left

    def _parse_not(self) -> Expr:
        if self._try_kw("not"):
            operand = self._parse_not()
            return UnaryOp("NOT", operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_concat()
        while True:
            tok = self._peek()
            if tok.kind == "OP" and tok.value in _COMPARISON_OPS:
                self._advance()
                right = self._parse_concat()
                left = BinaryOp(tok.value, left, right)
                continue
            if self._is_kw("is"):
                self._advance()
                negated = self._try_kw("not")
                self._eat_kw("null")
                left = IsNull(left, negated)
                continue
            negated = False
            save = self.pos
            if self._try_kw("not"):
                if self._is_kw("in") or self._is_kw("between") or self._is_kw("like"):
                    negated = True
                else:
                    self.pos = save
                    break
            if self._try_kw("in"):
                self._eat_op("(")
                items = []
                if not self._is_op(")"):
                    items.append(self.parse_expr())
                    while self._try_op(","):
                        items.append(self.parse_expr())
                self._eat_op(")")
                left = InList(left, items, negated)
                continue
            if self._try_kw("between"):
                low = self._parse_concat()
                self._eat_kw("and")
                high = self._parse_concat()
                left = Between(left, low, high, negated)
                continue
            if self._try_kw("like"):
                pattern = self._parse_concat()
                left = Like(left, pattern, negated)
                continue
            break
        return left

    def _parse_concat(self) -> Expr:
        left = self._parse_additive()
        while self._is_op("||"):
            self._advance()
            right = self._parse_additive()
            left = BinaryOp("||", left, right)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok.kind == "OP" and tok.value in ("+", "-"):
                self._advance()
                right = self._parse_multiplicative()
                left = BinaryOp(tok.value, left, right)
            else:
                break
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while True:
            tok = self._peek()
            if tok.kind == "OP" and tok.value in ("*", "/", "%"):
                self._advance()
                right = self._parse_unary()
                left = BinaryOp(tok.value, left, right)
            else:
                break
        return left

    def _parse_unary(self) -> Expr:
        if self._is_op("-"):
            self._advance()
            operand = self._parse_unary()
            return UnaryOp("-", operand)
        if self._is_op("+"):
            self._advance()
            return self._parse_unary()
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            return Literal(tok.value)
        if tok.kind == "STRING":
            self._advance()
            return Literal(tok.value)
        if tok.kind == "KEYWORD" and tok.value == "null":
            self._advance()
            return Literal(None)
        if tok.kind == "KEYWORD" and tok.value == "true":
            self._advance()
            return Literal(1)
        if tok.kind == "KEYWORD" and tok.value == "false":
            self._advance()
            return Literal(0)
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            expr = self.parse_expr()
            self._eat_op(")")
            return expr
        if tok.kind == "IDENT":
            name = self._advance().value
            if self._is_op("."):
                self._advance()
                if self._is_op("*"):
                    self._advance()
                    return Star(name)
                colname = self._name_or_kw_as_ident()
                return ColumnRef(name, colname)
            if self._is_op("("):
                self._advance()
                distinct = False
                args: list[Expr] = []
                if name.lower() == "count" and self._is_op("*"):
                    self._advance()
                    args = [Star()]
                else:
                    if self._try_kw("distinct"):
                        distinct = True
                    if not self._is_op(")"):
                        args.append(self.parse_expr())
                        while self._try_op(","):
                            args.append(self.parse_expr())
                self._eat_op(")")
                return FunctionCall(name.lower(), args, distinct)
            return ColumnRef(None, name)
        raise SQLError(f"Unexpected token at position {tok.pos}")


def parse_sql(sql: str):
    tokens = tokenize(sql)
    parser = Parser(tokens)
    return parser.parse_statement()

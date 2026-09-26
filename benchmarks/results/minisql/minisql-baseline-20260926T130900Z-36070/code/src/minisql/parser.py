from __future__ import annotations

from .ast_nodes import (
    And,
    Assignment,
    Between,
    BinOp,
    ColumnDefAst,
    ColumnRef,
    CreateTable,
    Delete,
    FuncCall,
    InList,
    Insert,
    IsNull,
    JoinClause,
    Like,
    Literal,
    Not,
    Or,
    OrderTerm,
    Select,
    SelectItem,
    UnaryOp,
    Update,
)
from .errors import SQLError
from .lexer import Token, tokenize

_COMPARISON_OPS = {"=", "==", "!=", "<>", "<", "<=", ">", ">="}
_AGGREGATE_NAMES = {"count", "sum", "avg", "min", "max"}
_TYPE_NAMES = {"integer", "real", "text"}


class Parser:
    def __init__(self, sql: str):
        self.tokens: list[Token] = tokenize(sql)
        self.pos = 0

    # -- token helpers -----------------------------------------------------

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def _at_keyword(self, *kws: str) -> bool:
        tok = self._peek()
        return tok.kind == "keyword" and tok.value in kws

    def _at_op(self, *ops: str) -> bool:
        tok = self._peek()
        return tok.kind == "op" and tok.value in ops

    def _expect_keyword(self, kw: str) -> Token:
        tok = self._peek()
        if tok.kind != "keyword" or tok.value != kw:
            raise SQLError(f"Expected keyword {kw!r} near position {tok.pos}, found {tok.value!r}")
        return self._advance()

    def _expect_op(self, op: str) -> Token:
        tok = self._peek()
        if tok.kind != "op" or tok.value != op:
            raise SQLError(f"Expected {op!r} near position {tok.pos}, found {tok.value!r}")
        return self._advance()

    def _expect_ident(self) -> str:
        tok = self._peek()
        if tok.kind == "ident":
            self._advance()
            return tok.value
        if tok.kind == "keyword":
            # allow keywords to be used loosely as identifiers where unambiguous
            self._advance()
            return tok.value
        raise SQLError(f"Expected identifier near position {tok.pos}, found {tok.value!r}")

    # -- entry point ---------------------------------------------------------

    def parse_statement(self):
        if self._at_keyword("select"):
            stmt = self._parse_select()
        elif self._at_keyword("insert"):
            stmt = self._parse_insert()
        elif self._at_keyword("update"):
            stmt = self._parse_update()
        elif self._at_keyword("delete"):
            stmt = self._parse_delete()
        elif self._at_keyword("create"):
            stmt = self._parse_create_table()
        else:
            tok = self._peek()
            raise SQLError(f"Unrecognized statement near position {tok.pos}: {tok.value!r}")
        if self._at_op(";"):
            self._advance()
        tok = self._peek()
        if tok.kind != "eof":
            raise SQLError(f"Unexpected trailing input near position {tok.pos}: {tok.value!r}")
        return stmt

    # -- CREATE TABLE --------------------------------------------------------

    def _parse_create_table(self):
        self._expect_keyword("create")
        self._expect_keyword("table")
        name = self._expect_ident()
        self._expect_op("(")
        columns = []
        while True:
            col_name = self._expect_ident()
            type_tok = self._peek()
            if type_tok.kind != "keyword" or type_tok.value not in _TYPE_NAMES:
                raise SQLError(f"Expected column type near position {type_tok.pos}")
            self._advance()
            columns.append(ColumnDefAst(col_name, type_tok.value.upper()))
            if self._at_op(","):
                self._advance()
                continue
            break
        self._expect_op(")")
        return CreateTable(name, columns)

    # -- INSERT ---------------------------------------------------------------

    def _parse_insert(self):
        self._expect_keyword("insert")
        self._expect_keyword("into")
        table = self._expect_ident()
        columns = None
        if self._at_op("("):
            self._advance()
            columns = []
            while True:
                columns.append(self._expect_ident())
                if self._at_op(","):
                    self._advance()
                    continue
                break
            self._expect_op(")")
        self._expect_keyword("values")
        rows = []
        while True:
            self._expect_op("(")
            row = []
            while True:
                row.append(self._parse_expr())
                if self._at_op(","):
                    self._advance()
                    continue
                break
            self._expect_op(")")
            rows.append(row)
            if self._at_op(","):
                self._advance()
                continue
            break
        return Insert(table, columns, rows)

    # -- UPDATE -----------------------------------------------------------------

    def _parse_update(self):
        self._expect_keyword("update")
        table = self._expect_ident()
        self._expect_keyword("set")
        assignments = []
        while True:
            col = self._expect_ident()
            self._expect_op("=")
            expr = self._parse_expr()
            assignments.append(Assignment(col, expr))
            if self._at_op(","):
                self._advance()
                continue
            break
        where = None
        if self._at_keyword("where"):
            self._advance()
            where = self._parse_expr()
        return Update(table, assignments, where)

    # -- DELETE -----------------------------------------------------------------

    def _parse_delete(self):
        self._expect_keyword("delete")
        self._expect_keyword("from")
        table = self._expect_ident()
        where = None
        if self._at_keyword("where"):
            self._advance()
            where = self._parse_expr()
        return Delete(table, where)

    # -- SELECT -------------------------------------------------------------------

    def _parse_select(self):
        self._expect_keyword("select")
        distinct = False
        if self._at_keyword("distinct"):
            self._advance()
            distinct = True
        select_list = self._parse_select_list()
        self._expect_keyword("from")
        from_table = self._expect_ident()
        from_alias = self._parse_optional_alias()
        joins = []
        while self._at_keyword("join", "inner", "left", "outer"):
            joins.append(self._parse_join())
        where = None
        if self._at_keyword("where"):
            self._advance()
            where = self._parse_expr()
        group_by: list = []
        if self._at_keyword("group"):
            self._advance()
            self._expect_keyword("by")
            group_by.append(self._parse_expr())
            while self._at_op(","):
                self._advance()
                group_by.append(self._parse_expr())
        having = None
        if self._at_keyword("having"):
            self._advance()
            having = self._parse_expr()
        order_by: list = []
        if self._at_keyword("order"):
            self._advance()
            self._expect_keyword("by")
            order_by.append(self._parse_order_term())
            while self._at_op(","):
                self._advance()
                order_by.append(self._parse_order_term())
        limit = None
        offset = None
        if self._at_keyword("limit"):
            self._advance()
            limit = self._parse_int_literal()
            if self._at_keyword("offset"):
                self._advance()
                offset = self._parse_int_literal()
        return Select(
            distinct=distinct,
            select_list=select_list,
            from_table=from_table,
            from_alias=from_alias,
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
        neg = False
        if tok.kind == "op" and tok.value == "-":
            self._advance()
            neg = True
            tok = self._peek()
        if tok.kind != "integer":
            raise SQLError(f"Expected integer literal near position {tok.pos}")
        self._advance()
        val = int(tok.value)
        return -val if neg else val

    def _parse_optional_alias(self) -> str | None:
        if self._at_keyword("as"):
            self._advance()
            return self._expect_ident()
        tok = self._peek()
        if tok.kind == "ident":
            self._advance()
            return tok.value
        return None

    def _parse_join(self) -> JoinClause:
        kind = "INNER"
        if self._at_keyword("left"):
            self._advance()
            if self._at_keyword("outer"):
                self._advance()
            kind = "LEFT"
        elif self._at_keyword("inner"):
            self._advance()
            kind = "INNER"
        self._expect_keyword("join")
        table = self._expect_ident()
        alias = self._parse_optional_alias()
        self._expect_keyword("on")
        on_expr = self._parse_expr()
        return JoinClause(kind, table, alias, on_expr)

    def _parse_select_list(self) -> list[SelectItem]:
        items = [self._parse_select_item()]
        while self._at_op(","):
            self._advance()
            items.append(self._parse_select_item())
        return items

    def _parse_select_item(self) -> SelectItem:
        if self._at_op("*"):
            self._advance()
            return SelectItem(ColumnRef(None, "*"), None)
        # alias.*
        next1 = self.tokens[self.pos + 1]
        next2 = self.tokens[self.pos + 2]
        if (
            self._peek().kind == "ident"
            and next1.kind == "op"
            and next1.value == "."
            and next2.kind == "op"
            and next2.value == "*"
        ):
            alias = self._advance().value
            self._advance()  # .
            self._advance()  # *
            return SelectItem(ColumnRef(alias, "*"), None)
        expr = self._parse_expr()
        alias = None
        if self._at_keyword("as"):
            self._advance()
            alias = self._expect_ident()
        elif self._peek().kind == "ident":
            alias = self._advance().value
        return SelectItem(expr, alias)

    def _parse_order_term(self) -> OrderTerm:
        expr = self._parse_expr()
        desc = False
        if self._at_keyword("asc"):
            self._advance()
        elif self._at_keyword("desc"):
            self._advance()
            desc = True
        return OrderTerm(expr, desc)

    # -- Expressions --------------------------------------------------------------
    # Precedence (low to high): OR, AND, NOT, comparison, ||, + -, * / %, unary

    def _parse_expr(self):
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while self._at_keyword("or"):
            self._advance()
            right = self._parse_and()
            left = Or(left, right)
        return left

    def _parse_and(self):
        left = self._parse_not()
        while self._at_keyword("and"):
            self._advance()
            right = self._parse_not()
            left = And(left, right)
        return left

    def _parse_not(self):
        if self._at_keyword("not"):
            self._advance()
            return Not(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_additive()
        while True:
            if self._at_op(*_COMPARISON_OPS):
                op = self._advance().value
                right = self._parse_additive()
                left = BinOp(op, left, right)
            elif self._at_keyword("is"):
                self._advance()
                negated = False
                if self._at_keyword("not"):
                    self._advance()
                    negated = True
                self._expect_keyword("null")
                left = IsNull(left, negated)
            elif self._at_keyword("in"):
                self._advance()
                left = self._parse_in_rest(left, False)
            elif self._at_keyword("like"):
                self._advance()
                pattern = self._parse_additive()
                left = Like(left, False, pattern)
            elif self._at_keyword("between"):
                self._advance()
                left = self._parse_between_rest(left, False)
            elif self._at_keyword("not"):
                self._advance()
                if self._at_keyword("in"):
                    self._advance()
                    left = self._parse_in_rest(left, True)
                elif self._at_keyword("like"):
                    self._advance()
                    pattern = self._parse_additive()
                    left = Like(left, True, pattern)
                elif self._at_keyword("between"):
                    self._advance()
                    left = self._parse_between_rest(left, True)
                else:
                    tok = self._peek()
                    raise SQLError(f"Expected IN/LIKE/BETWEEN after NOT near position {tok.pos}")
            else:
                break
        return left

    def _parse_in_rest(self, left, negated: bool):
        self._expect_op("(")
        values = []
        if not self._at_op(")"):
            values.append(self._parse_expr())
            while self._at_op(","):
                self._advance()
                values.append(self._parse_expr())
        self._expect_op(")")
        return InList(left, negated, values)

    def _parse_between_rest(self, left, negated: bool):
        low = self._parse_additive()
        self._expect_keyword("and")
        high = self._parse_additive()
        return Between(left, negated, low, high)

    # Precedence (loose to tight): additive, multiplicative, concat, unary.
    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._at_op("+", "-"):
            op = self._advance().value
            right = self._parse_multiplicative()
            left = BinOp(op, left, right)
        return left

    def _parse_multiplicative(self):
        left = self._parse_concat()
        while self._at_op("*", "/", "%"):
            op = self._advance().value
            right = self._parse_concat()
            left = BinOp(op, left, right)
        return left

    def _parse_concat(self):
        left = self._parse_unary()
        while self._at_op("||"):
            self._advance()
            right = self._parse_unary()
            left = BinOp("||", left, right)
        return left

    def _parse_unary(self):
        if self._at_op("-", "+"):
            op = self._advance().value
            return UnaryOp(op, self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self):
        tok = self._peek()
        if tok.kind == "integer":
            self._advance()
            return Literal(int(tok.value))
        if tok.kind == "real":
            self._advance()
            return Literal(float(tok.value))
        if tok.kind == "string":
            self._advance()
            return Literal(tok.value)
        if tok.kind == "keyword" and tok.value == "null":
            self._advance()
            return Literal(None)
        if tok.kind == "keyword" and tok.value == "true":
            self._advance()
            return Literal(1)
        if tok.kind == "keyword" and tok.value == "false":
            self._advance()
            return Literal(0)
        if tok.kind == "op" and tok.value == "(":
            self._advance()
            expr = self._parse_expr()
            self._expect_op(")")
            return expr
        if tok.kind == "keyword" and tok.value in _AGGREGATE_NAMES:
            self._advance()
            return self._parse_func_call(tok.value)
        if tok.kind == "ident" or tok.kind == "keyword":
            # could be function call, qualified column, or plain column
            name = self._advance().value
            if self._at_op("("):
                return self._parse_func_call(name)
            if self._at_op("."):
                self._advance()
                if self._at_op("*"):
                    self._advance()
                    return ColumnRef(name, "*")
                col = self._expect_ident()
                return ColumnRef(name, col)
            return ColumnRef(None, name)
        raise SQLError(f"Unexpected token near position {tok.pos}: {tok.value!r}")

    def _parse_func_call(self, name: str) -> FuncCall:
        lname = name.lower()
        self._expect_op("(")
        distinct = False
        if self._at_keyword("distinct"):
            self._advance()
            distinct = True
        if self._at_op("*"):
            self._advance()
            self._expect_op(")")
            return FuncCall(lname, distinct, True, [])
        args = []
        if not self._at_op(")"):
            args.append(self._parse_expr())
            while self._at_op(","):
                self._advance()
                args.append(self._parse_expr())
        self._expect_op(")")
        return FuncCall(lname, distinct, False, args)


def parse(sql: str):
    return Parser(sql).parse_statement()

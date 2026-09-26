"""Recursive-descent parser producing AST dataclasses.

Operator precedence follows SQLite (lowest to highest):
OR; AND; NOT; = == != <> IS IN LIKE BETWEEN; < <= > >=; & | << >>; + -; * / %; ||;
unary - + ~.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from minisql.errors import SQLError
from minisql.lexer import EOF, IDENT, NUMBER, OP, STRING, Token, tokenize

# ---------------------------------------------------------------------------
# AST: expressions (eq=False so nodes hash by identity)
# ---------------------------------------------------------------------------


class Expr:
    pass


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclass(eq=False)
class Unary(Expr):
    op: str  # '-', '+', '~', 'NOT'
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class InList(Expr):
    expr: Expr
    items: list[Expr]
    negated: bool


@dataclass(eq=False)
class Between(Expr):
    expr: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(eq=False)
class Like(Expr):
    expr: Expr
    pattern: Expr
    escape: Expr | None
    negated: bool


@dataclass(eq=False)
class FuncCall(Expr):
    name: str  # lower-case
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass(eq=False)
class Case(Expr):
    base: Expr | None
    whens: list[tuple[Expr, Expr]]
    else_: Expr | None


@dataclass(eq=False)
class Cast(Expr):
    expr: Expr
    type_name: str


# ---------------------------------------------------------------------------
# AST: statements
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class ColumnDef:
    name: str
    type_name: str


@dataclass(eq=False)
class CreateTable:
    name: str
    columns: list[ColumnDef]
    if_not_exists: bool = False


@dataclass(eq=False)
class DropTable:
    name: str
    if_exists: bool = False


@dataclass(eq=False)
class SelectItem:
    kind: str  # 'star', 'table_star', 'expr'
    expr: Expr | None = None
    alias: str | None = None
    table: str | None = None


@dataclass(eq=False)
class TableRef:
    name: str
    alias: str | None = None


@dataclass(eq=False)
class Join:
    kind: str  # 'INNER', 'LEFT', 'CROSS'
    table: TableRef
    on: Expr | None


@dataclass(eq=False)
class FromClause:
    first: TableRef
    joins: list[Join] = field(default_factory=list)


@dataclass(eq=False)
class OrderTerm:
    expr: Expr
    desc: bool = False
    nulls_first: bool | None = None


@dataclass(eq=False)
class Select:
    distinct: bool
    items: list[SelectItem]
    from_: FromClause | None
    where: Expr | None
    group_by: list[Expr]
    having: Expr | None
    order_by: list[OrderTerm]
    limit: Expr | None
    offset: Expr | None


@dataclass(eq=False)
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]] | None
    select: Select | None


@dataclass(eq=False)
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass(eq=False)
class Delete:
    table: str
    where: Expr | None


Statement = CreateTable | DropTable | Insert | Update | Delete | Select

# Words that may not be used as bare identifiers / implicit aliases.
RESERVED = {
    "ABORT", "ALL", "ALTER", "AND", "AS", "ASC", "BETWEEN", "BY", "CASE", "CAST", "CHECK",
    "COLLATE", "CONSTRAINT", "CREATE", "CROSS", "DEFAULT", "DELETE", "DESC", "DISTINCT",
    "DROP", "ELSE", "END", "ESCAPE", "EXCEPT", "EXISTS", "FROM", "FULL", "GLOB", "GROUP",
    "HAVING", "IN", "INNER", "INSERT", "INTERSECT", "INTO", "IS", "ISNULL", "JOIN", "LEFT",
    "LIKE", "LIMIT", "NATURAL", "NOT", "NOTNULL", "NULL", "OFFSET", "ON", "OR", "ORDER",
    "OUTER", "PRIMARY", "REFERENCES", "RIGHT", "SELECT", "SET", "TABLE", "THEN", "UNION",
    "UNIQUE", "UPDATE", "USING", "VALUES", "WHEN", "WHERE",
}

_COMPARISON_OPS = {"<", "<=", ">", ">="}
_EQUALITY_OPS = {"=": "=", "==": "=", "!=": "!=", "<>": "!="}


class Parser:
    def __init__(self, sql: str):
        self.tokens: list[Token] = tokenize(sql)
        self.pos = 0

    # -- token helpers -----------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != EOF:
            self.pos += 1
        return t

    def error(self, msg: str | None = None) -> SQLError:
        t = self.tok
        if msg is None:
            near = "end of input" if t.kind == EOF else repr(t.value)
            msg = f"syntax error near {near}"
        return SQLError(msg)

    def at_kw(self, *words: str) -> bool:
        return self.tok.upper in words

    def accept_kw(self, *words: str) -> bool:
        if self.tok.upper in words:
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error()

    def at_op(self, *ops: str) -> bool:
        return self.tok.kind == OP and self.tok.value in ops

    def accept_op(self, *ops: str) -> bool:
        if self.at_op(*ops):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def identifier(self) -> str:
        t = self.tok
        if t.kind == IDENT and (t.quoted or t.upper not in RESERVED):
            self.advance()
            return str(t.value)
        raise self.error()

    # -- statements ----------------------------------------------------------
    def parse_statement(self) -> Statement:
        if self.at_kw("SELECT"):
            stmt: Statement = self.parse_select()
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
            raise self.error()
        while self.accept_op(";"):
            pass
        if self.tok.kind != EOF:
            raise self.error()
        return stmt

    def parse_create(self) -> CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        columns: list[ColumnDef] = []
        while True:
            if self.at_kw("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"):
                self.skip_constraint()
            else:
                col = self.identifier()
                type_words: list[str] = []
                while self.tok.kind == IDENT and not self.tok.quoted and self.tok.upper not in (
                    RESERVED | {"KEY", "FOREIGN"}
                ):
                    type_words.append(str(self.advance().value))
                if type_words and self.at_op("("):
                    # e.g. VARCHAR(20) or DECIMAL(10, 2)
                    self.advance()
                    while not self.at_op(")"):
                        if self.tok.kind == EOF:
                            raise self.error()
                        self.advance()
                    self.advance()
                columns.append(ColumnDef(col, " ".join(type_words)))
                self.skip_constraint()
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        if not columns:
            raise self.error()
        return CreateTable(name, columns, if_not_exists)

    def skip_constraint(self) -> None:
        """Skip column/table constraints up to the next top-level ',' or ')'."""
        depth = 0
        while True:
            t = self.tok
            if t.kind == EOF:
                raise self.error()
            if t.kind == OP and t.value == "(":
                depth += 1
            elif t.kind == OP and t.value == ")":
                if depth == 0:
                    return
                depth -= 1
            elif t.kind == OP and t.value == "," and depth == 0:
                return
            self.advance()

    def parse_drop(self) -> DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return DropTable(self.identifier(), if_exists)

    def parse_insert(self) -> Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.identifier()
        columns: list[str] | None = None
        if self.accept_op("("):
            columns = [self.identifier()]
            while self.accept_op(","):
                columns.append(self.identifier())
            self.expect_op(")")
        if self.at_kw("SELECT"):
            return Insert(table, columns, None, self.parse_select())
        self.expect_kw("VALUES")
        rows: list[list[Expr]] = []
        while True:
            self.expect_op("(")
            row = [self.parse_expr()]
            while self.accept_op(","):
                row.append(self.parse_expr())
            self.expect_op(")")
            rows.append(row)
            if not self.accept_op(","):
                break
        return Insert(table, columns, rows, None)

    def parse_update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.identifier()
        self.expect_kw("SET")
        assignments: list[tuple[str, Expr]] = []
        while True:
            col = self.identifier()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Update(table, assignments, where)

    def parse_delete(self) -> Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.identifier()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Delete(table, where)

    def parse_select(self) -> Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        from_ = self.parse_from() if self.accept_kw("FROM") else None
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
        order_by: list[OrderTerm] = []
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order_by.append(self.parse_order_term())
            while self.accept_op(","):
                order_by.append(self.parse_order_term())
        limit = offset = None
        if self.accept_kw("LIMIT"):
            limit = self.parse_expr()
            if self.accept_kw("OFFSET"):
                offset = self.parse_expr()
            elif self.accept_op(","):
                offset, limit = limit, self.parse_expr()
        return Select(distinct, items, from_, where, group_by, having, order_by, limit, offset)

    def parse_select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return SelectItem("star")
        t = self.tok
        if (
            t.kind == IDENT
            and self.peek().kind == OP
            and self.peek().value == "."
            and self.peek(2).kind == OP
            and self.peek(2).value == "*"
        ):
            self.pos += 3
            return SelectItem("table_star", table=str(t.value))
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            if self.tok.kind == STRING:
                alias = str(self.advance().value)
            else:
                alias = self.identifier()
        elif self.tok.kind == IDENT and (self.tok.quoted or self.tok.upper not in RESERVED):
            alias = str(self.advance().value)
        elif self.tok.kind == STRING:
            alias = str(self.advance().value)
        return SelectItem("expr", expr=expr, alias=alias)

    def parse_table_ref(self) -> TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.tok.kind == IDENT and (self.tok.quoted or self.tok.upper not in RESERVED):
            alias = str(self.advance().value)
        return TableRef(name, alias)

    def parse_from(self) -> FromClause:
        clause = FromClause(self.parse_table_ref())
        while True:
            if self.accept_op(","):
                clause.joins.append(Join("CROSS", self.parse_table_ref(), None))
                continue
            kind = None
            if self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            elif self.accept_kw("INNER"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("JOIN"):
                kind = "INNER"
            elif self.at_kw("RIGHT", "FULL", "NATURAL"):
                raise self.error(f"unsupported join type: {self.tok.value}")
            if kind is None:
                break
            table = self.parse_table_ref()
            on = None
            if self.accept_kw("ON"):
                on = self.parse_expr()
            elif self.at_kw("USING"):
                raise self.error("USING is not supported")
            elif kind == "LEFT":
                raise self.error()
            clause.joins.append(Join(kind, table, on))
        return clause

    def parse_order_term(self) -> OrderTerm:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        if self.accept_kw("NULLS"):
            if self.accept_kw("FIRST"):
                nulls_first = True
            else:
                self.expect_kw("LAST")
                nulls_first = False
        return OrderTerm(expr, desc, nulls_first)

    # -- expressions -----------------------------------------------------------
    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.accept_kw("NOT"):
            return Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> Expr:
        left = self.parse_comparison()
        while True:
            t = self.tok
            if t.kind == OP and t.value in _EQUALITY_OPS:
                self.advance()
                left = Binary(_EQUALITY_OPS[str(t.value)], left, self.parse_comparison())
            elif self.accept_kw("IS"):
                op = "IS NOT" if self.accept_kw("NOT") else "IS"
                left = Binary(op, left, self.parse_comparison())
            elif self.accept_kw("ISNULL"):
                left = Binary("IS", left, Literal(None))
            elif self.accept_kw("NOTNULL"):
                left = Binary("IS NOT", left, Literal(None))
            elif self.at_kw("NOT") and self.peek().upper in ("IN", "LIKE", "BETWEEN", "NULL"):
                self.advance()
                if self.accept_kw("NULL"):
                    left = Binary("IS NOT", left, Literal(None))
                else:
                    left = self.parse_postfix(left, negated=True)
            elif self.at_kw("IN", "LIKE", "BETWEEN"):
                left = self.parse_postfix(left, negated=False)
            else:
                return left

    def parse_postfix(self, left: Expr, negated: bool) -> Expr:
        if self.accept_kw("IN"):
            self.expect_op("(")
            items: list[Expr] = []
            if self.at_kw("SELECT"):
                raise self.error("subqueries are not supported")
            if not self.at_op(")"):
                items.append(self.parse_expr())
                while self.accept_op(","):
                    items.append(self.parse_expr())
            self.expect_op(")")
            return InList(left, items, negated)
        if self.accept_kw("LIKE"):
            pattern = self.parse_comparison()
            escape = self.parse_comparison() if self.accept_kw("ESCAPE") else None
            return Like(left, pattern, escape, negated)
        self.expect_kw("BETWEEN")
        low = self.parse_comparison()
        self.expect_kw("AND")
        high = self.parse_comparison()
        return Between(left, low, high, negated)

    def parse_comparison(self) -> Expr:
        left = self.parse_bitwise()
        while self.tok.kind == OP and self.tok.value in _COMPARISON_OPS:
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_bitwise())
        return left

    def parse_bitwise(self) -> Expr:
        left = self.parse_additive()
        while self.at_op("&", "|", "<<", ">>"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> Expr:
        left = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> Expr:
        left = self.parse_concat()
        while self.at_op("*", "/", "%"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> Expr:
        left = self.parse_unary()
        while self.at_op("||"):
            self.advance()
            left = Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        if self.at_op("-", "+", "~"):
            op = str(self.advance().value)
            if op == "-" and self.tok.kind == NUMBER and self.tok.value == 2**63:
                self.advance()
                return Literal(-(2**63))
            return Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        t = self.tok
        if t.kind == NUMBER:
            self.advance()
            value = t.value
            if isinstance(value, int) and value > 2**63 - 1:
                return Literal(float(value))
            return Literal(value)
        if t.kind == STRING:
            self.advance()
            return Literal(t.value)
        if t.kind == OP and t.value == "(":
            self.advance()
            if self.at_kw("SELECT"):
                raise self.error("subqueries are not supported")
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if t.kind != IDENT:
            raise self.error()
        up = t.upper
        if up == "NULL":
            self.advance()
            return Literal(None)
        if up in ("TRUE", "FALSE") and not (self.peek().kind == OP and self.peek().value == "("):
            self.advance()
            return Literal(1 if up == "TRUE" else 0)
        if up == "CASE":
            return self.parse_case()
        if up == "CAST":
            self.advance()
            self.expect_op("(")
            expr = self.parse_expr()
            self.expect_kw("AS")
            words: list[str] = []
            while self.tok.kind == IDENT:
                words.append(str(self.advance().value))
            if not words:
                raise self.error()
            if self.accept_op("("):
                while not self.at_op(")"):
                    if self.tok.kind == EOF:
                        raise self.error()
                    self.advance()
                self.advance()
            self.expect_op(")")
            return Cast(expr, " ".join(words))
        if up == "EXISTS":
            raise self.error("subqueries are not supported")
        if not t.quoted and up in RESERVED:
            raise self.error()
        self.advance()
        name = str(t.value)
        if self.at_op("(") and not t.quoted:
            self.advance()
            distinct = False
            if self.accept_op("*"):
                self.expect_op(")")
                return FuncCall(name.lower(), [], star=True)
            args: list[Expr] = []
            if self.accept_kw("DISTINCT"):
                distinct = True
            else:
                self.accept_kw("ALL")
            if not self.at_op(")"):
                args.append(self.parse_expr())
                while self.accept_op(","):
                    args.append(self.parse_expr())
            self.expect_op(")")
            return FuncCall(name.lower(), args, distinct=distinct)
        if self.at_op("."):
            self.advance()
            col = self.identifier()
            return ColumnRef(name, col)
        return ColumnRef(None, name)

    def parse_case(self) -> Case:
        self.expect_kw("CASE")
        base = None
        if not self.at_kw("WHEN"):
            base = self.parse_expr()
        whens: list[tuple[Expr, Expr]] = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return Case(base, whens, else_)


def parse(sql: str) -> Statement:
    if not isinstance(sql, str):
        raise SQLError("SQL must be a string")
    return Parser(sql).parse_statement()

"""AST node definitions and a recursive-descent SQL parser."""

from __future__ import annotations

from dataclasses import dataclass, field

from minisql.errors import SQLError
from minisql.tokenizer import EOF, IDENT, INT, QIDENT, REAL, STRING, Token, tokenize
from minisql.values import INT_MAX, INT_MIN

# ----------------------------------------------------------------------------
# Expression AST
# ----------------------------------------------------------------------------


@dataclass
class Literal:
    value: object


@dataclass
class TrueFalse:
    """The TRUE/FALSE keywords (also what SQLite rewrites ``x [NOT] IN ()`` into)."""

    value: bool


@dataclass
class ColumnRef:
    table: str | None
    name: str


@dataclass
class Star:
    table: str | None


@dataclass
class Unary:
    op: str  # '-', '+', 'NOT'
    operand: Expr


@dataclass
class Binary:
    op: str  # arithmetic, '||', comparison, 'AND', 'OR', 'IS', 'IS NOT'
    left: Expr
    right: Expr


@dataclass
class BoolTest:
    """``x IS [NOT] TRUE`` / ``x IS [NOT] FALSE``: a boolean test that never yields NULL."""

    operand: Expr
    target: bool
    negated: bool


@dataclass
class In:
    operand: Expr
    items: list[Expr]
    negated: bool


@dataclass
class Between:
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass
class Like:
    operand: Expr
    pattern: Expr
    negated: bool


@dataclass
class Call:
    name: str  # upper-cased
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass
class Bound:
    """A column reference resolved to a row index (produced by the executor)."""

    index: int
    affinity: str
    name: str


Expr = (
    Literal | TrueFalse | ColumnRef | Star | Unary | Binary | BoolTest | In | Between | Like
    | Call | Bound
)


# ----------------------------------------------------------------------------
# Statement AST
# ----------------------------------------------------------------------------


@dataclass
class ColumnDef:
    name: str
    type_name: str | None


@dataclass
class CreateTable:
    name: str
    columns: list[ColumnDef]


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]]


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass
class Delete:
    table: str
    where: Expr | None


@dataclass
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass
class TableRef:
    name: str
    alias: str


@dataclass
class Join:
    table: TableRef
    kind: str  # 'INNER' or 'LEFT'
    on: Expr | None


@dataclass
class OrderTerm:
    expr: Expr
    desc: bool


@dataclass
class Select:
    items: list[SelectItem]
    distinct: bool = False
    from_table: TableRef | None = None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None


Statement = CreateTable | Insert | Update | Delete | Select


# Keywords that may not be used as bare (un-quoted) aliases or column names.
RESERVED = frozenset(
    {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "LIMIT", "OFFSET",
        "JOIN", "LEFT", "INNER", "OUTER", "CROSS", "ON", "AS", "AND", "OR", "NOT", "IS",
        "IN", "LIKE", "BETWEEN", "NULL", "DISTINCT", "ALL", "ASC", "DESC", "VALUES",
        "SET", "INTO", "INSERT", "UPDATE", "DELETE", "CREATE", "TABLE", "USING",
        "NATURAL", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END", "UNION", "EXCEPT",
        "INTERSECT",
    }
)

_CONSTRAINT_KEYWORDS = frozenset(
    {"PRIMARY", "NOT", "NULL", "UNIQUE", "DEFAULT", "CHECK", "REFERENCES", "COLLATE",
     "CONSTRAINT", "GENERATED"}
)


def _always_false(expr: Expr) -> bool:
    if isinstance(expr, TrueFalse):
        return not expr.value
    return isinstance(expr, Literal) and type(expr.value) is int and expr.value == 0


def parse(sql: str) -> Statement:
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # -- token helpers -------------------------------------------------------

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

    def error(self, message: str | None = None) -> SQLError:
        t = self.tok
        if message is None:
            if t.kind == EOF:
                message = "unexpected end of input"
            else:
                message = f"syntax error near {t.value!r}"
        return SQLError(message)

    def accept_kw(self, *words: str) -> bool:
        if self.tok.is_kw(*words):
            self.advance()
            return True
        return False

    def expect_kw(self, *words: str) -> None:
        if not self.accept_kw(*words):
            raise self.error(f"expected {' or '.join(words)}")

    def accept_op(self, *ops: str) -> bool:
        if self.tok.is_op(*ops):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error(f"expected {op!r}")

    def expect_name(self) -> str:
        t = self.tok
        if t.kind == QIDENT:
            self.advance()
            return str(t.value)
        if t.kind == IDENT and str(t.value).upper() not in RESERVED:
            self.advance()
            return str(t.value)
        raise self.error("expected a name")

    def at_name(self) -> bool:
        t = self.tok
        return t.kind == QIDENT or (t.kind == IDENT and str(t.value).upper() not in RESERVED)

    # -- statements -----------------------------------------------------------

    def parse_statement(self) -> Statement:
        t = self.tok
        if t.is_kw("SELECT"):
            stmt: Statement = self.parse_select()
        elif t.is_kw("CREATE"):
            stmt = self.parse_create()
        elif t.is_kw("INSERT"):
            stmt = self.parse_insert()
        elif t.is_kw("UPDATE"):
            stmt = self.parse_update()
        elif t.is_kw("DELETE"):
            stmt = self.parse_delete()
        else:
            raise self.error()
        self.accept_op(";")
        if self.tok.kind != EOF:
            raise self.error()
        return stmt

    def parse_create(self) -> CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        name = self.expect_name()
        self.expect_op("(")
        columns: list[ColumnDef] = []
        while True:
            col = self.expect_name()
            type_parts: list[str] = []
            while self.tok.kind == IDENT and not self.tok.is_kw(*_CONSTRAINT_KEYWORDS):
                type_parts.append(str(self.advance().value))
            if type_parts and self.accept_op("("):
                self._skip_parens()
            # Skip any column constraints.
            depth = 0
            while not (depth == 0 and self.tok.is_op(",", ")")):
                if self.tok.kind == EOF:
                    raise self.error()
                if self.tok.is_op("("):
                    depth += 1
                elif self.tok.is_op(")"):
                    depth -= 1
                self.advance()
            columns.append(ColumnDef(col, " ".join(type_parts) or None))
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        if not columns:
            raise self.error("table must have at least one column")
        return CreateTable(name, columns)

    def _skip_parens(self) -> None:
        depth = 1
        while depth > 0:
            t = self.advance()
            if t.kind == EOF:
                raise self.error()
            if t.is_op("("):
                depth += 1
            elif t.is_op(")"):
                depth -= 1

    def parse_insert(self) -> Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.expect_name()
        columns: list[str] | None = None
        if self.accept_op("("):
            columns = [self.expect_name()]
            while self.accept_op(","):
                columns.append(self.expect_name())
            self.expect_op(")")
        self.expect_kw("VALUES")
        rows: list[list[Expr]] = []
        while True:
            self.expect_op("(")
            values = [self.parse_expr()]
            while self.accept_op(","):
                values.append(self.parse_expr())
            self.expect_op(")")
            rows.append(values)
            if not self.accept_op(","):
                break
        return Insert(table, columns, rows)

    def parse_update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.expect_name()
        self.expect_kw("SET")
        assignments: list[tuple[str, Expr]] = []
        while True:
            col = self.expect_name()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return Update(table, assignments, where)

    def parse_delete(self) -> Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.expect_name()
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
        select = Select(items, distinct=distinct)
        if self.accept_kw("FROM"):
            select.from_table = self.parse_table_ref()
            while True:
                kind = None
                if self.accept_kw("JOIN"):
                    kind = "INNER"
                elif self.tok.is_kw("INNER", "CROSS"):
                    self.advance()
                    self.expect_kw("JOIN")
                    kind = "INNER"
                elif self.accept_kw("LEFT"):
                    self.accept_kw("OUTER")
                    self.expect_kw("JOIN")
                    kind = "LEFT"
                elif self.accept_op(","):
                    kind = "INNER"
                if kind is None:
                    break
                ref = self.parse_table_ref()
                on = self.parse_expr() if self.accept_kw("ON") else None
                select.joins.append(Join(ref, kind, on))
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
                # LIMIT offset, count
                select.offset = select.limit
                select.limit = self.parse_expr()
        return select

    def parse_select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return SelectItem(Star(None), None)
        if self.at_name() and self.peek().is_op(".") and self.peek(2).is_op("*"):
            table = self.expect_name()
            self.advance()
            self.advance()
            return SelectItem(Star(table), None)
        expr = self.parse_expr()
        alias: str | None = None
        if self.accept_kw("AS"):
            alias = self.expect_name()
        elif self.at_name():
            alias = self.expect_name()
        return SelectItem(expr, alias)

    def parse_table_ref(self) -> TableRef:
        name = self.expect_name()
        alias = name
        if self.accept_kw("AS"):
            alias = self.expect_name()
        elif self.at_name():
            alias = self.expect_name()
        return TableRef(name, alias)

    def parse_order_term(self) -> OrderTerm:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        return OrderTerm(expr, desc)

    # -- expressions ----------------------------------------------------------

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
            right = self.parse_not()
            if _always_false(left) or _always_false(right):
                # SQLite folds "expr AND 0" / "expr AND FALSE" into the integer literal 0
                # while parsing (before name resolution), and so do we.
                left = Literal(0)
            else:
                left = Binary("AND", left, right)
        return left

    def parse_not(self) -> Expr:
        if self.accept_kw("NOT"):
            return Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> Expr:
        """Level of = == != <> IS IN LIKE BETWEEN (left-associative).

        Mirrors SQLite's LALR grammar: the right operand of IS / LIKE and the upper bound of
        BETWEEN absorb higher-precedence operators, the lower bound of BETWEEN absorbs
        everything up to the AND, and a completed IN (...) acts as an atom for any operators
        of higher precedence that follow it.
        """
        left = self.parse_comparison()
        while True:
            t = self.tok
            if t.is_op("=", "==", "!=", "<>"):
                self.advance()
                op = "=" if t.value == "==" else str(t.value)
                left = Binary(op, left, self.parse_comparison())
            elif t.is_kw("IS"):
                self.advance()
                negated = self.accept_kw("NOT")
                right = self.parse_comparison()
                if isinstance(right, TrueFalse):
                    left = BoolTest(left, right.value, negated)
                else:
                    left = Binary("IS NOT" if negated else "IS", left, right)
            elif t.is_kw("IN") or (t.is_kw("NOT") and self.peek().is_kw("IN")):
                negated = self.accept_kw("NOT")
                self.expect_kw("IN")
                self.expect_op("(")
                items: list[Expr] = []
                if not self.tok.is_op(")"):
                    items.append(self.parse_expr())
                    while self.accept_op(","):
                        items.append(self.parse_expr())
                self.expect_op(")")
                if not items:
                    # SQLite rewrites "x IN ()" to FALSE and "x NOT IN ()" to TRUE.
                    left = self.parse_comparison(TrueFalse(negated))
                else:
                    left = self.parse_comparison(In(left, items, negated))
            elif t.is_kw("BETWEEN") or (t.is_kw("NOT") and self.peek().is_kw("BETWEEN")):
                negated = self.accept_kw("NOT")
                self.expect_kw("BETWEEN")
                low = self.parse_not()
                self.expect_kw("AND")
                high = self.parse_comparison()
                left = Between(left, low, high, negated)
            elif t.is_kw("LIKE") or (t.is_kw("NOT") and self.peek().is_kw("LIKE")):
                negated = self.accept_kw("NOT")
                self.expect_kw("LIKE")
                left = Like(left, self.parse_comparison(), negated)
            else:
                return left

    def parse_comparison(self, left: Expr | None = None) -> Expr:
        left = self.parse_additive(left)
        while self.tok.is_op("<", "<=", ">", ">="):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self, left: Expr | None = None) -> Expr:
        left = self.parse_term(left)
        while self.tok.is_op("+", "-"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_term())
        return left

    def parse_term(self, left: Expr | None = None) -> Expr:
        left = self.parse_concat(left)
        while self.tok.is_op("*", "/", "%"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self, left: Expr | None = None) -> Expr:
        if left is None:
            left = self.parse_unary()
        while self.accept_op("||"):
            left = Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        if self.tok.is_op("-", "+"):
            op = str(self.advance().value)
            if op == "-" and self.tok.kind == INT:
                # Fold the sign into the literal so -9223372036854775808 stays an integer.
                value = -int(self.advance().value)  # type: ignore[call-overload]
                return Literal(value if INT_MIN <= value <= INT_MAX else float(value))
            operand = self.parse_unary()
            if op == "-" and isinstance(operand, Literal) and isinstance(operand.value, float):
                return Literal(-operand.value)  # literal -0.0 stays negative zero, like SQLite
            return Unary(op, operand)
        if self.tok.is_kw("NOT"):
            # NOT in operand position; its operand extends as far as NOT's precedence allows.
            self.advance()
            return Unary("NOT", self.parse_not())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        t = self.tok
        if t.kind == INT:
            self.advance()
            value = int(t.value)  # type: ignore[call-overload]
            return Literal(value if INT_MIN <= value <= INT_MAX else float(value))
        if t.kind == REAL:
            self.advance()
            return Literal(t.value)
        if t.kind == STRING:
            self.advance()
            return Literal(t.value)
        if t.is_op("("):
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if t.is_kw("NULL"):
            self.advance()
            return Literal(None)
        if t.is_kw("TRUE", "FALSE"):
            self.advance()
            return TrueFalse(str(t.value).upper() == "TRUE")
        if t.kind == IDENT and self.peek().is_op("("):
            return self.parse_call()
        if self.at_name():
            name = self.expect_name()
            if self.accept_op("."):
                return ColumnRef(name, self.expect_name())
            return ColumnRef(None, name)
        raise self.error()

    def parse_call(self) -> Expr:
        name = str(self.advance().value).upper()
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            return Call(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        args: list[Expr] = []
        if not self.tok.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return Call(name, args, distinct=distinct)

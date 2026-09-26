"""Recursive-descent SQL parser."""

from __future__ import annotations

from minisql import nodes as n
from minisql.errors import SQLError
from minisql.tokenizer import EOF, ID, NUM, OP, QID, STR, Token, tokenize

# Keywords that cannot be used as bare identifiers / implicit aliases.
RESERVED = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST COLLATE CREATE CROSS DELETE DESC DISTINCT DROP ELSE
    END ESCAPE EXCEPT EXISTS FROM FULL GLOB GROUP HAVING IN INNER INSERT INTERSECT INTO IS
    ISNULL JOIN LEFT LIMIT LIKE NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT
    SELECT SET TABLE THEN UNION UPDATE USING VALUES WHEN WHERE
    """.split()
)

AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"})


def parse(sql: str):
    """Parse a single SQL statement."""
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, k: int = 1) -> Token:
        idx = min(self.pos + k, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != EOF:
            self.pos += 1
        return t

    def error(self, msg: str | None = None) -> SQLError:
        t = self.tok
        if msg is None:
            if t.kind == EOF:
                msg = "incomplete input"
            else:
                msg = f'near "{t.value}": syntax error'
        return SQLError(msg)

    def is_kw(self, *kws: str, tok: Token | None = None) -> bool:
        t = self.tok if tok is None else tok
        return t.kind == ID and t.upper in kws

    def match_kw(self, *kws: str) -> str | None:
        if self.is_kw(*kws):
            return self.advance().upper
        return None

    def expect_kw(self, kw: str) -> None:
        if not self.match_kw(kw):
            raise self.error()

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == OP and self.tok.value in ops

    def match_op(self, *ops: str) -> str | None:
        if self.is_op(*ops):
            return self.advance().value
        return None

    def expect_op(self, op: str) -> None:
        if not self.match_op(op):
            raise self.error()

    def is_name(self, tok: Token | None = None) -> bool:
        t = self.tok if tok is None else tok
        return t.kind == QID or (t.kind == ID and t.upper not in RESERVED)

    def name(self) -> str:
        t = self.tok
        if t.kind == QID:
            self.advance()
            return t.value
        if t.kind == ID and t.upper not in RESERVED:
            self.advance()
            return t.value
        if t.kind == STR:  # SQLite accepts 'string' as identifier in some places
            self.advance()
            return t.value
        raise self.error()

    # ------------------------------------------------------------ statements
    def parse_statement(self):
        while self.match_op(";"):
            pass
        if self.tok.kind == EOF:
            return None  # empty statement: a no-op, as in SQLite
        if self.is_kw("SELECT"):
            stmt = self.parse_select()
        elif self.is_kw("CREATE"):
            stmt = self.parse_create()
        elif self.is_kw("DROP"):
            stmt = self.parse_drop()
        elif self.is_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.is_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.is_kw("DELETE"):
            stmt = self.parse_delete()
        else:
            raise self.error()
        while self.match_op(";"):
            pass
        if self.tok.kind != EOF:
            raise self.error()
        return stmt

    def parse_create(self) -> n.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.match_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.name()
        self.expect_op("(")
        cols: list[n.ColumnDef] = []
        while True:
            if self.is_kw("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"):
                raise self.error("table constraints are not supported")
            cname = self.name()
            type_parts: list[str] = []
            while self.tok.kind == ID and self.tok.upper not in RESERVED and not self.is_kw(
                "PRIMARY", "UNIQUE", "CHECK", "DEFAULT", "REFERENCES", "CONSTRAINT"
            ):
                type_parts.append(self.advance().value)
            if type_parts and self.match_op("("):
                self._skip_parens()
            # Skip simple column constraints.
            while not self.is_op(",", ")"):
                if self.tok.kind == EOF:
                    raise self.error()
                if self.match_op("("):
                    self._skip_parens()
                else:
                    self.advance()
            cols.append(n.ColumnDef(cname, " ".join(type_parts)))
            if self.match_op(","):
                continue
            self.expect_op(")")
            break
        return n.CreateTable(name, cols, if_not_exists)

    def _skip_parens(self) -> None:
        depth = 1
        while depth:
            t = self.advance()
            if t.kind == EOF:
                raise self.error()
            if t.kind == OP and t.value == "(":
                depth += 1
            elif t.kind == OP and t.value == ")":
                depth -= 1

    def parse_drop(self) -> n.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.match_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return n.DropTable(self.name(), if_exists)

    def parse_insert(self) -> n.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.name()
        columns = None
        if self.match_op("("):
            columns = [self.name()]
            while self.match_op(","):
                columns.append(self.name())
            self.expect_op(")")
        if self.match_kw("VALUES"):
            rows = []
            while True:
                self.expect_op("(")
                row = [self.parse_expr()]
                while self.match_op(","):
                    row.append(self.parse_expr())
                self.expect_op(")")
                rows.append(row)
                if not self.match_op(","):
                    break
            return n.Insert(table, columns, rows, None)
        if self.is_kw("SELECT"):
            return n.Insert(table, columns, None, self.parse_select())
        raise self.error()

    def parse_update(self) -> n.Update:
        self.expect_kw("UPDATE")
        table = self.name()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.name()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.match_op(","):
                break
        where = self.parse_expr() if self.match_kw("WHERE") else None
        return n.Update(table, assignments, where)

    def parse_delete(self) -> n.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.name()
        where = self.parse_expr() if self.match_kw("WHERE") else None
        return n.Delete(table, where)

    def parse_select(self) -> n.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.match_kw("DISTINCT"):
            distinct = True
        else:
            self.match_kw("ALL")
        items = [self.parse_select_item()]
        while self.match_op(","):
            items.append(self.parse_select_item())
        stmt = n.Select(distinct, items, None)
        if self.match_kw("FROM"):
            stmt.from_ = self.parse_table_ref()
            while True:
                if self.match_op(","):
                    stmt.joins.append(n.Join("CROSS", self.parse_table_ref(), None))
                    continue
                kind = None
                if self.match_kw("LEFT"):
                    self.match_kw("OUTER")
                    kind = "LEFT"
                elif self.match_kw("INNER"):
                    kind = "INNER"
                elif self.match_kw("CROSS"):
                    kind = "CROSS"
                elif self.is_kw("JOIN"):
                    kind = "INNER"
                elif self.is_kw("RIGHT", "FULL", "NATURAL"):
                    raise self.error(f"{self.tok.upper} JOIN is not supported")
                if kind is None:
                    break
                self.expect_kw("JOIN")
                ref = self.parse_table_ref()
                on = None
                if self.match_kw("ON"):
                    on = self.parse_expr()
                elif self.is_kw("USING"):
                    raise self.error("USING is not supported")
                stmt.joins.append(n.Join(kind, ref, on))
        if self.match_kw("WHERE"):
            stmt.where = self.parse_expr()
        if self.match_kw("GROUP"):
            self.expect_kw("BY")
            stmt.group_by = [self.parse_expr()]
            while self.match_op(","):
                stmt.group_by.append(self.parse_expr())
        if self.match_kw("HAVING"):
            stmt.having = self.parse_expr()
        if self.match_kw("ORDER"):
            self.expect_kw("BY")
            stmt.order_by = [self.parse_order_term()]
            while self.match_op(","):
                stmt.order_by.append(self.parse_order_term())
        if self.match_kw("LIMIT"):
            first = self.parse_expr()
            if self.match_kw("OFFSET"):
                stmt.limit = first
                stmt.offset = self.parse_expr()
            elif self.match_op(","):
                stmt.offset = first
                stmt.limit = self.parse_expr()
            else:
                stmt.limit = first
        return stmt

    def parse_order_term(self) -> n.OrderTerm:
        expr = self.parse_expr()
        desc = False
        if self.match_kw("DESC"):
            desc = True
        else:
            self.match_kw("ASC")
        nulls_first = None
        if self.match_kw("NULLS"):
            which = self.match_kw("FIRST", "LAST")
            if which is None:
                raise self.error()
            nulls_first = which == "FIRST"
        return n.OrderTerm(expr, desc, nulls_first)

    def parse_select_item(self) -> n.SelectItem:
        if self.match_op("*"):
            return n.SelectItem(n.Star(None), None)
        if self.is_name() and self.peek().kind == OP and self.peek().value == ".":
            t2 = self.peek(2)
            if t2.kind == OP and t2.value == "*":
                table = self.name()
                self.advance()
                self.advance()
                return n.SelectItem(n.Star(table), None)
        expr = self.parse_expr()
        alias = None
        if self.match_kw("AS"):
            alias = self.name()
        elif self.is_name() or self.tok.kind == STR:
            alias = self.name()
        return n.SelectItem(expr, alias)

    def parse_table_ref(self) -> n.TableRef:
        name = self.name()
        alias = None
        if self.match_kw("AS"):
            alias = self.name()
        elif self.is_name():
            alias = self.name()
        return n.TableRef(name, alias)

    # ------------------------------------------------------------ expressions
    def parse_expr(self) -> n.Expr:
        return self.parse_or()

    def parse_or(self) -> n.Expr:
        left = self.parse_and()
        while self.match_kw("OR"):
            left = n.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> n.Expr:
        left = self.parse_not()
        while self.match_kw("AND"):
            left = n.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> n.Expr:
        if self.match_kw("NOT"):
            return n.Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> n.Expr:
        left = self.parse_comparison()
        while True:
            op = self.match_op("=", "==", "!=", "<>")
            if op:
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = n.Binary(op, left, self.parse_comparison())
                continue
            if self.match_kw("IS"):
                negated = bool(self.match_kw("NOT"))
                if self.match_kw("DISTINCT"):
                    self.expect_kw("FROM")
                    negated = not negated
                right = self.parse_comparison()
                left = n.Binary("ISNOT" if negated else "IS", left, right)
                continue
            if self.match_kw("ISNULL"):
                left = n.Binary("IS", left, n.Literal(None))
                continue
            if self.match_kw("NOTNULL"):
                left = n.Binary("ISNOT", left, n.Literal(None))
                continue
            negated = False
            if self.is_kw("NOT"):
                nxt = self.peek()
                if self.is_kw("NULL", tok=nxt):
                    self.advance()
                    self.advance()
                    left = n.Binary("ISNOT", left, n.Literal(None))
                    continue
                if self.is_kw("IN", "LIKE", "BETWEEN", "GLOB", tok=nxt):
                    self.advance()
                    negated = True
                else:
                    break
            if self.match_kw("IN"):
                self.expect_op("(")
                items: list[n.Expr] = []
                if not self.is_op(")"):
                    if self.is_kw("SELECT"):
                        raise self.error("subqueries are not supported")
                    items.append(self.parse_expr())
                    while self.match_op(","):
                        items.append(self.parse_expr())
                self.expect_op(")")
                left = n.InList(left, items, negated)
                continue
            if self.match_kw("LIKE"):
                pattern = self.parse_comparison()
                escape = None
                if self.match_kw("ESCAPE"):
                    escape = self.parse_comparison()
                left = n.Like(left, pattern, escape, negated)
                continue
            if self.match_kw("BETWEEN"):
                low = self.parse_comparison()
                self.expect_kw("AND")
                high = self.parse_comparison()
                left = n.Between(left, low, high, negated)
                continue
            if self.is_kw("GLOB"):
                raise self.error("GLOB is not supported")
            if negated:
                raise self.error()
            break
        return left

    def parse_comparison(self) -> n.Expr:
        left = self.parse_bitwise()
        while True:
            op = self.match_op("<", "<=", ">", ">=")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_bitwise())

    def parse_bitwise(self) -> n.Expr:
        left = self.parse_additive()
        while True:
            op = self.match_op("&", "|", "<<", ">>")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_additive())

    def parse_additive(self) -> n.Expr:
        left = self.parse_multiplicative()
        while True:
            op = self.match_op("+", "-")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_multiplicative())

    def parse_multiplicative(self) -> n.Expr:
        left = self.parse_concat()
        while True:
            op = self.match_op("*", "/", "%")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_concat())

    def parse_concat(self) -> n.Expr:
        left = self.parse_unary()
        while self.match_op("||"):
            left = n.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> n.Expr:
        op = self.match_op("-", "+", "~")
        if op:
            operand = self.parse_unary()
            if (
                op == "-"
                and isinstance(operand, n.Literal)
                and operand.value == 9223372036854775808.0
            ):
                # -9223372036854775808 is representable as an integer.
                if self.tokens[self.pos - 1].kind == NUM:
                    return n.Literal(-(1 << 63))
            return n.Unary(op, operand)
        expr = self.parse_primary()
        if self.match_kw("COLLATE"):
            coll = self.name().upper()
            if coll not in ("BINARY",):
                raise self.error(f"unsupported collation: {coll}")
        return expr

    def parse_primary(self) -> n.Expr:
        t = self.tok
        if t.kind == NUM:
            self.advance()
            return n.Literal(t.value)
        if t.kind == STR:
            self.advance()
            return n.Literal(t.value)
        if t.kind == OP and t.value == "(":
            self.advance()
            if self.is_kw("SELECT"):
                raise self.error("subqueries are not supported")
            e = self.parse_expr()
            self.expect_op(")")
            return e
        if t.kind == ID:
            up = t.upper
            if up == "NULL":
                self.advance()
                return n.Literal(None)
            if up == "CASE":
                return self.parse_case()
            if up == "CAST":
                self.advance()
                self.expect_op("(")
                e = self.parse_expr()
                self.expect_kw("AS")
                parts = []
                while self.tok.kind == ID and not self.is_op(")"):
                    parts.append(self.advance().value)
                if not parts:
                    raise self.error()
                if self.match_op("("):
                    self._skip_parens()
                self.expect_op(")")
                return n.Cast(e, " ".join(parts))
            if up == "EXISTS":
                raise self.error("subqueries are not supported")
        if self.is_name():
            nxt = self.peek()
            if t.kind == ID and nxt.kind == OP and nxt.value == "(":
                return self.parse_function()
            name = self.name()
            if self.match_op("."):
                col = self.name()
                return n.Column(name, col)
            return n.Column(None, name)
        raise self.error()

    def parse_function(self) -> n.Expr:
        name = self.advance().upper
        self.expect_op("(")
        if self.match_op("*"):
            self.expect_op(")")
            if name != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            return n.Func(name, [], star=True)
        distinct = bool(self.match_kw("DISTINCT"))
        args: list[n.Expr] = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.match_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return n.Func(name, args, distinct=distinct)

    def parse_case(self) -> n.Expr:
        self.expect_kw("CASE")
        operand = None
        if not self.is_kw("WHEN"):
            operand = self.parse_expr()
        whens = []
        while self.match_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.match_kw("ELSE") else None
        self.expect_kw("END")
        return n.Case(operand, whens, else_)

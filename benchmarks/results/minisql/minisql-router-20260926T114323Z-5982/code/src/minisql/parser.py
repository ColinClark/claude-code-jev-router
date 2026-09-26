"""Recursive-descent SQL parser producing :mod:`minisql.nodes` trees.

Operator precedence follows SQLite (lowest to highest)::

    OR
    AND
    NOT (prefix)
    =  ==  !=  <>  IS [NOT]  IN  LIKE  GLOB  BETWEEN  ISNULL  NOTNULL
    <  <=  >  >=
    &  |  <<  >>
    +  -
    *  /  %
    ||
    unary - + ~
"""

from __future__ import annotations

from minisql import nodes as n
from minisql.errors import SQLError
from minisql.tokenizer import Token, tokenize

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Words that terminate a column type name in CREATE TABLE (column constraints).
_CONSTRAINT_WORDS = frozenset(
    {
        "PRIMARY",
        "UNIQUE",
        "CHECK",
        "DEFAULT",
        "REFERENCES",
        "CONSTRAINT",
        "AUTOINCREMENT",
        "GENERATED",
        "FOREIGN",
    }
)


# Binary operator precedence (higher binds tighter); prefix NOT sits between AND and EQ.
_P_OR = 1
_P_AND = 2
_P_EQ = 4
_P_REL = 5
_P_BIT = 6
_P_ADD = 7
_P_MUL = 8
_P_CONCAT = 9
_OP_PREC = {
    "=": _P_EQ,
    "==": _P_EQ,
    "!=": _P_EQ,
    "<>": _P_EQ,
    "<": _P_REL,
    "<=": _P_REL,
    ">": _P_REL,
    ">=": _P_REL,
    "&": _P_BIT,
    "|": _P_BIT,
    "<<": _P_BIT,
    ">>": _P_BIT,
    "+": _P_ADD,
    "-": _P_ADD,
    "*": _P_MUL,
    "/": _P_MUL,
    "%": _P_MUL,
    "||": _P_CONCAT,
}


def parse(sql: str) -> n.Statement:
    return _Parser(sql).parse_statement()


def _describe(tok: Token) -> str:
    if tok.kind == "EOF":
        return "end of input"
    if tok.kind in ("KW", "ID"):
        return str(tok.text or tok.value)
    if tok.kind == "STR":
        return "'" + str(tok.value) + "'"
    if tok.kind == "QID":
        return str(tok.value)
    if tok.kind in ("INT", "FLOAT"):
        return tok.text
    return str(tok.value)


class _Parser:
    def __init__(self, sql: str) -> None:
        self.toks = tokenize(sql)
        self.pos = 0

    # ------------------------------------------------------------ helpers
    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.toks) - 1)
        return self.toks[idx]

    def advance(self) -> Token:
        tok = self.toks[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def error(self, tok: Token | None = None) -> SQLError:
        tok = tok or self.peek()
        if tok.kind == "EOF":
            return SQLError("incomplete input")
        return SQLError(f'near "{_describe(tok)}": syntax error')

    def at_kw(self, *words: str) -> bool:
        tok = self.peek()
        return tok.kind == "KW" and tok.value in words

    def at_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok.kind == "OP" and tok.value in ops

    def accept_kw(self, word: str) -> bool:
        if self.at_kw(word):
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
            raise self.error()

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def at_name(self) -> bool:
        return self.peek().kind in ("ID", "QID")

    def expect_name(self) -> str:
        tok = self.peek()
        if tok.kind in ("ID", "QID"):
            self.advance()
            return str(tok.value)
        raise self.error()

    # --------------------------------------------------------- statements
    def parse_statement(self) -> n.Statement:
        tok = self.peek()
        if tok.kind == "KW" and tok.value == "SELECT":
            stmt: n.Statement = self.parse_select()
        elif tok.kind == "KW" and tok.value == "CREATE":
            stmt = self.parse_create()
        elif tok.kind == "KW" and tok.value == "DROP":
            stmt = self.parse_drop()
        elif tok.kind == "KW" and tok.value == "INSERT":
            stmt = self.parse_insert()
        elif tok.kind == "KW" and tok.value == "UPDATE":
            stmt = self.parse_update()
        elif tok.kind == "KW" and tok.value == "DELETE":
            stmt = self.parse_delete()
        else:
            raise self.error()
        if self.accept_op(";"):
            while self.accept_op(";"):
                pass
            if self.peek().kind != "EOF":
                raise SQLError("You can only execute one statement at a time.")
        if self.peek().kind != "EOF":
            raise self.error()
        return stmt

    def parse_create(self) -> n.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.expect_name()
        if self.at_op("."):
            raise SQLError("schema-qualified table names are not supported")
        self.expect_op("(")
        cols: list[n.ColumnDef] = []
        while True:
            tok = self.peek()
            if tok.kind == "ID" and str(tok.value).upper() in _CONSTRAINT_WORDS:
                raise SQLError("table constraints are not supported")
            col_name = self.expect_name()
            type_name = self.parse_type_name(allow_empty=True)
            if not (self.at_op(",") or self.at_op(")")):
                raise SQLError(f"unsupported column definition for {col_name!r}")
            cols.append(n.ColumnDef(col_name, type_name))
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        return n.CreateTable(name, cols, if_not_exists)

    def parse_type_name(self, allow_empty: bool) -> str:
        words: list[str] = []
        while True:
            tok = self.peek()
            if tok.kind == "ID" and str(tok.value).upper() not in _CONSTRAINT_WORDS:
                words.append(str(tok.value))
                self.advance()
                continue
            break
        if not words:
            if allow_empty:
                return ""
            raise self.error()
        if self.accept_op("("):
            self._signed_number()
            if self.accept_op(","):
                self._signed_number()
            self.expect_op(")")
        return " ".join(words)

    def _signed_number(self) -> None:
        if self.at_op("+", "-"):
            self.advance()
        if self.peek().kind not in ("INT", "FLOAT"):
            raise self.error()
        self.advance()

    def parse_drop(self) -> n.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return n.DropTable(self.expect_name(), if_exists)

    def parse_insert(self) -> n.Insert:
        self.expect_kw("INSERT")
        if self.at_kw("OR"):
            raise SQLError("INSERT OR ... is not supported")
        self.expect_kw("INTO")
        table = self.expect_name()
        columns: list[str] | None = None
        if self.accept_op("("):
            columns = [self.expect_name()]
            while self.accept_op(","):
                columns.append(self.expect_name())
            self.expect_op(")")
        if self.at_kw("SELECT"):
            return n.Insert(table, columns, None, self.parse_select())
        self.expect_kw("VALUES")
        rows: list[list[n.Expr]] = []
        while True:
            self.expect_op("(")
            row = [self.parse_expr()]
            while self.accept_op(","):
                row.append(self.parse_expr())
            self.expect_op(")")
            if rows and len(row) != len(rows[0]):
                raise SQLError("all VALUES must have the same number of terms")
            rows.append(row)
            if not self.accept_op(","):
                break
        return n.Insert(table, columns, rows)

    def parse_update(self) -> n.Update:
        self.expect_kw("UPDATE")
        table = self.expect_name()
        self.expect_kw("SET")
        assignments: list[tuple[str, n.Expr]] = []
        while True:
            col = self.expect_name()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return n.Update(table, assignments, where)

    def parse_delete(self) -> n.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.expect_name()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return n.Delete(table, where)

    # ------------------------------------------------------------- select
    def parse_select(self) -> n.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        sel = n.Select(items=items, distinct=distinct)
        if self.accept_kw("FROM"):
            sel.from_table = self.parse_table_ref()
            self.parse_joins(sel)
        if self.accept_kw("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            sel.group_by = [self.parse_expr()]
            while self.accept_op(","):
                sel.group_by.append(self.parse_expr())
        if self.accept_kw("HAVING"):
            sel.having = self.parse_expr()
        if self.at_kw("UNION", "INTERSECT", "EXCEPT"):
            raise SQLError("compound SELECT is not supported")
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            sel.order_by = [self.parse_order_term()]
            while self.accept_op(","):
                sel.order_by.append(self.parse_order_term())
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.limit, sel.offset = first, self.parse_expr()
            elif self.accept_op(","):
                sel.offset, sel.limit = first, self.parse_expr()
            else:
                sel.limit = first
        return sel

    def parse_select_item(self) -> n.SelectItem:
        if self.accept_op("*"):
            return n.SelectItem(None, is_star=True)
        if (
            self.at_name()
            and self.peek(1).kind == "OP"
            and self.peek(1).value == "."
            and self.peek(2).kind == "OP"
            and self.peek(2).value == "*"
        ):
            table = self.expect_name()
            self.advance()
            self.advance()
            return n.SelectItem(None, star_table=table, is_star=True)
        expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            tok = self.peek()
            if tok.kind in ("ID", "QID", "STR"):
                self.advance()
                alias = str(tok.value)
            else:
                raise self.error()
        elif self.peek().kind in ("ID", "QID", "STR"):
            alias = str(self.advance().value)
        return n.SelectItem(expr, alias=alias)

    def parse_table_ref(self) -> n.TableRef:
        if self.at_op("("):
            raise SQLError("subqueries in FROM are not supported")
        name = self.expect_name()
        if self.at_op("."):
            raise SQLError("schema-qualified table names are not supported")
        alias = None
        if self.accept_kw("AS"):
            alias = self.expect_name()
        elif self.at_name():
            alias = self.expect_name()
        return n.TableRef(name, alias)

    def parse_joins(self, sel: n.Select) -> None:
        while True:
            if self.accept_op(","):
                sel.joins.append(n.Join("CROSS", self.parse_table_ref(), None))
                continue
            if self.at_kw("NATURAL", "RIGHT", "FULL"):
                raise SQLError(f"{self.peek().value} JOIN is not supported")
            kind = None
            if self.accept_kw("JOIN"):
                kind = "INNER"
            elif self.accept_kw("INNER"):
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                kind = "CROSS"
            elif self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            if kind is None:
                return
            ref = self.parse_table_ref()
            on = None
            if self.accept_kw("ON"):
                on = self.parse_expr()
            elif self.at_kw("USING"):
                raise SQLError("JOIN ... USING is not supported")
            sel.joins.append(n.Join(kind, ref, on))

    def parse_order_term(self) -> n.OrderTerm:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        tok = self.peek()
        if tok.kind == "ID" and str(tok.value).upper() == "NULLS":
            self.advance()
            which = self.peek()
            if which.kind == "ID" and str(which.value).upper() in ("FIRST", "LAST"):
                self.advance()
                nulls_first = str(which.value).upper() == "FIRST"
            else:
                raise self.error()
        return n.OrderTerm(expr, desc, nulls_first)

    # --------------------------------------------------------- expressions
    def parse_expr(self) -> n.Expr:
        return self.parse_binary(_P_OR)

    def _binary_prec(self) -> int | None:
        """Precedence of the operator at the current token, or None if there is none."""
        tok = self.peek()
        if tok.kind == "OP":
            return _OP_PREC.get(str(tok.value))
        if tok.kind != "KW":
            return None
        word = tok.value
        if word == "OR":
            return _P_OR
        if word == "AND":
            return _P_AND
        if word in ("IS", "IN", "LIKE", "GLOB", "BETWEEN", "ISNULL", "NOTNULL"):
            return _P_EQ
        if word == "NOT":
            nxt = self.peek(1)
            if nxt.kind == "KW" and nxt.value in ("NULL", "IN", "LIKE", "GLOB", "BETWEEN"):
                return _P_EQ
        return None

    def parse_binary(self, min_prec: int) -> n.Expr:
        """Precedence climbing.  Postfix forms that end in a terminal (``IN (...)``,
        ``ISNULL``, ``NOTNULL``, ``NOT NULL``) leave the loop open so that a following
        higher-precedence operator takes them as its left operand, as SQLite's LALR
        grammar does (``x IN (1) >= 0`` is ``(x IN (1)) >= 0``)."""
        left = self.parse_unary()
        while True:
            prec = self._binary_prec()
            if prec is None or prec < min_prec:
                return left
            tok = self.advance()
            if tok.kind == "OP":
                op = str(tok.value)
                op = {"==": "=", "<>": "!="}.get(op, op)
                left = n.Binary(op, left, self.parse_binary(prec + 1))
                continue
            word = tok.value
            if word in ("AND", "OR"):
                left = n.Binary(str(word), left, self.parse_binary(prec + 1))
                continue
            if word == "IS":
                op = "IS NOT" if self.accept_kw("NOT") else "IS"
                left = n.Binary(op, left, self.parse_binary(_P_EQ + 1))
                continue
            if word == "ISNULL":
                left = n.Binary("IS", left, n.Literal(None))
                continue
            if word == "NOTNULL":
                left = n.Binary("IS NOT", left, n.Literal(None))
                continue
            negated = False
            if word == "NOT":
                if self.accept_kw("NULL"):
                    left = n.Binary("IS NOT", left, n.Literal(None))
                    continue
                negated = True
                word = self.advance().value
            if word == "IN":
                left = self.parse_in_rhs(left, negated)
            elif word in ("LIKE", "GLOB"):
                pattern = self.parse_binary(_P_EQ + 1)
                escape = None
                if self.accept_kw("ESCAPE"):
                    escape = self.parse_binary(_P_EQ + 1)
                left = n.Like(str(word), left, pattern, escape, negated)
            else:  # BETWEEN
                low = self.parse_binary(_P_EQ)
                self.expect_kw("AND")
                high = self.parse_binary(_P_EQ + 1)
                left = n.Between(left, low, high, negated)

    def parse_in_rhs(self, left: n.Expr, negated: bool) -> n.Expr:
        if not self.accept_op("("):
            if self.at_name():
                raise SQLError("IN <table> is not supported")
            raise self.error()
        if self.at_kw("SELECT"):
            raise SQLError("subqueries are not supported")
        items: list[n.Expr] = []
        if not self.at_op(")"):
            items.append(self.parse_expr())
            while self.accept_op(","):
                items.append(self.parse_expr())
        self.expect_op(")")
        return n.InList(left, items, negated)

    def parse_unary(self) -> n.Expr:
        if self.accept_kw("NOT"):
            # NOT binds looser than comparisons: NOT a = b is NOT (a = b).
            return n.Unary("NOT", self.parse_binary(_P_EQ))
        if self.accept_op("-"):
            operand = self.parse_unary()
            if isinstance(operand, n.Literal):
                v = operand.value
                if type(v) is int:
                    neg = -v
                    if neg < INT64_MIN or neg > INT64_MAX:
                        return n.Literal(float(neg))
                    return n.Literal(neg, int_text="-")
                if type(v) is float:
                    if operand.int_text == "9223372036854775808":
                        return n.Literal(INT64_MIN, int_text="-")
                    return n.Literal(-v)
            return n.Unary("-", operand)
        if self.accept_op("+"):
            return n.Unary("+", self.parse_unary())
        if self.accept_op("~"):
            return n.Unary("~", self.parse_unary())
        expr = self.parse_primary()
        while self.at_kw("COLLATE"):
            self.advance()
            coll = self.expect_name()
            if coll.upper() != "BINARY":
                raise SQLError(f"no such collation sequence: {coll}")
        return expr

    def parse_primary(self) -> n.Expr:
        tok = self.peek()
        kind = tok.kind
        if kind == "INT":
            self.advance()
            return n.Literal(tok.value, int_text=tok.text)
        if kind == "FLOAT":
            self.advance()
            text = tok.text if tok.text.isdigit() else None
            return n.Literal(tok.value, int_text=text)
        if kind == "STR":
            self.advance()
            return n.Literal(tok.value)
        if kind == "OP" and tok.value == "(":
            self.advance()
            if self.at_kw("SELECT"):
                raise SQLError("subqueries are not supported")
            expr = self.parse_expr()
            if self.at_op(","):
                raise SQLError("row value misused")
            self.expect_op(")")
            return expr
        if kind == "KW":
            word = tok.value
            if word == "NULL":
                self.advance()
                return n.Literal(None)
            if word == "CASE":
                return self.parse_case()
            if word == "CAST":
                self.advance()
                self.expect_op("(")
                operand = self.parse_expr()
                self.expect_kw("AS")
                type_name = self.parse_type_name(allow_empty=False)
                self.expect_op(")")
                return n.Cast(operand, type_name)
            if word == "EXISTS":
                raise SQLError("subqueries are not supported")
            raise self.error()
        if kind in ("ID", "QID"):
            self.advance()
            name = str(tok.value)
            if kind == "ID" and self.at_op("("):
                return self.parse_call(name)
            if self.at_op("."):
                self.advance()
                col = self.expect_name()
                if self.at_op("."):
                    raise SQLError("schema-qualified names are not supported")
                return n.Column(name, col)
            return n.Column(None, name, dquoted=(kind == "QID" and tok.text == '"'))
        raise self.error()

    def parse_call(self, name: str) -> n.Expr:
        self.expect_op("(")
        lname = name.lower()
        if self.accept_op("*"):
            self.expect_op(")")
            return n.Func(lname, [], star=True)
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args: list[n.Expr] = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        elif distinct:
            raise self.error()
        self.expect_op(")")
        if self.peek().kind == "ID" and str(self.peek().value).upper() in ("FILTER", "OVER"):
            raise SQLError("window functions and FILTER are not supported")
        return n.Func(lname, args, distinct=distinct)

    def parse_case(self) -> n.Expr:
        self.expect_kw("CASE")
        operand = None
        if not self.at_kw("WHEN"):
            operand = self.parse_expr()
        whens: list[tuple[n.Expr, n.Expr]] = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return n.Case(operand, whens, else_)

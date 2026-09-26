"""Recursive-descent SQL parser producing AST nodes."""

from __future__ import annotations

from . import ast as A
from .errors import SQLError
from .tokenizer import Token, tokenize

# Keywords that can never be used as bare identifiers / implicit aliases.
RESERVED = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST CREATE CROSS DELETE DESC DISTINCT DROP ELSE END
    ESCAPE EXCEPT EXISTS FROM FULL GLOB GROUP HAVING IN INNER INSERT INTERSECT INTO IS ISNULL
    JOIN LEFT LIKE LIMIT NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT SELECT SET
    TABLE THEN UNION UPDATE USING VALUES WHEN WHERE
    """.split()
)

AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"})


class Parser:
    def __init__(self, sql: str):
        self.tokens = tokenize(sql)
        self.pos = 0

    # -- token helpers -----------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, k: int = 1) -> Token:
        return self.tokens[min(self.pos + k, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def error(self, t: Token | None = None) -> SQLError:
        t = t or self.tok
        if t.kind == "EOF":
            return SQLError("incomplete input")
        return SQLError(f'near "{t.value}": syntax error')

    def is_kw(self, *words: str) -> bool:
        return self.tok.upper in words

    def accept_kw(self, *words: str) -> bool:
        if self.tok.upper in words:
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error()

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.value in ops

    def accept_op(self, op: str) -> bool:
        if self.is_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def identifier(self) -> str:
        t = self.tok
        if t.kind == "QNAME":
            self.advance()
            return str(t.value)
        if t.kind == "NAME" and t.upper not in RESERVED:
            self.advance()
            return str(t.value)
        raise self.error()

    def optional_alias(self) -> str | None:
        if self.accept_kw("AS"):
            if self.tok.kind == "STR":
                return str(self.advance().value)
            return self.identifier()
        t = self.tok
        if t.kind == "QNAME" or (t.kind == "NAME" and t.upper not in RESERVED):
            self.advance()
            return str(t.value)
        if t.kind == "STR":
            self.advance()
            return str(t.value)
        return None

    # -- statements --------------------------------------------------------

    def parse_statement(self) -> A.Statement | None:
        while self.accept_op(";"):
            pass
        if self.tok.kind == "EOF":
            return None
        kw = self.tok.upper
        if kw == "SELECT":
            stmt: A.Statement = self.parse_select()
        elif kw == "CREATE":
            stmt = self.parse_create()
        elif kw == "DROP":
            stmt = self.parse_drop()
        elif kw == "INSERT":
            stmt = self.parse_insert()
        elif kw == "UPDATE":
            stmt = self.parse_update()
        elif kw == "DELETE":
            stmt = self.parse_delete()
        else:
            raise self.error()
        while self.accept_op(";"):
            pass
        if self.tok.kind != "EOF":
            raise self.error()
        return stmt

    def parse_create(self) -> A.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.identifier()
        self.expect_op("(")
        cols: list[A.ColumnDef] = []
        while True:
            if self.is_kw("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"):
                self.skip_constraint_tokens()
            else:
                col_name = self.identifier()
                type_words: list[str] = []
                while self.tok.kind == "NAME" and self.tok.upper not in (
                    "PRIMARY", "NOT", "NULL", "UNIQUE", "CHECK", "DEFAULT",
                    "REFERENCES", "CONSTRAINT", "COLLATE", "GENERATED", "AS",
                ):
                    type_words.append(str(self.advance().value))
                if type_words and self.accept_op("("):
                    self.skip_parens()
                self.skip_constraint_tokens()
                cols.append(A.ColumnDef(col_name, " ".join(type_words) or None))
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        return A.CreateTable(name, cols, if_not_exists)

    def skip_parens(self) -> None:
        depth = 1
        while depth:
            t = self.advance()
            if t.kind == "EOF":
                raise self.error(t)
            if t.kind == "OP" and t.value == "(":
                depth += 1
            elif t.kind == "OP" and t.value == ")":
                depth -= 1

    def skip_constraint_tokens(self) -> None:
        while not (self.is_op(",", ")") or self.tok.kind == "EOF"):
            if self.accept_op("("):
                self.skip_parens()
            else:
                self.advance()

    def parse_drop(self) -> A.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return A.DropTable(self.identifier(), if_exists)

    def parse_insert(self) -> A.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.identifier()
        columns: list[str] | None = None
        if self.accept_op("("):
            columns = [self.identifier()]
            while self.accept_op(","):
                columns.append(self.identifier())
            self.expect_op(")")
        if self.is_kw("SELECT"):
            return A.Insert(table, columns, None, self.parse_select())
        self.expect_kw("VALUES")
        rows: list[list[A.Expr]] = []
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
        return A.Insert(table, columns, rows, None)

    def parse_update(self) -> A.Update:
        self.expect_kw("UPDATE")
        table = self.identifier()
        self.expect_kw("SET")
        assigns: list[tuple[str, A.Expr]] = []
        while True:
            col = self.identifier()
            self.expect_op("=")
            assigns.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return A.Update(table, assigns, where)

    def parse_delete(self) -> A.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.identifier()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return A.Delete(table, where)

    def parse_select(self) -> A.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items: list[A.SelectItem | A.Star] = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        sel = A.Select(distinct, items, None)
        if self.accept_kw("FROM"):
            sel.from_ = self.parse_table_ref()
            while True:
                if self.accept_op(","):
                    sel.joins.append(A.Join("CROSS", self.parse_table_ref(), None))
                    continue
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
                    break
                ref = self.parse_table_ref()
                on = None
                if self.accept_kw("ON"):
                    on = self.parse_expr()
                sel.joins.append(A.Join(kind, ref, on))
        if self.accept_kw("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            sel.group_by = [self.parse_expr()]
            while self.accept_op(","):
                sel.group_by.append(self.parse_expr())
        if self.accept_kw("HAVING"):
            sel.having = self.parse_expr()
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

    def parse_select_item(self) -> A.SelectItem | A.Star:
        if self.accept_op("*"):
            return A.Star(None)
        t = self.tok
        if (
            t.kind in ("NAME", "QNAME")
            and self.peek().kind == "OP"
            and self.peek().value == "."
            and self.peek(2).kind == "OP"
            and self.peek(2).value == "*"
        ):
            name = self.identifier()
            self.advance()
            self.advance()
            return A.Star(name)
        expr = self.parse_expr()
        return A.SelectItem(expr, self.optional_alias())

    def parse_table_ref(self) -> A.TableRef:
        name = self.identifier()
        alias = None
        if self.accept_kw("AS"):
            alias = self.identifier()
        elif self.tok.kind == "QNAME" or (
            self.tok.kind == "NAME" and self.tok.upper not in RESERVED
        ):
            alias = self.identifier()
        return A.TableRef(name, alias)

    def parse_order_term(self) -> A.OrderTerm:
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
        return A.OrderTerm(expr, desc, nulls_first)

    # -- expressions -------------------------------------------------------

    def parse_expr(self) -> A.Expr:
        return self.parse_or()

    def parse_or(self) -> A.Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = A.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> A.Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = A.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> A.Expr:
        if self.accept_kw("NOT"):
            return A.Unary("NOT", self.parse_not())
        return self.parse_equality()

    def parse_equality(self) -> A.Expr:
        left = self.parse_comparison()
        while True:
            t = self.tok
            if t.kind == "OP" and t.value in ("=", "==", "!=", "<>"):
                self.advance()
                op = {"==": "=", "<>": "!="}.get(str(t.value), str(t.value))
                left = A.Binary(op, left, self.parse_comparison())
                continue
            kw = t.upper
            if kw == "IS":
                self.advance()
                negated = self.accept_kw("NOT")
                if self.accept_kw("DISTINCT"):
                    self.expect_kw("FROM")
                    negated = not negated
                right = self.parse_comparison()
                left = A.Binary("ISNOT" if negated else "IS", left, right)
                continue
            if kw == "ISNULL":
                self.advance()
                left = A.Binary("IS", left, A.Literal(None))
                continue
            if kw == "NOTNULL":
                self.advance()
                left = A.Binary("ISNOT", left, A.Literal(None))
                continue
            negated = False
            if kw == "NOT":
                nxt = self.peek().upper
                if nxt == "NULL":
                    self.advance()
                    self.advance()
                    left = A.Binary("ISNOT", left, A.Literal(None))
                    continue
                if nxt not in ("IN", "BETWEEN", "LIKE", "GLOB"):
                    break
                self.advance()
                negated = True
                kw = self.tok.upper
            if kw == "IN":
                self.advance()
                self.expect_op("(")
                items: list[A.Expr] = []
                if not self.is_op(")"):
                    items.append(self.parse_expr())
                    while self.accept_op(","):
                        items.append(self.parse_expr())
                self.expect_op(")")
                left = A.InList(left, items, negated)
                continue
            if kw == "BETWEEN":
                self.advance()
                low = self.parse_between_low()
                self.expect_kw("AND")
                high = self.parse_comparison()
                left = A.Between(left, low, high, negated)
                continue
            if kw == "LIKE":
                self.advance()
                pattern = self.parse_comparison()
                escape = None
                if self.accept_kw("ESCAPE"):
                    escape = self.parse_comparison()
                left = A.Like(left, pattern, escape, negated)
                continue
            if negated:
                raise self.error()
            break
        return left

    def parse_between_low(self) -> A.Expr:
        # The operand between BETWEEN and AND may use NOT and equality-level operators,
        # but not a bare AND/OR (SQLite's grammar rejects those there).
        return self.parse_not()

    def parse_comparison(self) -> A.Expr:
        left = self.parse_bitwise()
        while self.is_op("<", "<=", ">", ">="):
            op = str(self.advance().value)
            left = A.Binary(op, left, self.parse_bitwise())
        return left

    def parse_bitwise(self) -> A.Expr:
        left = self.parse_additive()
        while self.is_op("&", "|", "<<", ">>"):
            op = str(self.advance().value)
            left = A.Binary(op, left, self.parse_additive())
        return left

    def parse_additive(self) -> A.Expr:
        left = self.parse_multiplicative()
        while self.is_op("+", "-"):
            op = str(self.advance().value)
            left = A.Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> A.Expr:
        left = self.parse_concat()
        while self.is_op("*", "/", "%"):
            op = str(self.advance().value)
            left = A.Binary(op, left, self.parse_concat())
        return left

    def parse_concat(self) -> A.Expr:
        left = self.parse_unary()
        while self.is_op("||"):
            self.advance()
            left = A.Binary("||", left, self.parse_unary())
        return left

    def parse_unary(self) -> A.Expr:
        if self.is_op("-", "+", "~"):
            op = str(self.advance().value)
            nxt = self.tok
            if (
                op == "-"
                and nxt.kind == "NUM"
                and nxt.text.isdigit()
                and int(nxt.text) == 2**63
            ):
                self.advance()
                return A.Literal(-(2**63))
            return A.Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> A.Expr:
        t = self.tok
        if t.kind == "NUM":
            self.advance()
            return A.Literal(t.value)
        if t.kind == "STR":
            self.advance()
            return A.Literal(t.value)
        if self.accept_op("("):
            e = self.parse_expr()
            self.expect_op(")")
            return e
        kw = t.upper
        if kw == "NULL":
            self.advance()
            return A.Literal(None)
        if kw in ("TRUE", "FALSE") and not (
            self.peek().kind == "OP" and self.peek().value in (".", "(")
        ):
            self.advance()
            return A.Literal(1 if kw == "TRUE" else 0)
        if kw == "CASE":
            return self.parse_case()
        if kw == "CAST":
            self.advance()
            self.expect_op("(")
            e = self.parse_expr()
            self.expect_kw("AS")
            words = []
            while self.tok.kind == "NAME":
                words.append(str(self.advance().value))
            if not words:
                raise self.error()
            if self.accept_op("("):
                self.skip_parens()
            self.expect_op(")")
            return A.Cast(e, " ".join(words))
        if t.kind in ("NAME", "QNAME"):
            if t.kind == "NAME" and kw in RESERVED:
                raise self.error()
            name = str(self.advance().value)
            if t.kind == "NAME" and self.is_op("("):
                return self.parse_call(name.upper())
            if self.accept_op("."):
                col = self.identifier()
                return A.Column(name, col)
            return A.Column(None, name)
        raise self.error()

    def parse_call(self, name: str) -> A.Expr:
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            if name != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            return A.Func(name, [], star=True)
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args: list[A.Expr] = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        if distinct and len(args) != 1:
            raise SQLError("DISTINCT aggregates must have exactly one argument")
        return A.Func(name, args, distinct=distinct)

    def parse_case(self) -> A.Expr:
        self.expect_kw("CASE")
        operand = None
        if not self.is_kw("WHEN"):
            operand = self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return A.Case(operand, whens, else_)


def parse(sql: str) -> A.Statement | None:
    return Parser(sql).parse_statement()

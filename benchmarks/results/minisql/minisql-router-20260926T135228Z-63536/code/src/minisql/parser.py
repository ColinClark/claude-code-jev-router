"""Tokenizer and recursive-descent parser for the supported SQL subset."""

from __future__ import annotations

from dataclasses import dataclass

from . import ast
from .errors import SQLError
from .values import INT_MAX

RESERVED = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST COLLATE CREATE CROSS DEFAULT DELETE DESC DISTINCT DROP
    ELSE END ESCAPE EXCEPT EXISTS FROM FULL GLOB GROUP HAVING IN INNER INSERT INTERSECT INTO IS
    ISNULL JOIN LEFT LIKE LIMIT NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER PRIMARY
    REFERENCES RIGHT SELECT SET TABLE THEN UNION UNIQUE UPDATE USING VALUES WHEN WHERE
    """.split()
)


@dataclass
class Token:
    kind: str  # 'num', 'str', 'id', 'op', 'eof'
    value: object
    pos: int
    quoted: bool = False
    text: str = ""


_OPS2 = ("||", "<=", ">=", "<>", "!=", "==", "<<", ">>")
_OPS1 = "(),;.+-*/%<>=&|~"


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ord(ch) > 127


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        if ch == "'":
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated string literal")
                c = sql[i]
                if c == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(Token("str", "".join(buf), start))
            continue
        if ch in "\"`[":
            close = {'"': '"', "`": "`", "[": "]"}[ch]
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated identifier")
                c = sql[i]
                if c == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        buf.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            name = "".join(buf)
            tokens.append(Token("id", name, start, quoted=True, text=name))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            if ch == "0" and i + 1 < n and sql[i + 1] in "xX":
                j = i + 2
                while j < n and sql[j] in "0123456789abcdefABCDEF":
                    j += 1
                if j == i + 2:
                    raise SQLError(f'unrecognized token: "{sql[i:j]}"')
                v = int(sql[i + 2 : j], 16)
                if v >= 2**64:
                    raise SQLError(f'hex literal too big: "{sql[i:j]}"')
                if v > INT_MAX:
                    v -= 2**64
                i = j
                tokens.append(Token("num", v, start))
                continue
            j = i
            is_float = False
            while j < n and sql[j].isdigit():
                j += 1
            if j < n and sql[j] == ".":
                is_float = True
                j += 1
                while j < n and sql[j].isdigit():
                    j += 1
            if j < n and sql[j] in "eE":
                k = j + 1
                if k < n and sql[k] in "+-":
                    k += 1
                if k < n and sql[k].isdigit():
                    is_float = True
                    while k < n and sql[k].isdigit():
                        k += 1
                    j = k
                else:
                    raise SQLError(f'unrecognized token: "{sql[i:k]}"')
            if j < n and _is_ident_char(sql[j]):
                raise SQLError(f'unrecognized token: "{sql[i : j + 1]}"')
            text = sql[i:j]
            if is_float:
                value: object = float(text)
            else:
                iv = int(text)
                value = iv if iv <= INT_MAX else float(iv)
            tokens.append(Token("num", value, start, text=text))
            i = j
            continue
        if _is_ident_start(ch):
            j = i + 1
            while j < n and _is_ident_char(sql[j]):
                j += 1
            word = sql[i:j]
            tokens.append(Token("id", word, start, text=word))
            i = j
            continue
        two = sql[i : i + 2]
        if two in _OPS2:
            tokens.append(Token("op", two, start))
            i += 2
            continue
        if ch in _OPS1:
            tokens.append(Token("op", ch, start))
            i += 1
            continue
        raise SQLError(f'unrecognized token: "{ch}"')
    tokens.append(Token("eof", None, n))
    return tokens


class Parser:
    def __init__(self, sql: str):
        self.sql = sql
        self.tokens = tokenize(sql)
        self.pos = 0

    # -- token helpers ------------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, tok: Token | None = None) -> SQLError:
        tok = tok or self.peek()
        if tok.kind == "eof":
            return SQLError("incomplete input")
        near = tok.text or (repr(tok.value) if tok.kind == "str" else str(tok.value))
        return SQLError(f'near "{near}": syntax error')

    def is_kw(self, word: str, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok.kind == "id" and not tok.quoted and str(tok.value).upper() == word

    def accept_kw(self, word: str) -> bool:
        if self.is_kw(word):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error()

    def is_op(self, op: str, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok.kind == "op" and tok.value == op

    def accept_op(self, op: str) -> bool:
        if self.is_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error()

    def is_name(self, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok.kind == "id" and (tok.quoted or str(tok.value).upper() not in RESERVED)

    def parse_name(self) -> str:
        if not self.is_name():
            raise self.error()
        return str(self.advance().value)

    # -- statements ---------------------------------------------------------
    def parse_statement(self):
        if self.peek().kind == "eof":
            raise SQLError("empty statement")
        if self.is_kw("SELECT"):
            stmt = self.parse_select()
        elif self.is_kw("INSERT"):
            stmt = self.parse_insert()
        elif self.is_kw("UPDATE"):
            stmt = self.parse_update()
        elif self.is_kw("DELETE"):
            stmt = self.parse_delete()
        elif self.is_kw("CREATE"):
            stmt = self.parse_create()
        elif self.is_kw("DROP"):
            stmt = self.parse_drop()
        else:
            raise self.error()
        while self.accept_op(";"):
            pass
        if self.peek().kind != "eof":
            raise self.error()
        return stmt

    def parse_type_name(self) -> str | None:
        words = []
        while self.peek().kind == "id" and not self.peek().quoted and (
            str(self.peek().value).upper() not in RESERVED
        ):
            words.append(str(self.advance().value))
        if not words:
            return None
        if self.accept_op("("):
            self._parse_signed_number()
            if self.accept_op(","):
                self._parse_signed_number()
            self.expect_op(")")
        return " ".join(words)

    def _parse_signed_number(self):
        sign = 1
        if self.accept_op("-"):
            sign = -1
        else:
            self.accept_op("+")
        tok = self.advance()
        if tok.kind != "num":
            raise self.error(tok)
        return sign * tok.value

    def parse_create(self) -> ast.CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        if_not_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True
        name = self.parse_name()
        self.expect_op("(")
        cols = []
        while True:
            cname = self.parse_name()
            tname = self.parse_type_name()
            col = ast.ColumnDef(cname, tname)
            while True:
                if self.accept_kw("NOT"):
                    self.expect_kw("NULL")
                    col.not_null = True
                elif self.accept_kw("NULL"):
                    pass
                elif self.accept_kw("DEFAULT"):
                    if self.accept_op("("):
                        col.default = self.parse_expr()
                        self.expect_op(")")
                    elif self.is_op("-") or self.is_op("+"):
                        col.default = ast.Literal(self._parse_signed_number())
                    else:
                        tok = self.advance()
                        if tok.kind in ("num", "str"):
                            col.default = ast.Literal(tok.value)
                        elif tok.kind == "id" and not tok.quoted and tok.value.upper() == "NULL":
                            col.default = ast.Literal(None)
                        else:
                            raise self.error(tok)
                else:
                    break
            cols.append(col)
            if self.accept_op(","):
                continue
            self.expect_op(")")
            break
        return ast.CreateTable(name, cols, if_not_exists)

    def parse_drop(self) -> ast.DropTable:
        self.expect_kw("DROP")
        self.expect_kw("TABLE")
        if_exists = False
        if self.accept_kw("IF"):
            self.expect_kw("EXISTS")
            if_exists = True
        return ast.DropTable(self.parse_name(), if_exists)

    def parse_insert(self) -> ast.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.parse_name()
        columns = None
        if self.accept_op("("):
            columns = [self.parse_name()]
            while self.accept_op(","):
                columns.append(self.parse_name())
            self.expect_op(")")
        if self.is_kw("SELECT"):
            return ast.Insert(table, columns, None, self.parse_select())
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
        table = self.parse_name()
        self.expect_kw("SET")
        assignments = []
        while True:
            col = self.parse_name()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if not self.accept_op(","):
                break
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return ast.Update(table, assignments, where)

    def parse_delete(self) -> ast.Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.parse_name()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        return ast.Delete(table, where)

    def _parse_alias(self) -> str | None:
        if self.accept_kw("AS"):
            tok = self.peek()
            if tok.kind == "str":
                self.advance()
                return str(tok.value)
            return self.parse_name()
        if self.is_name():
            return str(self.advance().value)
        if self.peek().kind == "str":
            return str(self.advance().value)
        return None

    def parse_select(self) -> ast.Select:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        items = [self._parse_select_item()]
        while self.accept_op(","):
            items.append(self._parse_select_item())
        sel = ast.Select(distinct, items)
        if self.accept_kw("FROM"):
            sel.sources = self._parse_from()
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
            sel.order_by = [self._parse_order_term()]
            while self.accept_op(","):
                sel.order_by.append(self._parse_order_term())
        if self.accept_kw("LIMIT"):
            first = self.parse_expr()
            if self.accept_kw("OFFSET"):
                sel.limit = first
                sel.offset = self.parse_expr()
            elif self.accept_op(","):
                sel.offset = first
                sel.limit = self.parse_expr()
            else:
                sel.limit = first
        if self.is_kw("UNION") or self.is_kw("INTERSECT") or self.is_kw("EXCEPT"):
            raise SQLError("compound SELECT is not supported")
        return sel

    def _parse_select_item(self) -> ast.SelectItem:
        if self.accept_op("*"):
            return ast.SelectItem(ast.Star(None), None)
        if self.is_name() and self.is_op(".", 1) and self.is_op("*", 2):
            table = self.parse_name()
            self.advance()
            self.advance()
            return ast.SelectItem(ast.Star(table), None)
        expr = self.parse_expr()
        return ast.SelectItem(expr, self._parse_alias())

    def _parse_order_term(self) -> ast.OrderTerm:
        expr = self.parse_expr()
        if self.accept_kw("COLLATE"):
            raise SQLError("COLLATE is not supported")
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        if self.accept_kw("NULLS"):
            raise SQLError("NULLS FIRST/LAST is not supported")
        return ast.OrderTerm(expr, desc)

    def _parse_table_ref(self, join: str) -> ast.TableRef:
        if self.is_op("("):
            raise SQLError("subqueries in FROM are not supported")
        name = self.parse_name()
        alias = None
        if self.accept_kw("AS"):
            alias = self.parse_name()
        elif self.is_name():
            alias = str(self.advance().value)
        return ast.TableRef(name, alias, join)

    def _parse_from(self) -> list[ast.TableRef]:
        refs = [self._parse_table_ref("FIRST")]
        while True:
            if self.accept_op(","):
                refs.append(self._parse_table_ref("CROSS"))
                continue
            if self.is_kw("NATURAL") or self.is_kw("RIGHT") or self.is_kw("FULL"):
                raise SQLError(f"{self.peek().value.upper()} JOIN is not supported")
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
            ref = self._parse_table_ref(kind)
            if self.accept_kw("ON"):
                ref.on = self.parse_expr()
            elif self.is_kw("USING"):
                raise SQLError("JOIN ... USING is not supported")
            refs.append(ref)
        return refs

    # -- expressions --------------------------------------------------------
    def parse_expr(self) -> ast.Expr:
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while self.accept_kw("OR"):
            left = ast.Binary("OR", left, self._parse_and())
        return left

    def _parse_and(self):
        left = self._parse_not()
        while self.accept_kw("AND"):
            left = ast.Binary("AND", left, self._parse_not())
        return left

    def _parse_not(self):
        if self.accept_kw("NOT"):
            return ast.Unary("NOT", self._parse_not())
        return self._parse_equality()

    def _parse_equality(self):
        left = self._parse_relational()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("=", "==", "!=", "<>"):
                self.advance()
                op = "=" if tok.value in ("=", "==") else "!="
                left = ast.Binary(op, left, self._parse_relational())
                continue
            if self.accept_kw("IS"):
                negated = self.accept_kw("NOT")
                if self.is_kw("DISTINCT"):
                    raise SQLError("IS DISTINCT FROM is not supported")
                right = self._parse_relational()
                left = ast.Binary("ISNOT" if negated else "IS", left, right)
                continue
            if self.accept_kw("ISNULL"):
                left = ast.Binary("IS", left, ast.Literal(None))
                continue
            if self.accept_kw("NOTNULL"):
                left = ast.Binary("ISNOT", left, ast.Literal(None))
                continue
            negated = False
            if self.is_kw("NOT") and (
                self.is_kw("IN", 1)
                or self.is_kw("LIKE", 1)
                or self.is_kw("BETWEEN", 1)
                or self.is_kw("NULL", 1)
                or self.is_kw("GLOB", 1)
            ):
                self.advance()
                negated = True
                if self.accept_kw("NULL"):
                    left = ast.Binary("ISNOT", left, ast.Literal(None))
                    continue
            if self.accept_kw("IN"):
                left = self._parse_in(left, negated)
                continue
            if self.accept_kw("LIKE"):
                pattern = self._parse_relational()
                escape = None
                if self.accept_kw("ESCAPE"):
                    escape = self._parse_relational()
                left = ast.Like(left, pattern, escape, negated)
                continue
            if self.accept_kw("BETWEEN"):
                low = self._parse_relational()
                self.expect_kw("AND")
                high = self._parse_relational()
                left = ast.Between(left, low, high, negated)
                continue
            if self.is_kw("GLOB"):
                raise SQLError("GLOB is not supported")
            if negated:
                raise self.error()
            return left

    def _parse_in(self, left, negated):
        self.expect_op("(")
        if self.is_kw("SELECT"):
            raise SQLError("subqueries are not supported")
        items = []
        if not self.is_op(")"):
            items.append(self.parse_expr())
            while self.accept_op(","):
                items.append(self.parse_expr())
        self.expect_op(")")
        if not items:
            # SQLite folds an empty IN list into the constant TRUE / FALSE.
            return ast.BoolLiteral(1 if negated else 0)
        return ast.InList(left, items, negated)

    def _parse_relational(self):
        left = self._parse_bitwise()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("<", "<=", ">", ">="):
                self.advance()
                left = ast.Binary(tok.value, left, self._parse_bitwise())
            else:
                return left

    def _parse_bitwise(self):
        left = self._parse_additive()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("&", "|", "<<", ">>"):
                self.advance()
                left = ast.Binary(tok.value, left, self._parse_additive())
            else:
                return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("+", "-"):
                self.advance()
                left = ast.Binary(tok.value, left, self._parse_multiplicative())
            else:
                return left

    def _parse_multiplicative(self):
        left = self._parse_concat()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("*", "/", "%"):
                self.advance()
                left = ast.Binary(tok.value, left, self._parse_concat())
            else:
                return left

    def _parse_concat(self):
        left = self._parse_unary()
        while self.accept_op("||"):
            left = ast.Binary("||", left, self._parse_unary())
        return left

    def _parse_unary(self):
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("-", "+", "~"):
            self.advance()
            return ast.Unary(tok.value, self._parse_unary())
        expr = self._parse_primary()
        if self.is_kw("COLLATE"):
            raise SQLError("COLLATE is not supported")
        return expr

    def _parse_primary(self):
        tok = self.peek()
        if tok.kind in ("num", "str"):
            self.advance()
            return ast.Literal(tok.value)
        if tok.kind == "op":
            if tok.value == "(":
                self.advance()
                if self.is_kw("SELECT"):
                    raise SQLError("subqueries are not supported")
                expr = self.parse_expr()
                if self.is_op(","):
                    raise SQLError("row values are not supported")
                self.expect_op(")")
                return expr
            raise self.error()
        if tok.kind != "id":
            raise self.error()
        word = str(tok.value).upper() if not tok.quoted else None
        if word == "NULL":
            self.advance()
            return ast.Literal(None)
        if word == "CASE":
            return self._parse_case()
        if word == "CAST":
            self.advance()
            self.expect_op("(")
            expr = self.parse_expr()
            self.expect_kw("AS")
            tname = self.parse_type_name()
            self.expect_op(")")
            return ast.Cast(expr, tname or "")
        if word == "EXISTS":
            raise SQLError("subqueries are not supported")
        if word in RESERVED:
            raise self.error()
        if word in ("TRUE", "FALSE") and not self.is_op("(", 1) and not self.is_op(".", 1):
            self.advance()
            return ast.BoolLiteral(1 if word == "TRUE" else 0)
        self.advance()
        name = str(tok.value)
        if self.accept_op("("):
            return self._parse_function_args(name)
        if self.accept_op("."):
            col = self.parse_name()
            if self.is_op("."):
                raise SQLError("schema-qualified names are not supported")
            return ast.ColumnRef(name, col)
        return ast.ColumnRef(None, name)

    def _parse_function_args(self, name: str) -> ast.FuncCall:
        if self.accept_op("*"):
            self.expect_op(")")
            return ast.FuncCall(name.lower(), [], star=True)
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        args = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        if self.is_kw("FILTER") or self.is_kw("OVER"):
            raise SQLError("window functions and FILTER are not supported")
        return ast.FuncCall(name.lower(), args, distinct=distinct)

    def _parse_case(self) -> ast.Case:
        self.expect_kw("CASE")
        base = None
        if not self.is_kw("WHEN"):
            base = self.parse_expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.parse_expr()
            self.expect_kw("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error()
        else_ = self.parse_expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return ast.Case(base, whens, else_)


def parse(sql: str):
    if not isinstance(sql, str):
        raise SQLError("SQL must be a string")
    return Parser(sql).parse_statement()

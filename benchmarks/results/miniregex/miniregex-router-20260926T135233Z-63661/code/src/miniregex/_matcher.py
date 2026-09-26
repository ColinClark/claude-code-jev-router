"""Backtracking matcher compiled from the parser's AST.

Each AST node is compiled into a function ``m(s, i, caps, k)``:

- ``s`` is the subject string, ``i`` the current position,
- ``caps`` an immutable tuple of capture positions (``2 * ngroups`` ints,
  ``-1`` meaning unset; group ``g`` occupies slots ``2*(g-1)`` and
  ``2*(g-1)+1``),
- ``k(j, caps)`` is the continuation: the rest of the pattern.

A matcher returns the continuation's result (a non-``None`` value) on
success, or ``None`` to make the caller backtrack. Because the continuation
always includes the entire rest of the pattern, alternatives and quantifier
iteration counts are explored in exactly the order Python's ``sre`` engine
explores them; the first overall success wins. Captures are immutable, so
backtracking restores them automatically, and a group inside a repetition is
left holding the span of the last iteration that matched.

Repetition of multi-character sub-patterns mirrors ``sre``'s
``REPEAT``/``MAX_UNTIL``/``MIN_UNTIL`` opcodes, including their zero-width
iteration protection (an optional iteration is not attempted again at the
position where the previous optional iteration started).
"""


def compile_node(node):
    kind = node[0]
    if kind == "char":
        return _compile_char(node[1])
    if kind == "bol":
        return _bol
    if kind == "eol":
        return _eol
    if kind == "seq":
        return _compile_seq([compile_node(n) for n in node[1]])
    if kind == "alt":
        return _compile_alt([compile_node(n) for n in node[1]])
    if kind == "group":
        return _compile_group(node[1], compile_node(node[2]))
    if kind == "repeat":
        _, body, lo, hi, greedy = node
        pred = _single_char_pred(body)
        if pred is not None:
            if greedy:
                return _compile_greedy_single(pred, lo, hi)
            return _compile_lazy_single(pred, lo, hi)
        if greedy:
            return _compile_greedy(compile_node(body), lo, hi)
        return _compile_lazy(compile_node(body), lo, hi)
    raise AssertionError(f"unknown node {kind!r}")


def _single_char_pred(node):
    """Return the predicate if ``node`` always matches exactly one char."""
    while node[0] == "seq" and len(node[1]) == 1:
        node = node[1][0]
    if node[0] == "char":
        return node[1]
    return None


def _compile_char(pred):
    def m(s, i, caps, k):
        if i < len(s) and pred(s[i]):
            return k(i + 1, caps)
        return None

    return m


def _bol(s, i, caps, k):
    if i == 0:
        return k(i, caps)
    return None


def _eol(s, i, caps, k):
    n = len(s)
    if i == n or (i == n - 1 and s[i] == "\n"):
        return k(i, caps)
    return None


def _empty(s, i, caps, k):
    return k(i, caps)


def _compile_seq(matchers):
    if not matchers:
        return _empty
    if len(matchers) == 1:
        return matchers[0]
    first = matchers[0]
    rest = _compile_seq(matchers[1:])

    def m(s, i, caps, k):
        return first(s, i, caps, lambda j, c: rest(s, j, c, k))

    return m


def _compile_alt(matchers):
    def m(s, i, caps, k):
        for sub in matchers:
            r = sub(s, i, caps, k)
            if r is not None:
                return r
        return None

    return m


def _compile_group(index, body):
    a = 2 * (index - 1)
    b = a + 2

    def m(s, i, caps, k):
        def close(j, c):
            return k(j, c[:a] + (i, j) + c[b:])

        return body(s, i, caps, close)

    return m


def _compile_greedy_single(pred, lo, hi):
    def m(s, i, caps, k):
        n = len(s)
        limit = n if hi is None else min(n, i + hi)
        j = i
        while j < limit and pred(s[j]):
            j += 1
        stop = i + lo
        while j >= stop:
            r = k(j, caps)
            if r is not None:
                return r
            j -= 1
        return None

    return m


def _compile_lazy_single(pred, lo, hi):
    def m(s, i, caps, k):
        n = len(s)
        j = i
        stop = i + lo
        while j < stop:
            if j >= n or not pred(s[j]):
                return None
            j += 1
        limit = n if hi is None else min(n, i + hi)
        while True:
            r = k(j, caps)
            if r is not None:
                return r
            if j >= limit or not pred(s[j]):
                return None
            j += 1

    return m


def _compile_greedy(body, lo, hi):
    """Greedy repeat of a general sub-pattern (sre MAX_UNTIL semantics)."""

    def m(s, i, caps, k):
        def step(count, j, c, last_ptr):
            # ``count`` iterations have completed; we are at position ``j``.
            if count < lo:
                return body(s, j, c, lambda j2, c2: step(count + 1, j2, c2, last_ptr))
            if (hi is None or count < hi) and j != last_ptr:
                r = body(s, j, c, lambda j2, c2: step(count + 1, j2, c2, j))
                if r is not None:
                    return r
            return k(j, c)

        return step(0, i, caps, None)

    return m


def _compile_lazy(body, lo, hi):
    """Lazy repeat of a general sub-pattern (sre MIN_UNTIL semantics)."""

    def m(s, i, caps, k):
        def step(count, j, c, last_ptr):
            if count < lo:
                return body(s, j, c, lambda j2, c2: step(count + 1, j2, c2, last_ptr))
            r = k(j, c)
            if r is not None:
                return r
            if (hi is not None and count >= hi) or j == last_ptr:
                return None
            return body(s, j, c, lambda j2, c2: step(count + 1, j2, c2, j))

        return step(0, i, caps, None)

    return m

"""AST / matcher nodes.

Each node implements ``match(s, pos, groups, cont)`` in continuation-passing
style: try to consume input starting at ``pos``, and on success call
``cont(new_pos)``. If ``cont`` returns ``False`` the node must backtrack
(undo any group assignments) and try the next alternative, mirroring the
backtracking semantics of Python's ``re`` module.
"""

from __future__ import annotations


class Node:
    def match(self, s, pos, groups, cont):
        raise NotImplementedError


class Empty(Node):
    def match(self, s, pos, groups, cont):
        return cont(pos)


class NonCapturingGroup(Node):
    """Wraps an inner node without capturing.

    Exists as a distinct type (rather than returning the inner node
    directly) so that quantifier parsing can tell "an atom that happens to
    contain a repeat" apart from "a repeat directly followed by another
    quantifier" -- only the latter is a parse error.
    """

    __slots__ = ("node",)

    def __init__(self, node):
        self.node = node

    def match(self, s, pos, groups, cont):
        return self.node.match(s, pos, groups, cont)


class Literal(Node):
    __slots__ = ("ch",)

    def __init__(self, ch):
        self.ch = ch

    def match(self, s, pos, groups, cont):
        if pos < len(s) and s[pos] == self.ch:
            return cont(pos + 1)
        return False


class AnyChar(Node):
    """``.`` - matches anything except a newline."""

    def match(self, s, pos, groups, cont):
        if pos < len(s) and s[pos] != "\n":
            return cont(pos + 1)
        return False


class CharPredicate(Node):
    """Matches a single character satisfying ``pred``."""

    __slots__ = ("pred",)

    def __init__(self, pred):
        self.pred = pred

    def match(self, s, pos, groups, cont):
        if pos < len(s) and self.pred(s[pos]):
            return cont(pos + 1)
        return False


class StartAnchor(Node):
    def match(self, s, pos, groups, cont):
        if pos == 0:
            return cont(pos)
        return False


class EndAnchor(Node):
    def match(self, s, pos, groups, cont):
        n = len(s)
        if pos == n or (pos == n - 1 and s[pos] == "\n"):
            return cont(pos)
        return False


class Concat(Node):
    __slots__ = ("nodes",)

    def __init__(self, nodes):
        self.nodes = nodes

    def match(self, s, pos, groups, cont):
        nodes = self.nodes
        n = len(nodes)

        def build(i, pos):
            if i == n:
                return cont(pos)
            return nodes[i].match(s, pos, groups, lambda newpos, i=i: build(i + 1, newpos))

        return build(0, pos)


class Alt(Node):
    __slots__ = ("branches",)

    def __init__(self, branches):
        self.branches = branches

    def match(self, s, pos, groups, cont):
        for branch in self.branches:
            if branch.match(s, pos, groups, cont):
                return True
        return False


class Group(Node):
    """A capturing group. ``index`` is the 1-based group number."""

    __slots__ = ("index", "node")

    def __init__(self, index, node):
        self.index = index
        self.node = node

    def match(self, s, pos, groups, cont):
        old = groups[self.index - 1]

        def inner_cont(newpos):
            groups[self.index - 1] = (pos, newpos)
            if cont(newpos):
                return True
            groups[self.index - 1] = old
            return False

        if self.node.match(s, pos, groups, inner_cont):
            return True
        groups[self.index - 1] = old
        return False


class Repeat(Node):
    """Repeats ``node`` between ``min_count`` and ``max_count`` times.

    ``max_count`` of ``None`` means unbounded.
    """

    __slots__ = ("node", "min_count", "max_count", "lazy")

    def __init__(self, node, min_count, max_count, lazy):
        self.node = node
        self.min_count = min_count
        self.max_count = max_count
        self.lazy = lazy

    def match(self, s, pos, groups, cont):
        node = self.node
        min_count = self.min_count
        max_count = self.max_count
        lazy = self.lazy

        def helper(pos, count):
            can_stop = count >= min_count
            can_more = max_count is None or count < max_count

            def try_stop():
                if can_stop:
                    return cont(pos)
                return False

            def try_more():
                if not can_more:
                    return False

                def one_cont(newpos):
                    if newpos == pos and max_count is None:
                        # Zero-width iteration with an unbounded quantifier:
                        # taking another would loop forever without
                        # progress, so only stopping here is allowed. This
                        # doesn't apply to bounded quantifiers ({n,m}), where
                        # the iteration count itself guarantees termination
                        # and further empty iterations may still be needed
                        # to satisfy min_count.
                        return count + 1 >= min_count and cont(newpos)
                    return helper(newpos, count + 1)

                return node.match(s, pos, groups, one_cont)

            if lazy:
                return try_stop() or try_more()
            return try_more() or try_stop()

        return helper(pos, 0)

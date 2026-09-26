from miniregex import RegexError, compile


def test_imports() -> None:
    assert callable(compile)
    assert issubclass(RegexError, Exception)

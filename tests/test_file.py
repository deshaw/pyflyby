# pyflyby/test_file.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from __future__ import print_function

from   hypothesis               import given, strategies as st
import pytest
import string

from   pyflyby._file            import FilePos, FileText, Filename
from   pyflyby._util            import CwdCtx


@st.composite
def maybe_comments(draw):
    """A strategy which generates lists of printable text which maybe contains '#'."""
    texts = draw(
        st.lists(
            st.tuples(
                st.text(alphabet=string.printable),
                st.text(alphabet=string.printable) | st.none(),
            )
        )
    )

    result = []
    for code, more_code in texts:
        if more_code is None:
            result.append(code)
        else:
            result.append(f"{code} # {more_code}")

    return result


def test_Filename_1():
    f = Filename('/etc/passwd')
    assert str(f) == '/etc/passwd'


def test_Filename_eqne_1():
    assert      Filename('/foo/bar') == Filename('/foo/bar')
    assert not (Filename('/foo/bar') != Filename('/foo/bar'))
    assert      Filename('/foo/bar') != Filename('/foo/BAR')
    assert not (Filename('/foo/bar') == Filename('/foo/BAR'))


def test_Filename_eqne_other_1():
    assert      Filename("/foo") != "/foo"
    assert not (Filename("/foo") == "/foo")
    assert      Filename("/foo") != object()
    assert not (Filename("/foo") == object())


def test_Filename_abspath_1():
    with CwdCtx("/dev"):
        f = Filename("foo")
    assert f == Filename("/dev/foo")


def test_Filename_normpath_1():
    with CwdCtx("/dev"):
        f = Filename("../a/b/../c")
    assert f == Filename("/a/c")


def test_Filename_dir_1():
    f = Filename('/Foo.foo.f/Bar.bar.b/Quux.quux.q')
    assert f.dir == Filename('/Foo.foo.f/Bar.bar.b')


def test_Filename_base_1():
    f = Filename('/Foo.foo.f/Bar.bar.b/Quux.quux.q')
    assert f.base == 'Quux.quux.q'


def test_Filename_ext_1():
    f = Filename('/Foo.foo.f/Bar.bar.b/Quux.quux.q')
    assert f.ext == '.q'


def test_Filename_isfile_1():
    f = Filename('/etc/passwd')
    assert f.isfile
    assert not f.dir.isfile


def test_Filename_isdir_1():
    f = Filename('/etc/passwd')
    assert not f.isdir
    assert f.dir.isdir


def test_Filename_ancestors_1():
    fn = Filename("/a.aa/b.bb/c.cc")
    result = fn.ancestors
    expected = (Filename("/a.aa/b.bb/c.cc"),
                Filename("/a.aa/b.bb"),
                Filename("/a.aa"),
                Filename("/"))
    assert result == expected


def test_FilePos_from_intint_1():
    pos = FilePos(55,66)
    assert pos.lineno == 55
    assert pos.colno  == 66


def test_FilePos_from_FilePos_1():
    pos = FilePos(55,66)
    assert FilePos(pos) is pos


def test_FilePos_from_tuple_intint_1():
    pos = FilePos((66,77))
    assert pos.lineno == 66
    assert pos.colno  == 77


def test_FilePos_from_None_1():
    pos = FilePos(None)
    assert pos.lineno == 1
    assert pos.colno  == 1


def test_FilePos_from_empty_1():
    pos = FilePos()
    assert pos.lineno == 1
    assert pos.colno  == 1


def test_FilePos_eqne_lineno_1():
    p1a = FilePos(55,66)
    p1b = FilePos(55,66)
    p2  = FilePos(55,1)
    assert     (p1a == p1b)
    assert not (p1a != p1b)
    assert     (p1a != p2 )
    assert not (p1a == p2 )


def test_FilePos_eqne_colno_1():
    p1a = FilePos(55,66)
    p1b = FilePos(55,66)
    p2  = FilePos(1,66)
    assert     (p1a == p1b)
    assert not (p1a != p1b)
    assert     (p1a != p2 )
    assert not (p1a == p2 )


def test_FilePos_bad_other_1():
    with pytest.raises(TypeError):
        FilePos(object())


def test_FilePos_bad_too_few_args_1():
    with pytest.raises(TypeError):
        FilePos(5)
    with pytest.raises(TypeError):
        FilePos((5,))


def test_FilePos_bad_too_many_args_1():
    with pytest.raises(TypeError):
        FilePos(5,6,7)
    with pytest.raises(TypeError):
        FilePos((5,6,7))


def test_FilePos_bad_type_1():
    with pytest.raises(TypeError):
        FilePos("5","6")
    with pytest.raises(TypeError):
        FilePos(5.0, 6.0)


def test_FileText_from_str_1():
    text = FileText("a\nb\nc\nd")
    assert text.joined == "a\nb\nc\nd"
    assert text.lines == ("a", "b", "c", "d")


def test_FileText_from_str_trailing_newline_1():
    text = FileText("a\nb\nc\nd\n")
    assert text.joined == "a\nb\nc\nd\n"
    assert text.lines == ("a", "b", "c", "d", "")


def test_FileText_from_str_one_1():
    text = FileText("a")
    assert text.joined == "a"
    assert text.lines == ("a",)


def test_FileText_from_str_one_trailing_newline_1():
    text = FileText("a\n")
    assert text.joined == "a\n"
    assert text.lines == ("a", "")


def test_FileText_idempotent_1():
    text = FileText("a\nb\nc\nd")
    assert FileText(text) is text


def test_FileText_attr_defaults_1():
    text = FileText("aabb\n")
    assert text.joined   == "aabb\n"
    assert text.filename == None
    assert text.startpos.lineno   == 1
    assert text.startpos.colno    == 1


def test_FileText_attrs_1():
    text = FileText("aabb\n", filename="/foo", startpos=(100,5))
    assert text.joined          == "aabb\n"
    assert text.filename        == Filename("/foo")
    assert text.startpos.lineno == 100
    assert text.startpos.colno  == 5


def test_FileText_attrs_from_instance_1():
    text = FileText(FileText("aabb\n"), filename="/foo", startpos=(100,5))
    assert text.joined          == "aabb\n"
    assert text.filename        == Filename("/foo")
    assert text.startpos.lineno == 100
    assert text.startpos.colno  == 5


def test_FileText_endpos_1():
    text = FileText("foo\nbar\n")
    assert text.endpos == FilePos(3,1)


def test_FileText_endpos_trailing_partial_line_1():
    text = FileText("foo\nbar")
    assert text.endpos == FilePos(2,4)


def test_FileText_endpos_offset_1():
    text = FileText("foo\nbar\n", startpos=(101,55))
    assert text.endpos == FilePos(103,1)


def test_FileText_empty_1():
    text = FileText("", startpos=(5,5))
    assert text.lines == ("",)
    assert text.joined == ""
    assert text.startpos == text.endpos == FilePos(5,5)


def test_FileText_one_full_line_offset_1():
    text = FileText("foo\n", startpos=(101,55))
    assert text.endpos == FilePos(102,1)


def test_FileText_one_partial_line_offset_1():
    text = FileText("foo", startpos=(101,55))
    assert text.endpos == FilePos(101,58)


def test_FileText_getitem_1():
    assert FileText("a\nb\nc\nd")[2] == 'b'


def test_FileText_slice_1():
    assert FileText("a\nb\nc\nd")[2:4] == FileText('b\nc\n', startpos=(2,1))


def test_FileText_slice_offset_1():
    text = FileText("a\nb\nc\nd", startpos=(101,5))
    assert text[102:104] == FileText('b\nc\n', startpos=(102,1))


def test_FileText_slice_col_1():
    text = FileText("one\ntwo4567\nthree6789\nfour\n", startpos=(101,55))
    result = text[ (102,3) : (103,8) ]
    expected = FileText("o4567\nthree67", startpos=(102,3))
    assert result == expected


def test_FileText_slice_starting_col_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,103) : (103,8) ]
    expected = FileText("o4567\nthree67", startpos=(102,103))
    assert result == expected


def test_FileText_slice_col_eol_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,103) : (104,1) ]
    expected = FileText("o4567\nthree6789\n", startpos=(102,103))
    assert result == expected


def test_FileText_slice_col_eof_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,103) : (105,1) ]
    expected = FileText("o4567\nthree6789\nfour\n", startpos=(102,103))
    assert result == expected


def test_FileText_slice_idempotent_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,101) : (105,1) ]
    assert result is text


def test_FileText_slice_idempotent_2():
    text = FileText("two4567\nthree6789\nfour", startpos=(102,101))
    result = text[ (102,101) : (104,5) ]
    assert result is text


def test_FileText_slice_col_almost_eof_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,103) : (104,5) ]
    expected = FileText("o4567\nthree6789\nfour", startpos=(102,103))
    assert result == expected


def test_FileText_slice_col_out_of_range_start_lineno_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (101,1) : (103,1) ]


def test_FileText_slice_col_out_of_range_end_lineno_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (102,103) : (106,1) ]


def test_FileText_slice_col_out_of_range_start_colno_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (102,1) : (103,1) ]


def test_FileText_slice_col_out_of_range_end_colno_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (102,103) : (105,2) ]


def test_FileText_slice_col_out_of_range_end_colno_2():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (102,103) : (104,6) ]


def test_FileText_slice_empty_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    result = text[ (102,103) : (102,103) ]
    expected = FileText("", startpos=(102,103))
    assert result == expected


def test_FileText_slice_out_of_range_empty_1():
    text = FileText("two4567\nthree6789\nfour\n", startpos=(102,101))
    with pytest.raises(IndexError):
        text[ (102,200) : (102,200) ]


def test_FileText_getitem_out_of_range_1():
    text = FileText("a\nb\nc\nd")
    with pytest.raises(IndexError):
        text[0]


def test_FileText_eqne_1():
    text1a = FileText("hello\n")
    text1b = FileText("hello\n")
    text2  = FileText("hello\nhello\n")
    assert     (text1a == text1b)
    assert not (text1a != text1b)
    assert     (text1a != text2 )
    assert not (text1a == text2 )


def test_FileText_eqne_lineno_1():
    text1a = FileText("hello\n", startpos=(100,1))
    text1b = FileText("hello\n", startpos=(100,1))
    text2  = FileText("hello\n", startpos=(101,1))
    assert     (text1a == text1b)
    assert not (text1a != text1b)
    assert     (text1a != text2 )
    assert not (text1a == text2 )


def test_FileText_eqne_filename_1():
    text1a = FileText("hello\n", filename='/foo')
    text1b = FileText("hello\n", filename='/foo')
    text2  = FileText("hello\n", filename='/bar')
    assert     (text1a == text1b)
    assert not (text1a != text1b)
    assert     (text1a != text2 )
    assert not (text1a == text2 )


def test_FileText_ne_other_1():
    text = FileText("hello\n")
    assert     (text != object())
    assert not (text == object())
    assert     (text != "hello\n")
    assert not (text == "hello\n")



@given(maybe_comments())
def test_get_comments(texts):
    joined = "\n".join(texts)
    lines = joined.split("\n")  # Texts might contain more '#' characters
    comments = FileText(joined).get_comments()

    assert len(lines) == len(comments)
    for line, comment in zip(lines, comments):
        split = line.split("#", maxsplit=1)

        if len(split) > 1:
            raw_comment = split[1]
            assert raw_comment == comment
        else:
            assert comment is None

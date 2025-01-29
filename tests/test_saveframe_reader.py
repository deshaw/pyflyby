from __future__ import annotations

from   contextlib               import contextmanager
import os
import pickle
import pytest
import random
from   shutil                   import rmtree
import subprocess
import sys
from   tempfile                 import mkdtemp
from   textwrap                 import dedent

from   pyflyby                  import Filename, SaveframeReader, saveframe

VERSION_INFO = sys.version_info

@pytest.fixture
def tmpdir(request):
    """
    A temporary directory which is temporarily added to sys.path.
    """
    d = mkdtemp(prefix="pyflyby_test_saveframe_", suffix=".tmp")
    d = Filename(d).real
    def cleanup():
        # Unload temp modules.
        for name, module in sorted(sys.modules.items()):
            if (getattr(module, "__file__", None) or "").startswith(str(d)):
                del sys.modules[name]
        # Clean up sys.path.
        sys.path.remove(str(d))
        # Clean up directory on disk.
        rmtree(str(d))
    request.addfinalizer(cleanup)
    sys.path.append(str(d))
    return d


def load_pkl(filename):
    with open(filename, mode='rb') as f:
        data = pickle.load(f)
    return data


def writetext(filename, text, mode='w'):
    text = dedent(text)
    assert isinstance(filename, Filename)
    with open(str(filename), mode) as f:
        f.write(text)
    return filename


@contextmanager
def chdir(path):
    old_cwd = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old_cwd)


def get_random():
    return int(random.random() * 10 ** 9)


def run_command(command):
    result = subprocess.run(command, capture_output=True)
    return result.stderr.decode('utf-8').strip().split('\n')


@contextmanager
def run_code_and_set_exception(code, exception):
    try:
        exec(code)
    except exception as err:
        if VERSION_INFO < (3, 12):
            sys.last_value = err
        else:
            sys.last_exc = err
    try:
        yield
    finally:
        delattr(sys, "last_value" if VERSION_INFO < (3, 12) else "last_exc")


def create_pkg(tmpdir):
    """
    Create a pacakge with multiple nested sub-packages and modules in ``tmpdir``.
    """
    pkg_name = f"saveframe_{int(random.random() * 10**9)}"
    os.mkdir(str(tmpdir / pkg_name))
    writetext(tmpdir / pkg_name / "__init__.py", f"""
        from {pkg_name}.mod1 import func1
        def init_func1():
            var1 = 3
            var2 = 'blah'
            func1()
    """)
    writetext(tmpdir / pkg_name / "mod1.py", f"""
        import os
        import signal
        from {pkg_name}.pkg1.mod2 import mod2_cls
        def func2():
            var1 = "func2"
            var2 = 34
            obj = mod2_cls()
            obj.func2()

        def func1():
            var1 = [4, 5, 2]
            func1_var2 = 4.56
            func2()
    """)
    os.mkdir(str(tmpdir / pkg_name / "pkg1"))
    writetext(tmpdir / pkg_name / "pkg1" / "__init__.py", "")
    writetext(tmpdir / pkg_name / "pkg1" / "mod2.py", f"""
        from {pkg_name}.pkg1.pkg2.mod3 import func3
        class mod2_cls:
            def __init__(self):
                pass
            def func2(self):
                 var1 = 'foo'
                 var2 = (4, 9, 10)
                 var3 = lambda x: x+1
                 func3()
    """)
    os.mkdir(str(tmpdir/ pkg_name / "pkg1" / "pkg2"))
    writetext(tmpdir / pkg_name / "pkg1" / "pkg2" / "__init__.py", "")
    writetext(tmpdir / pkg_name / "pkg1" / "pkg2" / "mod3.py", """
        def func3():
            var1 = [4, 'foo', 2.4]
            var2 = 'blah'
            func3_var3 = True
            raise ValueError("Error is raised")
    """)
    return pkg_name


def call_saveframe(pkg_name, tmpdir, frames):
    code = f"from {pkg_name} import init_func1; init_func1()"
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    with run_code_and_set_exception(code, ValueError):
        saveframe(filename=filename, frames=frames)
    return filename


def get_func2_qualname():
    return "func2" if VERSION_INFO < (3, 11) else "mod2_cls.func2"


def test_saveframe_reader_repr_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=1)
    reader = SaveframeReader(filename)

    expected = (
        f'SaveframeReader(\nfilename: \'{filename}\' \n\nFrames:\nFrame 1:\n  '
        f'Filename: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py\'\n  Line Number: '
        f'6\n  Function: func3\n  Module: {pkg_name}.pkg1.pkg2.mod3\n  Frame ID: '
        f'\'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py,6,func3\'\n  Code: raise '
        'ValueError("Error is raised")\n  Variables: [\'var1\', \'var2\', \''
        'func3_var3\']\n\nException:\n  Full String: ValueError: Error is '
        'raised\n  String: Error is raised\n  Class Name: ValueError\n  '
        'Qualified Name: ValueError\n)')
    assert repr(reader) == expected


def test_saveframe_reader_repr_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=2)
    reader = SaveframeReader(filename)

    expected = (
        f'SaveframeReader(\nfilename: \'{filename}\' \n\nFrames:\nFrame 1:\n  '
        f'Filename: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py\'\n  Line Number: '
        f'6\n  Function: func3\n  Module: {pkg_name}.pkg1.pkg2.mod3\n  Frame ID: '
        f'\'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py,6,func3\'\n  Code: raise '
        'ValueError("Error is raised")\n  Variables: [\'var1\', \'var2\', \''
        f'func3_var3\']\n\nFrame 2:\n  Filename: \'{tmpdir}/{pkg_name}/pkg1/'
        f'mod2.py\'\n  Line Number: 10\n  Function: {get_func2_qualname()}\n  Module: '
        f'{pkg_name}.pkg1.mod2\n  Frame ID: \'{tmpdir}/{pkg_name}/pkg1/mod2.py,'
        '10,func2\'\n  Code: func3()\n  Variables: [\'self\', \'var1\', \'var2'
        '\']\n\nException:\n  Full String: ValueError: Error is '
        'raised\n  String: Error is raised\n  Class Name: ValueError\n  '
        'Qualified Name: ValueError\n)')
    assert repr(reader) == expected


def test_saveframe_reader_repr_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=["mod1.py::"])
    reader = SaveframeReader(filename)

    expected = (
        f'SaveframeReader(\nfilename: \'{filename}\' \n\nFrames:\nFrame 3:\n  '
        f'Filename: \'{tmpdir}/{pkg_name}/mod1.py\'\n  Line Number: 9\n  '
        f'Function: func2\n  Module: {pkg_name}.mod1\n  Frame ID: \'{tmpdir}/'
        f'{pkg_name}/mod1.py,9,func2\'\n  Code: obj.func2()\n  Variables: '
        f'[\'var1\', \'var2\', \'obj\']\n\nFrame 4:\n  Filename: \'{tmpdir}/'
        f'{pkg_name}/mod1.py\'\n  Line Number: 14\n  Function: func1\n  Module: '
        f'{pkg_name}.mod1\n  Frame ID: \'{tmpdir}/{pkg_name}/mod1.py,14,func1\''
        '\n  Code: func2()\n  Variables: [\'var1\', \'func1_var2\']\n\n'
        'Exception:\n  Full String: ValueError: Error is raised\n  String: '
        'Error is raised\n  Class Name: ValueError\n  Qualified Name: ValueError\n)')
    assert repr(reader) == expected


def test_saveframe_reader_str_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=1)
    reader = SaveframeReader(filename)

    expected = (
        f'Frames:\nFrame 1:\n  Filename: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py'
        f'\'\n  Line Number: 6\n  Function: func3\n  Module: {pkg_name}.pkg1.'
        f'pkg2.mod3\n  Frame ID: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py,6,'
        'func3\'\n  Code: raise ValueError("Error is raised")\n  Variables: '
        '[\'var1\', \'var2\', \'func3_var3\']\n\nException:\n  Full String: '
        'ValueError: Error is raised\n  String: Error is raised\n  Class Name: '
        'ValueError\n  Qualified Name: ValueError\n')
    assert str(reader) == expected


def test_saveframe_reader_str_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=2)
    reader = SaveframeReader(filename)

    expected = (
        f'Frames:\nFrame 1:\n  Filename: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py'
        f'\'\n  Line Number: 6\n  Function: func3\n  Module: {pkg_name}.pkg1.'
        f'pkg2.mod3\n  Frame ID: \'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py,6,func3'
        '\'\n  Code: raise ValueError("Error is raised")\n  Variables: [\'var1'
        f'\', \'var2\', \'func3_var3\']\n\nFrame 2:\n  Filename: \'{tmpdir}/'
        f'{pkg_name}/pkg1/mod2.py\'\n  Line Number: 10\n  Function: '
        f'{get_func2_qualname()}\n  Module: {pkg_name}.pkg1.mod2\n  Frame ID: '
        f'\'{tmpdir}/{pkg_name}/pkg1/mod2.py,10,func2\'\n  Code: func3()\n  '
        f'Variables: [\'self\', \'var1\', \'var2\']\n\nException:\n  Full '
        f'String: ValueError: Error is raised\n  String: Error is raised\n  '
        f'Class Name: ValueError\n  Qualified Name: ValueError\n')
    assert str(reader) == expected


def test_saveframe_reader_str_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=["mod1.py::"])
    reader = SaveframeReader(filename)

    expected = (
        f'Frames:\nFrame 3:\n  Filename: \'{tmpdir}/{pkg_name}/mod1.py\'\n  Line '
        f'Number: 9\n  Function: func2\n  Module: {pkg_name}.mod1\n  Frame ID: '
        f'\'{tmpdir}/{pkg_name}/mod1.py,9,func2\'\n  Code: obj.func2()\n  Variables: '
        f'[\'var1\', \'var2\', \'obj\']\n\nFrame 4:\n  Filename: \'{tmpdir}/'
        f'{pkg_name}/mod1.py\'\n  Line Number: 14\n  Function: func1\n  Module: '
        f'{pkg_name}.mod1\n  Frame ID: \'{tmpdir}/{pkg_name}/mod1.py,14,func1\''
        '\n  Code: func2()\n  Variables: [\'var1\', \'func1_var2\']\n\n'
        'Exception:\n  Full String: ValueError: Error is raised\n  String: '
        'Error is raised\n  Class Name: ValueError\n  Qualified Name: ValueError\n')
    assert str(reader) == expected


def test_filename(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=1)
    reader = SaveframeReader(filename)

    assert reader.filename == filename


def test_metadata(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=1)
    reader = SaveframeReader(filename)

    expected = [
        'frame_index', 'filename', 'lineno', 'function_name', 'function_qualname',
        'function_object', 'module_name', 'code', 'frame_identifier',
        'exception_string', 'exception_full_string', 'exception_class_name',
        'exception_class_qualname', 'exception_object', 'traceback']
    assert reader.metadata == expected


def test_variables_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=2)
    reader = SaveframeReader(filename)

    expected = {1: ['var1', 'var2', 'func3_var3'], 2: ['self', 'var1', 'var2']}
    assert reader.variables == expected


def test_variables_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    expected =  {
        1: ['var1', 'var2', 'func3_var3'], 2: ['self', 'var1', 'var2'],
        3: ['var1', 'var2', 'obj'], 4: ['var1', 'func1_var2'], 5: ['var1', 'var2']}
    assert reader.variables == expected


def test_variables_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    expected = {3: ['var1', 'var2', 'obj'], 4: ['var1', 'func1_var2']}
    assert reader.variables == expected


def test_get_metadata_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=3)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("filename")
    expected = {
        1: f'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py',
        2: f'{tmpdir}/{pkg_name}/pkg1/mod2.py',
        3: f'{tmpdir}/{pkg_name}/mod1.py'}
    assert result == expected

    result = reader.get_metadata("filename", frame_idx=2)
    expected = f'{tmpdir}/{pkg_name}/pkg1/mod2.py'
    assert result == expected


def test_get_metadata_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    result = reader.get_metadata("lineno")
    expected = {3: 9, 4: 14}
    assert result == expected

    result = reader.get_metadata("lineno", frame_idx=4)
    expected = 14
    assert result == expected


def test_get_metadata_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("function_name")
    expected = {1: 'func3', 2: 'func2', 3: 'func2', 4: 'func1', 5: 'init_func1'}
    assert result == expected

    result = reader.get_metadata("function_name", frame_idx=5)
    expected = 'init_func1'
    assert result == expected


def test_get_metadata_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::..')
    reader = SaveframeReader(filename)

    result = reader.get_metadata("function_qualname")
    expected = {1: 'func3', 2: get_func2_qualname(), 3: 'func2', 4: 'func1'}
    assert result == expected

    result = reader.get_metadata("function_qualname", frame_idx=2)
    expected = get_func2_qualname()
    assert result == expected


def test_get_metadata_5(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    frame_idx_to_info = {
        1: {'name': 'func3', 'qualname': 'func3'},
        2: {'name': 'func2', 'qualname': get_func2_qualname()},
        3: {'name': 'func2', 'qualname': 'func2'},
        4: {'name': 'func1', 'qualname': 'func1'},
        5: {'name': 'init_func1', 'qualname': 'init_func1'}
    }

    result = reader.get_metadata("function_object")
    assert list(result.keys()) == [1, 2, 3, 4, 5]
    for key in result:
        func = result[key]
        if isinstance(func, str):
            continue
        name = func.__name__
        qualname = func.__qualname__
        assert name == frame_idx_to_info[key]['name']
        assert qualname == frame_idx_to_info[key]['qualname']

    result = reader.get_metadata("function_object", frame_idx=2)
    if not isinstance(result, str):
        assert result.__qualname__ == get_func2_qualname()


def test_get_metadata_6(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("module_name")
    expected =  {1: f'{pkg_name}.pkg1.pkg2.mod3', 2: f'{pkg_name}.pkg1.mod2',
                 3: f'{pkg_name}.mod1', 4: f'{pkg_name}.mod1', 5: pkg_name}
    assert result == expected

    result = reader.get_metadata("module_name", frame_idx=4)
    assert result == f'{pkg_name}.mod1'


def test_get_metadata_7(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("code")
    expected = {1: 'raise ValueError("Error is raised")', 2: 'func3()',
                3: 'obj.func2()', 4: 'func2()', 5: 'func1()'}
    assert result == expected

    result = reader.get_metadata("code", frame_idx=1)
    assert result == 'raise ValueError("Error is raised")'

    result = reader.get_metadata("code", frame_idx=3)
    assert result == 'obj.func2()'


def test_get_metadata_8(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("frame_identifier")
    expected = {
        1: f'{tmpdir}/{pkg_name}/pkg1/pkg2/mod3.py,6,func3',
        2: f'{tmpdir}/{pkg_name}/pkg1/mod2.py,10,func2',
        3: f'{tmpdir}/{pkg_name}/mod1.py,9,func2',
        4: f'{tmpdir}/{pkg_name}/mod1.py,14,func1',
        5: f'{tmpdir}/{pkg_name}/__init__.py,6,init_func1'}
    assert result == expected

    result = reader.get_metadata("frame_identifier", frame_idx=4)
    assert result == f'{tmpdir}/{pkg_name}/mod1.py,14,func1'

    result = reader.get_metadata("frame_identifier", frame_idx=2)
    assert result == f'{tmpdir}/{pkg_name}/pkg1/mod2.py,10,func2'


def test_get_metadata_9(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("exception_string")
    exepected = 'Error is raised'
    assert result == exepected


def test_get_metadata_10(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("exception_full_string")
    expected = 'ValueError: Error is raised'
    assert result == expected


def test_get_metadata_11(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("exception_class_name")
    expected = 'ValueError'
    assert result == expected


def test_get_metadata_12(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("exception_class_qualname")
    expected = 'ValueError'
    assert result == expected


def test_get_metadata_13(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_metadata("exception_object")
    assert isinstance(result, ValueError)
    assert result.args == ('Error is raised',)


def test_get_metadata_invalid(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=2)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_metadata("foo")

    expected = (
        "Invalid metadata requested: 'foo'. Allowed metadata entries are: "
        "['frame_index', 'filename', 'lineno', 'function_name', 'function_qualname', "
        "'function_object', 'module_name', 'code', 'frame_identifier', "
        "'exception_string', 'exception_full_string', 'exception_class_name', "
        "'exception_class_qualname', 'exception_object', 'traceback'].")
    assert str(err.value) == expected


def test_get_metadata_invalid_frame_idx_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=3)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_metadata("filename", frame_idx=4)

    expected = "Invalid value for 'frame_idx': '4'.  Allowed values are: [1, 2, 3]."
    assert str(err.value) == expected


def test_get_metadata_invalid_frame_idx_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_metadata("filename", frame_idx=2)

    expected = "Invalid value for 'frame_idx': '2'.  Allowed values are: [3, 4]."
    assert str(err.value) == expected


def test_get_metadata_invalid_frame_idx_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    with pytest.raises(TypeError) as err:
        reader.get_metadata("filename", frame_idx='foo')

    expected = "'frame_idx' must be of type 'int', not 'str'."
    assert str(err.value) == expected


def test_get_metadata_invalid_frame_idx_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_metadata("traceback", frame_idx=3)

    expected = ("'frame_idx' is not supported for querying exception metadata: "
                "'traceback'.")
    assert str(err.value) == expected


def test_get_variables_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables('var2')
    expected = {1: 'blah', 2: (4, 9, 10), 3: 34, 5: 'blah'}
    assert result == expected

    # Single variable passed as a list.
    result = reader.get_variables(['var2'])
    expected = {1: {'var2': 'blah'}, 2: {'var2': (4, 9, 10)}, 3: {'var2': 34},
                5: {'var2': 'blah'}}
    assert result == expected

    # Single variable passed as a tuple.
    result = reader.get_variables(('var2',))
    expected = {1: {'var2': 'blah'}, 2: {'var2': (4, 9, 10)}, 3: {'var2': 34},
                5: {'var2': 'blah'}}
    assert result == expected


def test_get_variables_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    module = __import__(f"{pkg_name}.pkg1.mod2", fromlist=['dummy'], level=0)
    mod2_cls = getattr(module, "mod2_cls")
    result = reader.get_variables('obj')
    assert isinstance(result, mod2_cls)


def test_get_variables_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    result = reader.get_variables('var2')
    expected = 34
    assert result == expected


def test_get_variables_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables('var2', frame_idx=2)
    expected = (4, 9, 10)
    assert result == expected


def test_get_variables_5(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables('var1', frame_idx=5)
    expected = 3
    assert result == expected

    # Single variable passed as a list.
    result = reader.get_variables(['var1'], frame_idx=5)
    expected = {'var1': 3}
    assert result == expected

    # Single variable passed as a tuple.
    result = reader.get_variables(('var1',), frame_idx=5)
    expected = {'var1': 3}
    assert result == expected


def test_get_variables_6(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables(['var1', 'var2'])
    expected = {1: {'var1': [4, 'foo', 2.4], 'var2': 'blah'},
                2: {'var1': 'foo', 'var2': (4, 9, 10)},
                3: {'var1': 'func2', 'var2': 34}, 4: {'var1': [4, 5, 2]},
                5: {'var1': 3, 'var2': 'blah'}}
    assert result == expected


def test_get_variables_7(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables(['func1_var2', 'func3_var3', 'var3'])
    expected = {1: {'func3_var3': True}, 4: {'func1_var2': 4.56}}
    assert result == expected


def test_get_variables_8(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    result = reader.get_variables(['func1_var2', 'func3_var3', 'var3'])
    expected = {'func1_var2': 4.56}
    assert result == expected


def test_get_variables_9(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    result = reader.get_variables(['var1', 'var2', 'func1_var2'], frame_idx=3)
    expected = {'var1': 'func2', 'var2': 34}
    assert result == expected


def test_get_variables_invalid_variable_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables('foo')

    expected = "Local variable(s) ('foo',) not found in any of the saved frames."
    assert str(err.value) == expected


def test_get_variables_invalid_variable_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables('var2', frame_idx=4)

    expected = "Local variable(s) ('var2',) not found in frame 4"
    assert str(err.value) == expected


def test_get_variables_invalid_variable_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables(['var2', 'var5'], frame_idx=4)

    expected = "Local variable(s) ['var2', 'var5'] not found in frame 4"
    assert str(err.value) == expected


def test_get_variables_invalid_variable_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables([])

    expected = "No 'variables' passed."
    assert str(err.value) == expected


def test_get_variables_invalid_variable_5(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(TypeError) as err:
        reader.get_variables(['var1', 2])

    expected = ("Invalid type for variable name: int. Expected string type "
                "instead.")
    assert str(err.value) == expected


def test_get_variables_invalid_frame_idx_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(TypeError) as err:
        reader.get_variables('var1', frame_idx='foo')

    expected = "'frame_idx' must be of type 'int', not 'str'."
    assert str(err.value) == expected


def test_get_variables_invalid_frame_idx_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames=5)
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables('var1', frame_idx=6)

    expected = ("Invalid value for 'frame_idx': '6'. Allowed values are: "
                "[1, 2, 3, 4, 5].")
    assert str(err.value) == expected


def test_get_variables_invalid_frame_idx_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = call_saveframe(pkg_name, tmpdir, frames='mod1.py::')
    reader = SaveframeReader(filename)

    with pytest.raises(ValueError) as err:
        reader.get_variables(['var1', 'var2'], frame_idx=1)

    expected = "Invalid value for 'frame_idx': '1'. Allowed values are: [3, 4]."
    assert str(err.value) == expected

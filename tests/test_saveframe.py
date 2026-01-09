from __future__ import annotations

from   contextlib               import contextmanager
import os
import pexpect
import pickle
import pytest
import random
from   shutil                   import rmtree
import subprocess
import sys
from   tempfile                 import mkdtemp
from   textwrap                 import dedent

from   pyflyby                  import Filename, saveframe

VERSION_INFO = sys.version_info
PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")

exception_info_keys = {
    'exception_full_string', 'exception_object', 'exception_string',
    'exception_class_name', 'exception_class_qualname', 'traceback'}


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


def frames_metadata_checker(tmpdir, pkg_name, filename, num_frames=None):
    """
    Check if the metadata of the frames is correctly written in the ``filename``.
    """
    data = load_pkl(filename)
    if num_frames is None:
        expected_frame_keys = {1, 2, 3, 4, 5}
        assert set(data.keys()) == exception_info_keys | expected_frame_keys
    else:
        expected_frame_keys = set(range(1, num_frames + 1))
        assert set(data.keys()) == expected_frame_keys

    # Check frame 1 (func3)
    if 1 in expected_frame_keys:
        # Check if we're in debugger mode vs exception mode
        if 'exception_object' in data and data['exception_object'] is not None:
            # Exception mode - should have "raise ValueError" code
            assert data[1]["code"] == 'raise ValueError("Error is raised")'
            assert data[1]["lineno"] == 6
        else:
            # Debugger mode - should have "pdb.set_trace()" code
            assert data[1]["code"] == 'pdb.set_trace()'
            assert data[1]["lineno"] == 7

        assert data[1]["frame_index"] == 1
        assert data[1]["filename"] == str(
            tmpdir / pkg_name / "pkg1" / "pkg2" / "mod3.py")
        assert data[1]["function_name"] == "func3"
        assert data[1]["function_qualname"] == "func3"
        assert data[1]["module_name"] == f"{pkg_name}.pkg1.pkg2.mod3"
        assert data[1]["frame_identifier"] == (
            f"{data[1]['filename']},{data[1]['lineno']},{data[1]['function_name']}")

    # Check frame 2 (func2 in mod2.py)
    if 2 in expected_frame_keys:
        assert data[2]["code"] == 'func3()'
        assert data[2]["frame_index"] == 2
        assert data[2]["filename"] == str(tmpdir / pkg_name / "pkg1" / "mod2.py")
        assert data[2]["lineno"] == 10
        assert data[2]["function_name"] == "func2"
        assert (
            data[2]["function_qualname"] ==
            "func2" if VERSION_INFO < (3, 11) else "mod2_cls.func2")
        assert data[2]["module_name"] == f"{pkg_name}.pkg1.mod2"
        assert data[2]["frame_identifier"] == (
            f"{data[2]['filename']},{data[2]['lineno']},{data[2]['function_name']}")

    # Check frame 3 (func2 in mod1.py)
    if 3 in expected_frame_keys:
        assert data[3]["code"] == 'obj.func2()'
        assert data[3]["frame_index"] == 3
        assert data[3]["filename"] == str(tmpdir / pkg_name / "mod1.py")
        assert data[3]["lineno"] == 9
        assert data[3]["function_name"] == "func2"
        assert data[3]["function_qualname"] == "func2"
        assert data[3]["module_name"] == f"{pkg_name}.mod1"
        assert data[3]["frame_identifier"] == (
            f"{data[3]['filename']},{data[3]['lineno']},{data[3]['function_name']}")

    # Check frame 4 (func1 in mod1.py)
    if 4 in expected_frame_keys:
        assert data[4]["code"] == 'func2()'
        assert data[4]["frame_index"] == 4
        assert data[4]["filename"] == str(tmpdir / pkg_name / "mod1.py")
        assert data[4]["lineno"] == 14
        assert data[4]["function_name"] == "func1"
        assert data[4]["function_qualname"] == "func1"
        assert data[4]["module_name"] == f"{pkg_name}.mod1"
        assert data[4]["frame_identifier"] == (
            f"{data[4]['filename']},{data[4]['lineno']},{data[4]['function_name']}")

    # Check frame 5 (init_func1 in __init__.py)
    if 5 in expected_frame_keys:
        assert data[5]["code"] == 'func1()'
        assert data[5]["frame_index"] == 5
        assert data[5]["filename"] == str(tmpdir / pkg_name / "__init__.py")
        assert data[5]["lineno"] == 6
        assert data[5]["function_name"] == "init_func1"
        assert data[5]["function_qualname"] == "init_func1"
        assert data[5]["module_name"] == pkg_name
        assert data[5]["frame_identifier"] == (
            f"{data[5]['filename']},{data[5]['lineno']},{data[5]['function_name']}")


def frames_metadata_checker_for_keyboard_interrupt(tmpdir, pkg_name, filename):
    """
    Check if the metadata of the frames is correctly written in the ``filename``,
    when KeyboardInterrupt exception is raised.
    """
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2}

    assert data[1]["code"] == 'os.kill(os.getpid(), signal.SIGINT)'
    assert data[1]["frame_index"] == 1
    assert data[1]["filename"] == str(
        tmpdir / pkg_name / "mod1.py")
    assert data[1]["lineno"] == 19
    assert data[1]["function_name"] == "interrupt_func"
    assert data[1]["function_qualname"] == "interrupt_func"
    assert data[1]["module_name"] == f"{pkg_name}.mod1"
    assert data[1]["frame_identifier"] == (
        f"{data[1]['filename']},{data[1]['lineno']},{data[1]['function_name']}")

    assert data[2]["code"] == 'interrupt_func()'
    assert data[2]["frame_index"] == 2
    assert data[2]["filename"] == str(tmpdir / pkg_name / "__init__.py")
    assert data[2]["lineno"] == 22
    assert data[2]["function_name"] == "init_func4"
    assert data[2]["function_qualname"] == "init_func4"
    assert data[2]["module_name"] == f"{pkg_name}"
    assert data[2]["frame_identifier"] == (
        f"{data[2]['filename']},{data[2]['lineno']},{data[2]['function_name']}")


def frames_local_variables_checker(pkg_name, filename, num_frames=None):
    """
    Check if the local variables of the frames are correctly written in the
    ``filename``.
    """
    data = load_pkl(filename)
    if num_frames is None:
        expected_frame_keys = {1, 2, 3, 4, 5}
        assert set(data.keys()) == exception_info_keys | expected_frame_keys
    else:
        expected_frame_keys = set(range(1, num_frames + 1))
        assert set(data.keys()) == expected_frame_keys

    # Check frame 1 (func3) variables
    if 1 in expected_frame_keys:
        vars = set(data[1]['variables'].keys())
        vars.discard('saveframe')
        assert vars == {'func3_var3', 'var1', 'var2'}
        assert pickle.loads(data[1]['variables']['func3_var3']) == True
        assert pickle.loads(data[1]['variables']['var1']) == [4, 'foo', 2.4]
        assert pickle.loads(data[1]['variables']['var2']) == 'blah'

    # Check frame 2 (func2 in mod2.py) variables
    if 2 in expected_frame_keys:
        vars = set(data[2]['variables'].keys())
        vars.discard('saveframe')
        assert vars == {'self', 'var1', 'var2'}
        self_val = pickle.loads(data[2]['variables']['self'])
        mod2 = __import__(f"{pkg_name}.pkg1.mod2", fromlist=['dummy'], level=0)
        assert isinstance(self_val, mod2.mod2_cls)
        assert pickle.loads(data[2]['variables']['var1']) == 'foo'
        assert pickle.loads(data[2]['variables']['var2']) == (4, 9, 10)

    # Check frame 3 (func2 in mod1.py) variables
    if 3 in expected_frame_keys:
        vars = set(data[3]['variables'].keys())
        vars.discard('saveframe')
        assert vars == {'obj', 'var1', 'var2'}
        obj_val = pickle.loads(data[3]['variables']['obj'])
        if 2 not in expected_frame_keys:
            # Import mod2 if we haven't already
            mod2 = __import__(f"{pkg_name}.pkg1.mod2", fromlist=['dummy'], level=0)
        assert isinstance(obj_val, mod2.mod2_cls)
        assert pickle.loads(data[3]['variables']['var1']) == 'func2'
        assert pickle.loads(data[3]['variables']['var2']) == 34

    # Check frame 4 (func1 in mod1.py) variables
    if 4 in expected_frame_keys:
        vars = set(data[4]['variables'].keys())
        vars.discard('saveframe')
        assert vars == {'func1_var2', 'var1'}
        assert pickle.loads(data[4]['variables']['func1_var2']) == 4.56
        assert pickle.loads(data[4]['variables']['var1']) == [4, 5, 2]

    # Check frame 5 (init_func1 in __init__.py) variables
    if 5 in expected_frame_keys:
        vars = set(data[5]['variables'].keys())
        vars.discard('saveframe')
        assert vars == {'var1', 'var2'}
        assert pickle.loads(data[5]['variables']['var1']) == 3
        assert pickle.loads(data[5]['variables']['var2']) == 'blah'


def frames_local_variables_checker_for_keyboard_interrupt(filename):
    """
    Check if the local variables of the frames are correctly written in the
    ``filename``, when KeyboardInterrupt exception is raised.
    """
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2}

    assert set(data[1]['variables'].keys()) == {'interrupt_var1', 'interrupt_var2'}
    assert pickle.loads(data[1]['variables']['interrupt_var1']) == 'foo bar'

    assert set(data[2]['variables'].keys()) == {'var1', 'var2'}
    assert pickle.loads(data[2]['variables']['var1']) == 'init_func4'
    assert pickle.loads(data[2]['variables']['var2']) == [3, 4]


def exception_info_checker(filename):
    """
    Check if the exception info is correctly written in the ``filename``.
    """
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys
    assert data['exception_class_name'] == 'ValueError'
    assert data['exception_class_qualname'] == 'ValueError'
    assert data['exception_full_string'] == 'ValueError: Error is raised'
    assert isinstance(data['exception_object'], ValueError)
    # Traceback shouldn't be pickled for security reasons.
    assert data['exception_object'].__traceback__ == None
    assert data['exception_string'] == 'Error is raised'


def exception_info_checker_for_keyboard_interrupt(filename):
    """
    Check if the exception info is correctly written in the ``filename``,
    when KeyboardInterrupt exception is raised.
    """
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys
    assert data['exception_class_name'] == 'KeyboardInterrupt'
    assert data['exception_class_qualname'] == 'KeyboardInterrupt'
    assert data['exception_full_string'] == 'KeyboardInterrupt: '
    assert isinstance(data['exception_object'], KeyboardInterrupt)
    # Traceback shouldn't be pickled for security reasons.
    assert data['exception_object'].__traceback__ == None
    assert data['exception_string'] == ''


def create_pkg(tmpdir, start_debugger=False):
    """
    Create a pacakge with multiple nested sub-packages and modules in ``tmpdir``.
    """
    pkg_name = f"saveframe_{int(random.random() * 10**9)}"
    os.mkdir(str(tmpdir / pkg_name))
    writetext(tmpdir / pkg_name / "__init__.py", f"""
        from {pkg_name}.mod1 import func1, interrupt_func
        def init_func1():
            var1 = 3
            var2 = 'blah'
            func1()

        def init_func2():
            pass

        def init_func3():
            var1 = 'init_func3'
            var2 = 24
            try:
                func1()
            except ValueError as err:
                raise TypeError("Chained exception") from err

        def init_func4():
            var1 = 'init_func4'
            var2 = [3, 4]
            interrupt_func()
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

        def interrupt_func():
            interrupt_var1 = 'foo bar'
            interrupt_var2 = 3.4
            os.kill(os.getpid(), signal.SIGINT)
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
    if start_debugger:
        writetext(tmpdir / pkg_name / "pkg1" / "pkg2" / "mod3.py", """
            import pdb
            def func3():
                var1 = [4, 'foo', 2.4]
                var2 = 'blah'
                func3_var3 = True
                pdb.set_trace()
        """)
    else:
        writetext(tmpdir / pkg_name / "pkg1" / "pkg2" / "mod3.py", """
            def func3():
                var1 = [4, 'foo', 2.4]
                var2 = 'blah'
                func3_var3 = True
                raise ValueError("Error is raised")
        """)
    return pkg_name


def _run_saveframe_in_debugger(tmpdir, num_frames=None, jump=False):
    """
    Helper function to run saveframe in debugger using pexpect.
    """
    pkg_name = create_pkg(tmpdir, start_debugger=True)
    # Create a test script that imports and calls the package
    test_script = writetext(tmpdir / f"debug_test_{get_random()}.py", f"""
        import sys
        sys.path.append('{tmpdir}')
        from {pkg_name} import init_func1
        init_func1()
    """)
    output_filename = str(tmpdir / f"debugger_saveframe_{get_random()}.pkl")

    # Start the process with pexpect
    child = pexpect.spawn('python', [str(test_script)], timeout=30)
    try:
        child.expect('(Pdb)')
        # Jump up one frame if requested
        if jump:
            child.sendline('u')
            child.expect('(Pdb)')
        child.sendline('from pyflyby import saveframe')
        child.expect('(Pdb)')

        # Call saveframe in the debugger
        if num_frames is not None:
            child.sendline(f'saveframe(filename="{output_filename}", frames={num_frames})')
        else:
            child.sendline(f'saveframe(filename="{output_filename}")')
        child.expect('(Pdb)')
        child.sendline('c')
        child.expect(pexpect.EOF)
    finally:
        child.close()

    # Verify the output file was created by saveframe.
    assert os.path.exists(output_filename)

    return output_filename, pkg_name


def test_saveframe_invalid_filename_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / pkg_name))
    err_msg = (f"{str(tmpdir / pkg_name)!a} is an already existing directory. "
               f"Please pass a different filename.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_filename_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_dir_{get_random()}" / f"saveframe_{get_random()}.pkl")
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(FileNotFoundError) as err:
            saveframe(filename=filename)
    err_msg = (f"Error while saving the frames to the file: {filename!a}. Error: "
               f"FileNotFoundError(2, 'No such file or directory')")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames="foo.py:")
    err_msg = ("Error while validating frame: 'foo.py:'. The correct syntax for "
               "a frame is 'file_regex:line_no:function_name' but frame 'foo.py:' "
               "contains 1 ':'.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames=":12:func1")
    err_msg = ("Error while validating frame: ':12:func1'. The filename / file "
               "regex must be passed in a frame.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames="file.py:12:func1,file1.py::")
    err_msg = ("Error while validating frames: 'file.py:12:func1,file1.py::'. "
               "If you want to pass multiple frames, pass a list/tuple of frames "
               "like ['file.py:12:func1', 'file1.py::'] rather than a comma "
               "separated string of frames.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames=["file.py:12:func1", "file1.py::,file2.py:34:func2"])
    err_msg = (
        "Invalid frame: 'file1.py::,file2.py:34:func2' in frames: ['file.py:12:func1', "
        "'file1.py::,file2.py:34:func2'] as it contains character ','. If you are "
        "trying to pass multiple frames, pass them as separate items in the list.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_5(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames="file.py:12:func1..file2.py::..")
    err_msg = ("Error while validating frames: 'file.py:12:func1..file2.py::..'. "
               "If you want to pass a range of frames, the correct syntax is "
               "'first_frame..last_frame'")
    assert str(err.value) == err_msg


def test_saveframe_invalid_frames_6(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      frames="file.py:foo:func1")
    err_msg = ("Error while validating frame: 'file.py:foo:func1'. The line "
               "number 'foo' can't be converted to an integer.")
    assert str(err.value) == err_msg


def test_saveframe_variables_and_exclude_variables(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(variables="foo", exclude_variables="bar")
    err_msg = "Cannot pass both `variables` and `exclude_variables` parameters."
    assert str(err.value) == err_msg


def test_saveframe_invalid_variables_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      variables="var1,var2")
    err_msg = ("Error while validating variables: 'var1,var2'. If you want to pass "
               "multiple variable names, pass a list/tuple of names like ['var1', "
               "'var2'] rather than a comma separated string of names.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_variables_2(tmpdir, caplog):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                  variables=["var1", "1var2"])
    log_messages = [record.message for record in caplog.records]
    warning_msg = ("Invalid variable names: ['1var2']. Skipping these variables "
                   "and continuing.")
    assert warning_msg in log_messages


def test_saveframe_invalid_variables_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(TypeError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      variables=1)
    err_msg = ("Variables '1' must be of type list, tuple or string (for a single "
               "variable), not '<class 'int'>'")
    assert str(err.value) == err_msg


def test_saveframe_invalid_exclude_variables_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(ValueError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      exclude_variables="var1,var2")
    err_msg = ("Error while validating variables: 'var1,var2'. If you want to pass "
               "multiple variable names, pass a list/tuple of names like ['var1', "
               "'var2'] rather than a comma separated string of names.")
    assert str(err.value) == err_msg


def test_saveframe_invalid_exclude_variables_2(tmpdir, caplog):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                  exclude_variables=["var1", "1var2"])
    log_messages = [record.message for record in caplog.records]
    warning_msg = ("Invalid variable names: ['1var2']. Skipping these variables "
                   "and continuing.")
    assert warning_msg in log_messages


def test_saveframe_invalid_exclude_variables_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with pytest.raises(TypeError) as err:
            saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                      exclude_variables=1)
    err_msg = ("Variables '1' must be of type list, tuple or string (for a single "
               "variable), not '<class 'int'>'")
    assert str(err.value) == err_msg


def test_saveframe_no_error_raised(tmpdir):
    if hasattr(sys, "last_value"):
        delattr(sys, "last_value")
    if hasattr(sys, "last_exc"):
        delattr(sys, "last_exc")
    pkg_name = create_pkg(tmpdir)
    with pytest.raises(RuntimeError) as err:
        exec(f"from {pkg_name} import init_func2; init_func2()")
        saveframe()
    err_msg = ("No exception has been raised, and the session is not currently "
               "within a debugger. Unable to save frames. "
               "Use current_frame=True to save the current call stack.")
    assert str(err.value) == err_msg


def test_saveframe_save_current_frame_basic(tmpdir):
    # Ensure we don't have a leftover "last exception" state impacting behavior.
    if hasattr(sys, "last_value"):
        delattr(sys, "last_value")
    if hasattr(sys, "last_exc"):
        delattr(sys, "last_exc")

    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    # Capture the exact line number of the subsequent saveframe() call.
    frame = sys._getframe()
    expected_lineno = frame.f_lineno + 1
    saveframe(filename=filename, current_frame=True)
    data = load_pkl(filename)

    # No exception metadata should be stored for current_frame mode.
    assert set(data.keys()) == {1}
    assert data[1]["filename"] == os.path.realpath(__file__)
    assert data[1]["lineno"] == expected_lineno
    assert data[1]["function_name"] == "test_saveframe_save_current_frame_basic"
    assert "saveframe(" in data[1]["code"]


def test_saveframe_save_current_frame_ignores_last_exception(tmpdir):
    pkg_name = create_pkg(tmpdir)
    # Set sys.last_value/sys.last_exc via a synthetic exception,
    # then ensure current_frame=True ignores it.
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
        saveframe(filename=filename, current_frame=True)
        data = load_pkl(filename)

    assert exception_info_keys.isdisjoint(set(data.keys()))
    assert 1 in data
    assert data[1]["filename"] == os.path.realpath(__file__)


def test_saveframe_frame_format_1(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
        # Format: 'filename:line_no:func_name'
        saveframe(filename=filename, frames="pkg1/mod2.py:10:func2")
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {2}
        assert data[2]["filename"] == str(tmpdir / pkg_name / "pkg1" / "mod2.py")
        assert data[2]["function_name"] == "func2"

        # Format: 'filename::'
        saveframe(filename=filename, frames="mod1.py::")
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {3, 4}
        assert data[3]["filename"] == str(tmpdir / pkg_name / "mod1.py")
        assert data[3]["function_name"] == "func2"

        # Format: 'filename::func_name'
        saveframe(filename=filename, frames=f"{pkg_name}/mod1.py::func1")
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {4}
        assert data[4]["filename"] == str(tmpdir / pkg_name / "mod1.py")
        assert data[4]["function_name"] == "func1"


def test_saveframe_frame_format_2(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = str(tmpdir / f"saveframe_{get_random()}.pkl")

        saveframe(filename=filename, frames=["__init__.py::", "pkg1/mod2.py:10:func2"])
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {2, 5}
        assert data[2]["filename"] == str(tmpdir / pkg_name / "pkg1" / "mod2.py")
        assert (
            data[2]["function_qualname"] ==
            "func2" if VERSION_INFO < (3, 11) else "mod2_cls.func2")

        assert data[5]["filename"] == str(tmpdir / pkg_name / "__init__.py")
        assert data[5]["function_qualname"] == "init_func1"

        saveframe(filename=filename, frames=["pkg1/pkg2/mod3.py:6:", "mod1::"])
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {1, 3, 4}
        assert data[1]["filename"] == str(tmpdir / pkg_name / "pkg1" / "pkg2" / "mod3.py")
        assert data[1]["function_qualname"] == "func3"


def test_saveframe_frame_format_3(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
        saveframe(filename=filename, frames=3)
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {1, 2, 3}

        saveframe(filename=filename, frames=5)
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4, 5}


def test_saveframe_frame_format_4(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
        saveframe(filename=filename, frames="pkg1/mod2.py::..__init__.py:6:init_func1")
        data = load_pkl(filename)
        assert set(data.keys()) == exception_info_keys | {2, 3, 4, 5}

        with pytest.raises(ValueError) as err:
            saveframe(filename=filename,
                      frames="pkg1/mod3.py::..__init__.py:6:init_func1")
        err_msg = "No frame in the traceback matched the frame: 'pkg1/mod3.py::'"
        assert str(err.value) == err_msg


def test_saveframe_frame_format_5(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                             frames=f"{str(tmpdir)}/{pkg_name}/mod1.py::..")
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4}


def test_saveframe_variables(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                             frames=5, variables=['var1', 'var2'])
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4, 5}

    assert set(data[1]["variables"].keys()) == {"var1", "var2"}
    assert set(data[2]["variables"].keys()) == {"var1", "var2"}
    assert set(data[3]["variables"].keys()) == {"var1", "var2"}
    assert set(data[4]["variables"].keys()) == {"var1"}
    assert set(data[5]["variables"].keys()) == {"var1", "var2"}


def test_saveframe_exclude_variables(tmpdir, caplog):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
                             frames=5, exclude_variables=['var1', 'var2'])
    log_messages = [record.message for record in caplog.records]
    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4, 5}

    assert set(data[1]["variables"].keys()) == {"func3_var3"}
    assert set(data[2]["variables"].keys()) == {"self"}
    assert set(data[3]["variables"].keys()) == {"obj"}
    assert set(data[4]["variables"].keys()) == {"func1_var2"}
    assert set(data[5]["variables"].keys()) == set()
    qualname = "func2" if VERSION_INFO < (3, 11) else "mod2_cls.func2"
    warning_msg = (
        f"Cannot pickle variable: 'var3' for frame: 'File: {str(tmpdir)}/{pkg_name}"
        f"/pkg1/mod2.py, Line: 10, Function: {qualname}'.")
    assert warning_msg in "\n".join(log_messages)


def test_saveframe_defaults(tmpdir, caplog):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        with chdir(tmpdir):
            filename  = saveframe()
            log_messages = [record.message for record in caplog.records]
    # Test that saveframe.pkl file in the current working directory is used by
    # default.
    info_message = (f"Filename is not passed explicitly using the `filename` "
                    f"parameter. The frame info will be saved in the file: "
                    f"'{str(tmpdir)}/saveframe.pkl'.")
    assert info_message in log_messages
    info_message = ("`frames` parameter is not passed explicitly. The first frame "
                    "from the bottom will be saved by default.")
    assert info_message in log_messages
    assert os.path.basename(filename) == 'saveframe.pkl'
    data = load_pkl(filename)
    # Test that only first frame from the bottom (index = 1) is stored in the
    # data by default.
    assert set(data.keys()) == exception_info_keys | {1}


def test_saveframe_frame_metadata(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(
            filename=str(tmpdir / f"saveframe_{get_random()}.pkl"), frames=5)
    frames_metadata_checker(tmpdir, pkg_name, filename)


def test_saveframe_local_variables_data(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(
            filename=str(tmpdir / f"saveframe_{get_random()}.pkl"), frames=5)
    frames_local_variables_checker(pkg_name, filename)


def test_saveframe_exception_info(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func1; init_func1()"
    with run_code_and_set_exception(code, ValueError):
        filename = saveframe(
            filename=str(tmpdir / f"saveframe_{get_random()}.pkl"), frames=0)
    exception_info_checker(filename)


def test_saveframe_chained_exceptions(tmpdir):
    pkg_name = create_pkg(tmpdir)
    code = f"from {pkg_name} import init_func3; init_func3()"
    with run_code_and_set_exception(code, TypeError):
        filename = saveframe(
            filename=str(tmpdir / f"saveframe_{get_random()}.pkl"),
            frames=['__init__.py::init_func3', f'.*/{pkg_name}/.*::'])
    data = load_pkl(filename)

    assert 1 in set(data.keys())
    assert data[1]["code"] == 'raise TypeError("Chained exception") from err'
    assert data[1]["frame_index"] == 1
    assert data[1]["filename"] == str(
        tmpdir / pkg_name / "__init__.py")
    assert data[1]["lineno"] == 17
    assert data[1]["function_name"] == "init_func3"
    assert data[1]["function_qualname"] == "init_func3"
    assert data[1]["module_name"] == f"{pkg_name}"
    assert data[1]["frame_identifier"] == (
        f"{data[1]['filename']},{data[1]['lineno']},{data[1]['function_name']}")
    assert len(set(data.keys()) - exception_info_keys) == 5


def test_keyboard_interrupt_frame_metadata(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    code = dedent(f"""
    import sys
    from pyflyby import saveframe
    sys.path.append('{tmpdir}')
    from {pkg_name} import init_func4
    try:
        init_func4()
    except KeyboardInterrupt as err:
        if {VERSION_INFO[:2]} < (3, 12):
            sys.last_value = err
        else:
            sys.last_exc = err
    saveframe(filename='{filename}', frames=2)
    """)
    run_command(["python", "-c", code])
    frames_metadata_checker_for_keyboard_interrupt(tmpdir, pkg_name, filename)


def test_keyboard_interrupt_local_variables_data(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    code = dedent(f"""
        import sys
        from pyflyby import saveframe
        sys.path.append('{tmpdir}')
        from {pkg_name} import init_func4
        try:
            init_func4()
        except KeyboardInterrupt as err:
            if {VERSION_INFO[:2]} < (3, 12):
                sys.last_value = err
            else:
                sys.last_exc = err
        saveframe(filename='{filename}', frames=2)
        """)
    run_command(["python", "-c", code])
    frames_local_variables_checker_for_keyboard_interrupt(filename)


def test_keyboard_interrupt_exception_info(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    code = dedent(f"""
        import sys
        from pyflyby import saveframe
        sys.path.append('{tmpdir}')
        from {pkg_name} import init_func4
        try:
            init_func4()
        except KeyboardInterrupt as err:
            if {VERSION_INFO[:2]} < (3, 12):
                sys.last_value = err
            else:
                sys.last_exc = err
        saveframe(filename='{filename}', frames=0)
        """)
    run_command(["python", "-c", code])
    exception_info_checker_for_keyboard_interrupt(filename)


def test_saveframe_cmdline_no_exception():
    command = [BIN_DIR+"/saveframe", "python", "-c", "import os;"]
    err = run_command(command)
    err_msg = "Error: No exception is raised by the program: 'python -c import os;'"
    assert err_msg in err


def test_saveframe_cmdline_variables_and_exclude_variables():
    command = [BIN_DIR + "/saveframe", "--variables", "foo,bar",
               "--exclude_variables", "var", "python", "-c", "import os;"]
    err = run_command(command)
    err_msg = ("ValueError: Cannot pass both --variables and --exclude_variables "
               "arguments.")
    assert err_msg in err


def test_saveframe_cmdline_invalid_command_1():
    command = [BIN_DIR+"/saveframe", "python", "-c"]
    err = run_command(command)
    err_msg = "Error: Please pass a valid script / command to run!"
    assert err_msg in err


def test_saveframe_cmdline_invalid_command_2():
    command = [BIN_DIR+"/saveframe", "python"]
    err = run_command(command)
    err_msg = "Error: Please pass a valid script / command to run!"
    assert err_msg in err


def test_saveframe_cmdline_invalid_command_3():
    command = [BIN_DIR+"/saveframe"]
    err = run_command(command)
    err_msg = "Error: Please pass a valid script / command to run!"
    assert err_msg in err


def test_saveframe_cmdline_variables(tmpdir):
    pkg_name = create_pkg(tmpdir)
    tmp_mod = writetext(tmpdir / f"tmp_mod_{get_random()}.py", f"""
            import sys
            sys.path.append('{tmpdir}')
            from {pkg_name} import init_func1
            init_func1()
        """)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "5",
        "--variables", "var1, var2", "python", str(tmp_mod)]
    run_command(command)

    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4, 5}

    assert set(data[1]["variables"].keys()) == {"var1", "var2"}
    assert set(data[2]["variables"].keys()) == {"var1", "var2"}
    assert set(data[3]["variables"].keys()) == {"var1", "var2"}
    assert set(data[4]["variables"].keys()) == {"var1"}
    assert set(data[5]["variables"].keys()) == {"var1", "var2"}


def test_saveframe_cmdline_exclude_variables(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "5",
        "--exclude_variables", "var1,var2", "python", "-c",
        f"import sys; sys.path.append('{tmpdir}'); from {pkg_name} import "
        f"init_func1; init_func1()"]
    run_command(command)

    data = load_pkl(filename)
    assert set(data.keys()) == exception_info_keys | {1, 2, 3, 4, 5}

    assert set(data[1]["variables"].keys()) == {"func3_var3"}
    assert set(data[2]["variables"].keys()) == {"self"}
    assert set(data[3]["variables"].keys()) == {"obj"}
    assert set(data[4]["variables"].keys()) == {"func1_var2"}
    assert set(data[5]["variables"].keys()) == set()


def test_saveframe_cmdline_frame_metadata(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR+"/saveframe", "--filename", filename, "--frames", "5",
        "python", "-c",
        f"import sys; sys.path.append('{tmpdir}'); from {pkg_name} import "
        f"init_func1; init_func1()"]
    run_command(command)
    frames_metadata_checker(tmpdir, pkg_name, filename)


def test_saveframe_cmdline_local_variables_data(tmpdir):
    pkg_name = create_pkg(tmpdir)
    tmp_mod = writetext(tmpdir / f"tmp_mod_{get_random()}.py", f"""
        import sys
        sys.path.append('{tmpdir}')
        from {pkg_name} import init_func1
        init_func1()
    """)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "5",
        "python", str(tmp_mod)]
    run_command(command)
    frames_local_variables_checker(pkg_name, filename)


def test_saveframe_cmdline_exception_info(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "0",
        "python", "-c",
        f"import sys; sys.path.append('{tmpdir}'); from {pkg_name} import "
        f"init_func1; init_func1()"]
    run_command(command)
    exception_info_checker(filename)


def test_saveframe_cmdline_keyboard_interrupt_frame_metadata(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR+"/saveframe", "--filename", filename, "--frames", "2",
        "python", "-c",
        f"import sys; sys.path.append('{tmpdir}'); from {pkg_name} import "
        f"init_func4; init_func4()"]
    run_command(command)
    frames_metadata_checker_for_keyboard_interrupt(tmpdir, pkg_name, filename)


def test_saveframe_cmdline_keyboard_interrupt_local_variables_data(tmpdir):
    pkg_name = create_pkg(tmpdir)
    tmp_mod = writetext(tmpdir / f"tmp_mod_{get_random()}.py", f"""
        import sys
        sys.path.append('{tmpdir}')
        from {pkg_name} import init_func4
        init_func4()
    """)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "2",
        "python", str(tmp_mod)]
    run_command(command)
    frames_local_variables_checker_for_keyboard_interrupt(filename)


def test_saveframe_cmdline_keyboard_interrupt_exception_info(tmpdir):
    pkg_name = create_pkg(tmpdir)
    filename = str(tmpdir / f"saveframe_{get_random()}.pkl")
    command = [
        BIN_DIR + "/saveframe", "--filename", filename, "--frames", "0",
        "python", "-c",
        f"import sys; sys.path.append('{tmpdir}'); from {pkg_name} import "
        f"init_func4; init_func4()"]
    run_command(command)
    exception_info_checker_for_keyboard_interrupt(filename)


@pytest.mark.parametrize("num_frames", [1, 2, 3, 5])
def test_saveframe_in_debugger_1(tmpdir, num_frames):
    """
    Test saveframe when called from within a debugger with different frame counts.
    """
    output_filename, pkg_name = _run_saveframe_in_debugger(
        tmpdir, num_frames=num_frames)

    frames_metadata_checker(tmpdir, pkg_name, output_filename, num_frames=num_frames)
    frames_local_variables_checker(pkg_name, output_filename, num_frames=num_frames)


def test_saveframe_in_debugger_2(tmpdir):
    """
    Test the default behavior of saveframe when called from within a debugger,
    i.e., only the current frame is saved.
    """
    output_filename, pkg_name = _run_saveframe_in_debugger(tmpdir)

    # Use the checker functions to verify the saved data - default behavior saves 1 frame
    frames_metadata_checker(tmpdir, pkg_name, output_filename, num_frames=1)
    frames_local_variables_checker(pkg_name, output_filename, num_frames=1)


def test_saveframe_in_debugger_3(tmpdir):
    """
    Test saveframe when called from within a debugger after jumping one frame
    up. It should save only the frame at which we are currently at. 
    """
    output_filename, pkg_name = _run_saveframe_in_debugger(
        tmpdir, jump=True)

    data = load_pkl(output_filename)
    assert set(data.keys()) == {1}

    # Verify frame metadata - should be func2's metadata saved as frame 1
    frame_data = data[1]
    assert frame_data["frame_index"] == 1
    assert frame_data["function_name"] == "func2"
    assert frame_data["function_qualname"] == ("func2" if VERSION_INFO < (3, 11) else "mod2_cls.func2")
    assert frame_data["filename"] == str(tmpdir / pkg_name / "pkg1" / "mod2.py")
    assert frame_data["lineno"] == 10
    assert frame_data["code"] == 'func3()'
    assert frame_data["module_name"] == f"{pkg_name}.pkg1.mod2"

    # Verify local variables - should be func2's variables
    variables = frame_data["variables"]
    vars_set = set(variables.keys())
    vars_set.discard('saveframe')
    assert vars_set == {'self', 'var1', 'var2'}
    mod2 = __import__(f"{pkg_name}.pkg1.mod2", fromlist=['dummy'], level=0)
    self_val = pickle.loads(variables['self'])
    assert isinstance(self_val, mod2.mod2_cls)
    assert pickle.loads(variables['var1']) == 'foo'
    assert pickle.loads(variables['var2']) == (4, 9, 10)

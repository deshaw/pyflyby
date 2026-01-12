"""
pyflyby/_saveframe.py

Provides a utility to save the info for debugging / reproducing any issue.
Checkout the doc of the `saveframe` function for more info.
"""

from __future__ import annotations

from   contextlib               import contextmanager
from   dataclasses              import dataclass
from   enum                     import Enum
import inspect
import keyword
import linecache
import logging
import os
import pickle
import re
import stat
import sys
import traceback

"""
The protocol used while pickling the frame's data.
"""
PICKLE_PROTOCOL=5

"""
The permissions used to create the file where the data is stored by the
'saveframe' utility.
"""
FILE_PERMISSION = 0o644

"""
The default filename used for storing the data when the user does not explicitly
provide one.
"""
DEFAULT_FILENAME = 'saveframe.pkl'


@dataclass
class ExceptionInfo:
    """
    A dataclass to store the exception info.
    """
    exception_string: str
    exception_full_string: str
    exception_class_name: str
    exception_class_qualname: str
    exception_object: object
    traceback: list


@dataclass
class FrameMetadata:
    """
    A dataclass to store a frame's metadata.
    """
    frame_index: int
    filename: str
    lineno: int
    function_name: str
    function_qualname: str
    function_object: bytes
    module_name: str
    code: str
    frame_identifier: str


class FrameFormat(Enum):
    """
    Enum class to store the different formats supported by the `frames` argument
    in the `saveframe` utility. See the doc of `saveframe` for more info.
    """
    NUM = "NUM"
    LIST = "LIST"
    RANGE = "RANGE"


def _get_saveframe_logger():
    """
    Get the logger used for the saveframe utility.
    """
    log_format = (
        "[%(asctime)s:%(msecs)03d pyflyby.saveframe:%(lineno)s "
        "%(levelname)s] %(message)s")
    log_datefmt = "%Y%m%d %H:%M:%S"
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt=log_format, datefmt=log_datefmt)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger

_SAVEFRAME_LOGGER = _get_saveframe_logger()


@contextmanager
def _open_file(filename, mode):
    """
    A context manager to open the ``filename`` with ``mode``.
    This function ignores the ``umask`` while creating the file.

    :param filename:
      The file to open.
    :param mode:
      Mode in which to open the file.
    """
    old_umask = os.umask(0)
    fd = None
    file_obj = None
    try:
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_PERMISSION)
        file_obj = os.fdopen(fd, mode)
        yield file_obj
    finally:
        if file_obj is not None:
            file_obj.close()
        elif fd is not None:
            os.close(fd)
        os.umask(old_umask)


def _get_exception_info(exception_obj):
    """
    Get the metadata information for the ``exception_obj``.

    :param exception_obj:
      The exception raised by the user's code.
    :return:
      An `ExceptionInfo` object.
    """
    try:
        tb = (
            traceback.format_exception(
                type(exception_obj), exception_obj, exception_obj.__traceback__))
    except Exception as err:
        _SAVEFRAME_LOGGER.warning(
            "Error while formatting the traceback. Error: %a", err)
        tb = "Traceback couldn't be formatted"
    exception_info = ExceptionInfo(
        exception_string=str(exception_obj),
        exception_full_string=f'{exception_obj.__class__.__name__}: {exception_obj}',
        exception_class_name=exception_obj.__class__.__name__,
        exception_class_qualname=exception_obj.__class__.__qualname__,
        exception_object=exception_obj,
        traceback=tb
    )
    return exception_info


def _get_qualname(frame):
    """
    Get fully qualified name of the function for the ``frame``.

    In python 3.10, ``co_qualname`` attribute is not present, so use ``co_name``.
    """
    return (frame.f_code.co_qualname if hasattr(frame.f_code, "co_qualname")
            else frame.f_code.co_name)

def _get_frame_repr(frame):
    """
    Construct repr for the ``frame``. This is used in the info messages.

    :param frame:
      The frame object.
    :return:
      The string f'File: {filename}, Line: {lineno}, Function: {function_qualname}'
    """
    return (f"'File: {frame.f_code.co_filename}, Line: {frame.f_lineno}, "
            f"Function: {_get_qualname(frame)}'")


def _get_frame_local_variables_data(frame, variables, exclude_variables):
    """
    Get the local variables data of the ``frame``.

    :param frame:
      The frame object
    :param variables:
      Local variables to be included.
    :param exclude_variables:
      Local variables to be excluded.
    :return:
      A dict containing the local variables data, with the key as the variable
      name and the value as the pickled local variable value.
    """
    # A dict to store the local variables to be saved.
    local_variables_to_save = {}
    all_local_variables = frame.f_locals
    for variable in all_local_variables:
        # Discard the variables that starts with '__' like '__eq__', etc., to
        # keep the data clean.
        if variable.startswith('__'):
            continue
        if variables and variable not in variables:
            continue
        if exclude_variables and variable in exclude_variables:
            continue
        try:
            pickled_value = pickle.dumps(
                all_local_variables[variable], protocol=PICKLE_PROTOCOL)
        except Exception as err:
            _SAVEFRAME_LOGGER.warning(
                "Cannot pickle variable: %a for frame: %s. Error: %a. Skipping "
                "this variable and continuing.",
                variable, _get_frame_repr(frame), err)
        else:
            local_variables_to_save[variable] = pickled_value
    return local_variables_to_save


def _get_frame_function_object(frame):
    """
    Get the function object of the frame.

    This helper does a best-effort attempt to find the function object using
    locals and globals dict.

    :param frame:
      The frame object.
    :return:
      The function object from which the ``frame`` is originating.
    """
    func_name = frame.f_code.co_name
    func_qualname = _get_qualname(frame)
    info_msg = f"Can't get function object for frame: {_get_frame_repr(frame)}"
    return_msg = "Function object not found"
    # The function is most-likely either a local function or a class method.
    if func_name != func_qualname:
        prev_frame = frame.f_back
        # Handle the local functions.
        if "<locals>" in func_qualname:
            if prev_frame is None:
                _SAVEFRAME_LOGGER.info(info_msg)
                return return_msg
            # The function is present in the previous frame's (the parent) locals.
            if func_name in prev_frame.f_locals:
                return prev_frame.f_locals[func_name]
            _SAVEFRAME_LOGGER.info(info_msg)
            return return_msg
        # Handle the class methods.
        else:
            try:
                func_parent = func_qualname.split('.')[-2]
            except IndexError:
                _SAVEFRAME_LOGGER.info(info_msg)
                return return_msg
            # The parent is present in the globals, so extract the function object
            # using getattr.
            if func_parent in frame.f_globals:
                func_parent_obj = frame.f_globals[func_parent]
                if hasattr(func_parent_obj, func_name):
                    return getattr(func_parent_obj, func_name)
            _SAVEFRAME_LOGGER.info(info_msg)
            return return_msg
    # The function is most-likely a global function.
    else:
        if func_name in frame.f_globals:
            return frame.f_globals[func_name]
        _SAVEFRAME_LOGGER.info(info_msg)
        return return_msg


def _get_frame_module_name(frame):
    """
    Get the module name of the ``frame``.

    :param frame:
      The frame object.
    :return:
      The name of the module from which the ``frame`` is originating.
    """
    try:
        frame_module = inspect.getmodule(frame)
        if frame_module is not None:
            return frame_module.__name__
        _SAVEFRAME_LOGGER.info(
            "No module found for the frame: %s", _get_frame_repr(frame))
        return "Module name not found"
    except Exception as err:
        _SAVEFRAME_LOGGER.warning(
            "Module name couldn't be found for the frame: %s. Error: %a",
            _get_frame_repr(frame), err)
        return "Module name not found"


def _get_frame_code_line(frame):
    """
    Get the code line of the ``frame``.

    :param frame:
      The frame object.
    :return:
      The code line as returned by the `linecache` package.
    """
    filename = frame.f_code.co_filename
    lineno = frame.f_lineno
    code_line = linecache.getline(filename, lineno).strip()
    if code_line is None:
        code_line = f"No code content found at {filename!a}: {lineno}"
        _SAVEFRAME_LOGGER.info(code_line + f" for frame {_get_frame_repr(frame)}")
    return code_line


def _get_frame_metadata(frame_idx, frame_obj):
    """
    Get metadata for the frame ``frame_obj``.

    :param frame_idx:
      Index of the frame ``frame_obj`` from the bottom of the stack trace.
    :param frame_obj:
      The frame object for which to get the metadata.
    :return:
      A `FrameMetadata` object.
    """
    frame_function_object = _get_frame_function_object(frame_obj)
    try:
        if isinstance(frame_function_object, str):
            # Function object couldn't be found.
            pickled_function = frame_function_object
        else:
            pickled_function = pickle.dumps(
                frame_function_object, protocol=PICKLE_PROTOCOL)
    except Exception as err:
        _SAVEFRAME_LOGGER.info(
            "Cannot pickle the function object for the frame: %s. Error: %a",
            _get_frame_repr(frame_obj), err)
        pickled_function = "Function object not pickleable"
    # Object that stores all the frame's metadata.
    frame_metadata = FrameMetadata(
        frame_index=frame_idx,
        filename=frame_obj.f_code.co_filename,
        lineno=frame_obj.f_lineno,
        function_name=frame_obj.f_code.co_name,
        function_qualname=_get_qualname(frame_obj),
        function_object=pickled_function,
        module_name=_get_frame_module_name(frame_obj),
        code=_get_frame_code_line(frame_obj),
        frame_identifier=(
            f"{frame_obj.f_code.co_filename},{frame_obj.f_lineno},"
            f"{frame_obj.f_code.co_name}")
    )
    return frame_metadata

def _get_all_matching_frames(frame, all_frames):
    """
    Get all the frames from ``all_frames`` that match the ``frame``.

    The matching is done based on the filename / file regex, the line number
    and the function name.

    :param frame:
      Frame for which to find all the matching frames.
    :param all_frames:
      A list of all the frame objects from the exception object.
    :return:
      A list of all the frames that match the ``frame``. Each item in the list
      is a tuple of 2 elements, where the first element is the frame index
      (starting from the bottom of the stack trace) and the second element is
      the frame object.
    """
    if frame == ['']:
        # This is the case where the last frame is not passed in the range
        # ('first_frame..'). Return the first frame from the bottom as the last
        # frame.
        return [(1, all_frames[0])]
    all_matching_frames = []
    filename_regex, lineno, func_name = frame
    for idx, frame_obj in enumerate(all_frames):
        if re.search(filename_regex, frame_obj.f_code.co_filename) is None:
            continue
        if lineno and frame_obj.f_lineno != lineno:
            continue
        if (func_name and
                func_name not in (frame_obj.f_code.co_name, _get_qualname(frame_obj))):
            continue
        all_matching_frames.append((idx+1, frame_obj))
    return all_matching_frames


def _get_frames_to_save(frames, all_frames):
    """
    Get the frames we want to save from ``all_frames`` as per ``frames``.

    :param frames:
      Frames that user wants to save. This parameter stores the parsed frames
      returned by `_validate_frames` function.
    :param all_frames:
      A list of all the frame objects from the exception object.
    :return:
      A list of filtered frames to save. Each item in the list is a tuple of 2
      elements, where the first element is the frame index (starting from the
      bottom of the stack trace) and the second element is the frame object.
    """
    frames, frame_type = frames
    filtered_frames = []
    if frame_type is None:
        # No frame passed by the user, return the first frame from the bottom
        # of the stack trace.
        return [(1, all_frames[0])]
    elif frame_type == FrameFormat.NUM:
        if len(all_frames) < frames:
            _SAVEFRAME_LOGGER.info(
                "Number of frames to dump are %s, but there are only %s frames "
                "in the error stack. So dumping all the frames.",
                frames, len(all_frames))
            frames = len(all_frames)
        return [(idx+1, all_frames[idx]) for idx in range(frames)]
    elif frame_type == FrameFormat.LIST:
        for frame in frames:
            filtered_frames.extend(_get_all_matching_frames(frame, all_frames))
    elif frame_type == FrameFormat.RANGE:
        # Handle 'first_frame..last_frame' and 'first_frame..' formats.
        # Find all the matching frames for the first_frame and last_frame.
        first_matching_frames = _get_all_matching_frames(frames[0], all_frames)
        if len(first_matching_frames) == 0:
            raise ValueError(f"No frame in the traceback matched the frame: "
                             f"{':'.join(map(str, frames[0]))!a}")
        last_matching_frames = _get_all_matching_frames(frames[1], all_frames)
        if len(last_matching_frames) == 0:
            raise ValueError(f"No frame in the traceback matched the frame: "
                             f"{':'.join(map(str, frames[1]))!a}")
        # Take out the minimum and maximum indexes of the matching frames.
        first_idxs = (first_matching_frames[0][0], first_matching_frames[-1][0])
        last_idxs = (last_matching_frames[0][0], last_matching_frames[-1][0])
        # Find the maximum absolute distance between the start and end matching
        # frame indexes, and get all the frames in between that range.
        distances = [
            (abs(first_idxs[0] - last_idxs[0]), (first_idxs[0], last_idxs[0])),
            (abs(first_idxs[0] - last_idxs[1]), (first_idxs[0], last_idxs[1])),
            (abs(first_idxs[1] - last_idxs[0]), (first_idxs[1], last_idxs[0])),
            (abs(first_idxs[1] - last_idxs[1]), (first_idxs[1], last_idxs[1])),
        ]
        _, max_distance_pair = max(distances, key=lambda x: x[0])
        max_distance_pair = sorted(max_distance_pair)
        for idx in range(max_distance_pair[0], max_distance_pair[1] + 1):
            filtered_frames.append((idx, all_frames[idx-1]))

    # Only keep the unique frames and sort them using their index.
    filtered_frames = sorted(filtered_frames, key=lambda f: f[0])
    seen_frames = set()
    unique_filtered_frames = []
    # In chained exceptions, we can get the same frame at multiple indexes, so
    # get the unique frames without considering the index.
    for frame in filtered_frames:
        if frame[1] not in seen_frames:
            unique_filtered_frames.append(frame)
            seen_frames.add(frame[1])
    return unique_filtered_frames


def _get_all_frames_from_exception_obj(exception_obj):
    """
    Get all the frame objects from the exception object. It also handles chained
    exceptions.

    :param exception_obj:
      The exception raise by the user's code.
    :return:
      A list containing all the frame objects from the exception. The frames
      are stored in bottom-to-top order, with the bottom frame (the error frame)
      at index 0.
    """
    current_exception = exception_obj
    all_frames = []
    while current_exception:
        traceback = current_exception.__traceback__
        current_tb_frames = []
        while traceback:
            current_tb_frames.append(traceback.tb_frame)
            traceback = traceback.tb_next
        all_frames.extend(reversed(current_tb_frames))
        current_exception = (current_exception.__cause__ or
                             current_exception.__context__)
    return all_frames


def _get_all_frames_from_current_frame(current_frame):
    """
    Get all frame objects starting from the current frame up the call stack.

    :param current_frame:
      The current frame in the debugger.
    :return
      A list of all frame objects in bottom-to-top order, with the bottom frame
      (current frame) at index 0.
    """
    all_frames = []
    while current_frame:
        func_name = current_frame.f_code.co_name
        # We've reached the python internal frames. Break the loop.
        if func_name == '<module>':
            break
        all_frames.append(current_frame)
        current_frame = current_frame.f_back
    return all_frames


def _save_frames_and_exception_info_to_file(
        filename, frames, variables, exclude_variables, *,
        exception_obj=None, current_frame=None):
    """
    Save the frames and exception information in the file ``filename``.

    The data structure that gets saved is a dictionary. It stores each frame
    info in a separate entry with the key as the frame index (from the bottom of
    the stack trace). It also stores some useful exception information. The data
    gets dumped in the ``filename`` in pickled form. Following is the same
    structure of the info saved:
      {
          # 5th frame from the bottom
          5: {
                'frame_index': 5,
                'filename': '/path/to/file.py',
                'lineno': 3423,
                'function_name': 'func1',
                'function_qualname': 'FooClass.func1',
                'function_object': <pickled object>,
                'module_name': '<frame_module>'
                'frame_identifier': '/path/to/file.py,3423,func1',
                'code': '... python code line ...'
                'variables': {'local_variable1': <pickled value>, 'local_variable2': <pickled value>, ...}
            },
          # 17th frame from the bottom
          17: {
                'frame_index': 17,
                ...
            },
          ...
          'exception_full_string': f'{exc.__class.__name__}: {exc}'
          'exception_object': exc,
          'exception_string': str(exc),
          'exception_class_name': exc.__class__.__name__,
          'exception_class_qualname': exc.__class__.__qualname__,
          'traceback': '(multiline traceback)
      }

    NOTE: Exception info (such as 'exception_*') will not be stored if
    ``exception_obj`` is None.

    :param filename:
      The file path in which to save the information.
    :param frames:
      The frames to save in the file. This parameter stores the parsed frames
      returned by the `_validate_frames` function.
    :param variables:
      The local variables to include in each frame.
    :param exclude_variables:
      The local variables to exclude from each frame.
    :param exception_obj:
      The ``Exception`` raised by the user's code. This is used to extract all
      the required info; the traceback, all the frame objects, etc.
    :param current_frame:
      The current frame if the user is in a debugger. This is used to extract all
      the required info; the traceback, all the frame objects, etc.
    """
    # Mapping that stores all the information to save.
    frames_and_exception_info = {}
    if exception_obj:
        # Get the list of frame objects from the exception object.
        all_frames = _get_all_frames_from_exception_obj(
            exception_obj=exception_obj)
    else:
        all_frames = _get_all_frames_from_current_frame(
            current_frame=current_frame)

    # Take out the frame objects we want to save as per 'frames'.
    frames_to_save = _get_frames_to_save(frames, all_frames)
    _SAVEFRAME_LOGGER.info(
        "Number of frames that'll be saved: %s", len(frames_to_save))

    for frame_idx, frame_obj in frames_to_save:
        _SAVEFRAME_LOGGER.info(
            "Getting required info for the frame: %s", _get_frame_repr(frame_obj))
        frames_and_exception_info[frame_idx] = _get_frame_metadata(
            frame_idx, frame_obj).__dict__
        frames_and_exception_info[frame_idx]['variables'] = (
            _get_frame_local_variables_data(frame_obj, variables, exclude_variables))

    if exception_obj:
        _SAVEFRAME_LOGGER.info("Getting exception metadata info.")
        frames_and_exception_info.update(_get_exception_info(
            exception_obj).__dict__)
    _SAVEFRAME_LOGGER.info("Saving the complete data in the file: %a", filename)
    with _open_file(filename, 'wb') as f:
        pickle.dump(frames_and_exception_info, f, protocol=PICKLE_PROTOCOL)
    _SAVEFRAME_LOGGER.info("Done!!")


def _is_dir_and_ancestors_world_traversable(directory):
    """
    Is the ``directory`` and all its ancestors world traversable.

    For world traversability we check if the execute bit is set for the
    owner, group and others.

    :param directory:
      The directory to check.
    :return:
      `True` if ``directory`` and its ancestors are world traversable, else
      `False`.
    """
    required_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    dir_permission_mode = os.stat(directory).st_mode & 0o777
    if (dir_permission_mode & required_mode) != required_mode:
        return False
    return directory == "/" or _is_dir_and_ancestors_world_traversable(
        os.path.dirname(directory))


def _validate_filename(filename, utility):
    """
    Validate the value of ``filename``.

    :param filename:
      The file path to validate.
    :param utility:
      Indicates whether this helper is invoked by the ``pyflyby.saveframe`` function
      or the ``pyflyby/bin/saveframe`` script. See `_validate_saveframe_arguments`
      for more info.
    :return:
      The file path post validation. If ``filename`` is None, a default file
      named `DEFAULT_FILENAME` in the current working directory is returned.
    """
    if filename is None:
        filename = os.path.abspath(DEFAULT_FILENAME)
        _SAVEFRAME_LOGGER.info(
            "Filename is not passed explicitly using the %s. The frame info will "
            "be saved in the file: %a.",
            '`filename` parameter' if utility == 'function' else '--filename argument',
            filename)
    _SAVEFRAME_LOGGER.info("Validating filename: %a", filename)
    # Resolve any symlinks.
    filename = os.path.realpath(filename)
    if os.path.islink(filename):
        raise ValueError(f"Cyclic link exists in the file: {filename!a}")
    if os.path.isdir(filename):
        raise ValueError(f"{filename!a} is an already existing directory. Please "
                         f"pass a different filename.")
    if os.path.exists(filename):
        _SAVEFRAME_LOGGER.info(
            "File %a already exists. This run will overwrite the file.", filename)
    parent_dir = os.path.dirname(filename)
    # Check if the parent directory and the ancestors are world traversable.
    # Log a warning if not. Raise an error if the parent or any ancestor
    # directory doesn't exist.
    try:
        is_parent_and_ancestors_world_traversable = (
            _is_dir_and_ancestors_world_traversable(directory=parent_dir))
    except PermissionError:
        is_parent_and_ancestors_world_traversable = False
    except (FileNotFoundError, NotADirectoryError) as err:
        msg = (f"Error while saving the frames to the file: "
               f"{filename!a}. Error: {err!a}")
        raise type(err)(msg) from None
    except OSError as err:
        is_parent_and_ancestors_world_traversable = False
        _SAVEFRAME_LOGGER.warning(
            "Error while trying to determine if the parent directory: %a and "
            "the ancestors are world traversable. Error: %a", parent_dir, err)
    if not is_parent_and_ancestors_world_traversable:
        _SAVEFRAME_LOGGER.warning(
            "The parent directory %a or an ancestor is not world traversable "
            "(i.e., the execute bit of one of the ancestors is 0). The filename "
            "%a might not be accessible by others.", parent_dir, filename)
    return filename


def _validate_frames(frames, utility):
    """
    Validate the value of ``frames``.

    This utility validates / parses the ``frames`` based on the following formats:
      1. Single frame: frames=frame or frames=['frame']
      2. Multiple frames: frames='frame1,frame2,...' (for `pyflyby/bin/saveframe`
         script) or frames=['frame1', 'frame2', ...] (for `saveframe` function).
      3. Range of frames: frames='first_frame..last_frame'
      4. Range from first frame to bottom: frames='first_frame..'
      5. Number of frames from bottom: frames=num

    NOTE: Each frame is represented as 'file_regex:lineno:function_name'

    :param frames:
      Frames to validate
    :param utility:
      Indicates whether this helper is invoked by the ``pyflyby.saveframe`` function
      or the ``pyflyby/bin/saveframe`` script. See `_validate_saveframe_arguments`
      for more info.
    :return:
      A tuple of 2 items:
      1. Parsed frames:
          - None if ``frames`` is None.
          - If ``frames=num`` (case 5), this is the integer ``num``.
          - Otherwise, this is a list of tuples. Each tuple represents a frame
            and consists of three items: ``filename``, ``lineno``, and ``function_name``.
          - Example: For ``frames='/some/foo.py:32:,/some/bar.py:28:func'``, the
            first item would be ``[('/some/foo.py', 32, ''), ('/some/bar.py', 28, 'func')]``.

      2. The format of the ``frames``:
           - None if ``frames`` is None.
           - For cases 1 and 2, the format is `FrameFormat.LIST`.
           - For cases 3 and 4, the format is `FrameFormat.RANGE`.
           - For case 5, the format is `FrameFormat.NUM`.
    """
    if frames is None:
        _SAVEFRAME_LOGGER.info(
            "%s is not passed explicitly. The first frame from the bottom will be "
            "saved by default.",
            '`frames` parameter' if utility == 'function' else '--frames argument')
        return None, None
    _SAVEFRAME_LOGGER.info("Validating frames: %a", frames)
    try:
        # Handle frames as an integer.
        return int(frames), FrameFormat.NUM
    except (ValueError, TypeError):
        pass
    # Boolean to denote if the `frames` parameter is passed in the range format.
    is_range = False
    if isinstance(frames, str) and ',' in frames and utility == 'function':
        raise ValueError(
            f"Error while validating frames: {frames!a}. If you want to pass multiple "
            f"frames, pass a list/tuple of frames like {frames.split(',')} rather "
            f"than a comma separated string of frames.")
    if isinstance(frames, (list, tuple)):
        for frame in frames:
            if ',' in frame:
                raise ValueError(
                    f"Invalid frame: {frame!a} in frames: {frames} as it "
                    f"contains character ','. If you are trying to pass multiple "
                    f"frames, pass them as separate items in the list.")
        frames = ','.join(frames)
    all_frames = [frame.strip() for frame in frames.split(',')]
    # Handle the single frame and the range of frame formats.
    if len(all_frames) == 1:
        all_frames = [frame.strip() for frame in frames.split('..')]
        if len(all_frames) > 2:
            raise ValueError(
                f"Error while validating frames: {frames!a}. If you want to pass a "
                f"range of frames, the correct syntax is 'first_frame..last_frame'")
        elif len(all_frames) == 2:
            is_range = True
        else:
            is_range = False

    parsed_frames = []
    for idx, frame in enumerate(all_frames):
        frame_parts = frame.split(':')
        # Handle 'first_frame..' format (case 4.).
        if idx == 1 and len(frame_parts) == 1 and frame_parts[0] == '' and is_range:
            parsed_frames.append(frame_parts)
            break
        if len(frame_parts) != 3:
            raise ValueError(
                f"Error while validating frame: {frame!a}. The correct syntax for a "
                f"frame is 'file_regex:line_no:function_name' but frame {frame!a} "
                f"contains {len(frame_parts)-1} ':'.")
        if not frame_parts[0]:
            raise ValueError(
                f"Error while validating frame: {frame!a}. The filename / file "
                f"regex must be passed in a frame.")
        # Validate the line number passed in the frame.
        if frame_parts[1]:
            try:
                frame_parts[1] = int(frame_parts[1])
            except ValueError:
                raise ValueError(f"Error while validating frame: {frame!a}. The "
                                f"line number {frame_parts[1]!a} can't be "
                                f"converted to an integer.")
        parsed_frames.append(frame_parts)

    return parsed_frames, FrameFormat.RANGE if is_range else FrameFormat.LIST


def _is_variable_name_valid(name):
    """
    Is ``name`` a valid variable name.

    :param name:
      Variable name to validate.
    :return:
      `True` or `False`.
    """
    if not name.isidentifier():
        return False
    if keyword.iskeyword(name):
        return False
    return True


def _validate_variables(variables, utility):
    """
    Validate the value of ``variables``.

    If there are invalid variable names, filter them out and log a warning.

    :param variables:
      Variables to validate
    :param utility:
      Indicates whether this helper is invoked by the ``pyflyby.saveframe`` function
      or the ``pyflyby/bin/saveframe`` script. See `_validate_saveframe_arguments`
      for more info.
    :return:
      A tuple of filtered variables post validation.
    """
    if variables is None:
        return
    _SAVEFRAME_LOGGER.info("Validating variables: %a", variables)
    if isinstance(variables, str) and ',' in variables and utility == 'function':
        raise ValueError(
            f"Error while validating variables: {variables!a}. If you want to "
            f"pass multiple variable names, pass a list/tuple of names like "
            f"{variables.split(',')} rather than a comma separated string of names.")
    if isinstance(variables, (list, tuple)):
        all_variables = tuple(variables)
    elif isinstance(variables, str):
        all_variables = tuple(variable.strip() for variable in variables.split(','))
    else:
        raise TypeError(
            f"Variables '{variables}' must be of type list, tuple or string (for a "
            f"single variable), not '{type(variables)}'")
    invalid_variable_names = [variable for variable in all_variables
                              if not _is_variable_name_valid(variable)]
    if invalid_variable_names:
        _SAVEFRAME_LOGGER.warning(
            "Invalid variable names: %s. Skipping these variables and continuing.",
            invalid_variable_names)
        # Filter out invalid variables.
        all_variables = tuple(variable for variable in all_variables
                              if variable not in invalid_variable_names)
    return all_variables


def _validate_saveframe_arguments(
        filename, frames, variables, exclude_variables, utility='function'):
    """
    Validate and sanitize the parameters supported by the `saveframe` function.

    :param filename:
      File path in which to save the frame's info.
    :param frames:
      Specific error frames to save.
    :param variables:
      Local variables to include in each frame info.
    :param exclude_variables:
      Local variables to exclude from each frame info.
    :param utility:
      Indicates whether this helper is invoked by the ``pyflyby.saveframe`` function
      or the ``pyflyby/bin/saveframe`` script. Allowed values are 'function' and
      'script'. The saveframe function and script accept different types of
      values for their arguments. This parameter helps distinguish between them
      to ensure proper argument and parameter validation.
    :return:
      A tuple of ``filename``, ``frames``, ``variables`` and ``exclude_variables``
      post validation.
    """
    allowed_utility_values = ['function', 'script']
    if utility not in allowed_utility_values:
        raise ValueError(
            f"Invalid value for parameter 'utility': {utility!a}. Allowed values "
            f"are: {allowed_utility_values}")
    filename = _validate_filename(filename, utility)
    frames =_validate_frames(frames, utility)
    if variables and exclude_variables:
        raise ValueError(
            f"Cannot pass both {'`variables`' if utility == 'function' else '--variables'} "
            f"and {'`exclude_variables`' if utility == 'function' else '--exclude_variables'} "
            f"{'parameters' if utility == 'function' else 'arguments'}.")
    variables = _validate_variables(variables, utility)
    exclude_variables = _validate_variables(exclude_variables, utility)
    if not (variables or exclude_variables):
        _SAVEFRAME_LOGGER.info(
            "Neither %s nor %s %s is passed. All the local variables from the "
            "frames will be saved.",
            '`variables`' if utility == 'function' else '--variables',
            '`exclude_variables`' if utility == 'function' else '--exclude_variables',
            'parameter' if utility == 'function' else 'argument')

    return filename, frames, variables, exclude_variables


def saveframe(filename=None, frames=None, variables=None, exclude_variables=None,
              current_frame=False):
    """
    Utility to save information for debugging / reproducing an issue.

    Usage:
    --------------------------------------------------------------------------
    If you have a piece of code that is currently failing due to an issue
    originating from upstream code, and you cannot share your private
    code as a reproducer, use this function to save relevant information to a file.

    When to use:
      - After an Exception:
        - In an interactive session (IPython, Jupyter Notebook, pdb/ipdb),
          after your code raises an error, call this function to capture and
          save error frames specific to the upstream code.
        - Share the generated file with the upstream team, enabling them to
          reproduce and diagnose the issue independently.
      -  Without an Exception:
        - Even if no error has occurred, you can deliberately enter a debugger
          (e.g., using ``ipdb.set_trace()``) and save the frames.
        - This can be used in case you are experiencing slowness in the upstream
          code. Save the frames using this function to provide the upstream team
          with relevant information for further investigation.
      - Inline in your code (current_frame=True):
        - You can embed ``saveframe(current_frame=True)`` directly in your
          code to capture the call stack at that point.
        - This is useful for analyzing how a function is called, debugging
          without raising an exception, or capturing state for later inspection.

    Information saved in the file:
    --------------------------------------------------------------------------
    This utility captures and saves error stack frames to a file. It includes the
    values of local variables from each stack frame, as well as metadata about each
    frame and the exception raised by the user's code. Following is the sample
    structure of the info saved in the file:

    ::

      {
          # 5th frame from the bottom
          5: {
                'frame_index': 5,
                'filename': '/path/to/file.py',
                'lineno': 3423,
                'function_name': 'func1',
                'function_qualname': 'FooClass.func1',
                'function_object': <pickled object>,
                'module_name': '<frame_module>'
                'frame_identifier': '/path/to/file.py,3423,func1',
                'code': '... python code line ...'
                'variables': {'local_variable1': <pickled value>, 'local_variable2': <pickled value>, ...}
            },
          # 17th frame from the bottom
          17: {
                'frame_index': 17,
                ...
            },
          ...
          'exception_full_string': f'{exc.__class.__name__}: {exc}'
          'exception_object': exc,
          'exception_string': str(exc),
          'exception_class_name': exc.__class__.__name__,
          'exception_class_qualname': exc.__class__.__qualname__,
          'traceback': '(multiline traceback)
      }

    .. note::
      - The above data gets saved in the file in pickled form.
      - In the above data, the key of each frame's entry is the index of that frame
        from the bottom of the error stack trace. So the first frame from the bottom
        (the error frame) has index 1, and so on.
      - 'variables' key in each frame's entry stores the local variables of that frame.
      - The 'exception_object' key stores the actual exception object but without
        the __traceback__ info (for security reasons).
      - Exception info (such as 'exception_*') will not be stored in the file if
        you enter the debugger manually (e.g., using ``ipdb.set_trace()``) and
        call ``saveframe`` without an exception being raised.

    **Example usage**:

    ::

      # In an interactive session (ipython, jupyter notebook, etc.)

      >> <Your code raised an error>
      >> saveframe(filename=/path/to/file) # Saves the first frame from the bottom
      >> saveframe(filename=/path/to/file, frames=frames_to_save,
      .. variables=local_variables_to_save, exclude_variables=local_variables_to_exclude)

      # In an interactive debugger (pdb / ipdb)

      >> <Your code raised an error>
      >> ipdb.pm() # start a debugger
      >> OR
      >> <You entered the debugger using ipdb.set_trace()>
      >> ipdb> from pyflyby import saveframe
      >> ipdb> saveframe(filename=/path/to/file) # Saves the frame which you are currently at
      >> ipdb> saveframe(filename=/path/to/file, frames=frames_to_save,
      .. variables=local_variables_to_include, exclude_variables=local_variables_to_exclude)

      # Let's say your code is raising an error with the following traceback:

      File "dir/__init__.py", line 6, in init_func1
          func1()
      File "dir/mod1.py", line 14, in func1
          func2()
      File "dir/mod1.py", line 9, in func2
          obj.func2()
      File "dir/pkg1/mod2.py", line 10, in func2
          func3()
      File "dir/pkg1/pkg2/mod3.py", line 6, in func3
          raise ValueError("Error is raised")
      ValueError: Error is raised

      # To save the last frame (the error frame) in file '/path/to/file', use:
      >> saveframe(filename='/path/to/file')

      # To save a specific frame like `File "dir/mod1.py", line 9, in func2`, use:
      >> saveframe(filename='/path/to/file', frames='mod1.py:9:func2')

      # To save the last 3 frames from the bottom, use:
      >> saveframe(frames=3)

      # To save all the frames from 'mod1.py' and 'mod2.py' files, use:
      >> saveframe(filename='/path/to/file', frames=['mod1.py::', 'mod2.py::'])

      # To save a range of frames from 'mod1.py' to 'mod3.py', use:
      >> saveframe(frames='mod1.py::..mod3.py::')

      # To save a range of frames from '__init__.py' till the last frame, use:
      >> saveframe(frames='__init__.py::..')

      # To only save local variables 'var1' and 'var2' from the frames, use:
      >> saveframe(frames=<frames_to_save>, variables=['var1', 'var2'])

      # To exclude local variables 'var1' and 'var2' from the frames, use:
      >> saveframe(frames=<frames_to_save>, exclude_variables=['var1', 'var2'])

    For non-interactive use cases (e.g., a failing script or command), checkout
    `pyflyby/bin/saveframe` script.

    :param filename:
      File path in which to save the frame information. If this file already
      exists, it will be overwritten; otherwise, a new file will be created
      with permission mode '0o644'. If this parameter is not passed, the info
      gets saved in the 'saveframe.pkl' file in the current working directory.

    :param frames:
      Error stack frames to save. A single frame follows the format
      'filename:line_no:function_name', where:
        - filename: The file path or a regex pattern matching the file path
          (displayed in the stack trace) of that error frame.
        - line_no (Optional): The code line number (displayed in the stack trace)
          of that error frame.
        - function_name (Optional): The function name (displayed in the stack trace)
          of that error frame.

      Partial frames are also supported where line_no and/or function_name can
      be omitted:
        - filename:: -> Includes all the frames that matches the filename
        - filename:line_no: -> Include all the frames that matches specific line
          in any function in the filename
        - filename::function_name -> Include all the frames that matches any line
          in the specific function in the filename

      Following formats are supported to pass the frames:

        1. Single frame:
           frames='frame'
           Example: frames='/path/to/file.py:24:some_func'
           Includes only the specified frame.

        2. Multiple frames:
           frames=['frame1', 'frame2', ...]
           Example: frames=['/dir/foo.py:45:', '.*/dir2/bar.py:89:caller']
           Includes all specified frames.

        3. Range of frames:
           frames='first_frame..last_frame'
           Example: frames='/dir/foo.py:45:get_foo../dir3/blah.py:23:myfunc'
           Includes all the frames from first_frame to last_frame (both inclusive).

        4. Range from first_frame to bottom:
           frames='first_frame..'
           Example: frames='/dir/foo.py:45:get_foo..'
           Includes all the frames from first_frame to the bottom of the stack trace.

        5. Number of Frames from Bottom:
           frames=num
           Example: frames=5
           Includes the first 'num' frames from the bottom of the stack trace.

      Default behavior if this parameter is not passed:
        - When user is in a debugger (ipdb/pdb): Save the frame the user is
          currently at.
        - When user is not in a debugger: Save the first frame from the bottom
          (the error frame).

    :param variables:
      Local variables to include in each frame. It accepts a list/tuple of
      variable names or a string if there is only 1 variable.

      If this parameter is not passed, save all the local variables of the
      included frames.

    :param exclude_variables:
      Local variables to exclude from each frame. It accepts a list/tuple of
      variable names or a string if there is only 1 variable.

      If this parameter is not passed, save all the local variables of the
      included frames as per the ``variables`` parameter value.

    :param current_frame:
      If True, save the current call stack from the point where saveframe() is
      called, even if no exception has been raised and not inside a debugger.
      This is useful for embedding saveframe() directly in your code to analyze
      how a function is being called. Use `frames=N` to save the last N frames
      while using this option, otherwise only the last frame is saved.

      Default is False.

    :return:
      The file path in which the frame info is saved.
    """
    save_current_frame = current_frame
    _current_frame = None
    exception_obj = None
    exception_raised = False

    # Handle save_current_frame=True: capture the caller's frame directly
    # This takes priority over any existing exception
    if save_current_frame:
        # Get the caller's frame (frame 1 is saveframe itself, frame 2 is the caller)
        _current_frame = sys._getframe(1)
        if frames is None:
            # Default to saving the current frame
            frames = (f"{_current_frame.f_code.co_filename}:{_current_frame.f_lineno}:"
                      f"{_get_qualname(_current_frame)}")
        # Don't use exception traceback when save_current_frame=True
        # We want to capture the live call stack, not an old exception's traceback
    else:
        # Check if an exception has been raised.
        if ((sys.version_info < (3, 12) and hasattr(sys, 'last_value')) or
                (sys.version_info >= (3, 12) and hasattr(sys, 'last_exc'))):
            exception_raised = True
            # Get the latest exception raised.
            exception_obj = sys.last_value if sys.version_info < (3, 12) else sys.last_exc

        if not (exception_raised and frames):
            try:
                # Get the instance of the interactive session the user is currently in.
                interactive_session_obj = sys._getframe(2).f_locals.get('self')
                # If the user is currently in a debugger (ipdb/pdb), save the frame the
                # user is currently at in the debugger.
                if interactive_session_obj and hasattr(interactive_session_obj, 'curframe'):
                    _current_frame = interactive_session_obj.curframe
            except Exception as err:
                _SAVEFRAME_LOGGER.warning(
                    f"Error while extracting the interactive session object: {err}")
            # This logic handles two scenarios:
            # 1. No exception is raised and the debugger is started.
            # 2. An exception is raised, and the user then starts a debugger manually
            #    (e.g., via ipdb.pm()).
            # In both cases, we set the frame to the current frame as the default
            # behavior.
            if frames is None and _current_frame:
                frames = (f"{_current_frame.f_code.co_filename}:{_current_frame.f_lineno}:"
                          f"{_get_qualname(_current_frame)}")

        if not (exception_obj or _current_frame):
            raise RuntimeError(
                "No exception has been raised, and the session is not currently "
                "within a debugger. Unable to save frames. "
                "Use current_frame=True to save the current call stack.")

    _SAVEFRAME_LOGGER.info("Validating arguments passed.")
    filename, frames, variables, exclude_variables = _validate_saveframe_arguments(
        filename, frames, variables, exclude_variables)
    if exception_raised and exception_obj:
        _SAVEFRAME_LOGGER.info(
            "Saving frames and metadata for the exception: %a", exception_obj)
    _save_frames_and_exception_info_to_file(
        filename=filename, frames=frames, variables=variables,
        exclude_variables=exclude_variables,
        exception_obj=exception_obj, current_frame=_current_frame)
    return filename

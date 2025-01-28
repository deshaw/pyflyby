"""
pyflyby/_saveframe_reader.py

This module provides the ``SaveframeReader`` class, which is used to read data
saved by the ``saveframe`` utility.
"""

from __future__ import annotations

import logging
import pickle

from   pyflyby._saveframe       import ExceptionInfo, FrameMetadata

class SaveframeReader:
    """
    A class for reading data saved by the ``saveframe`` utility.

    The ``saveframe`` utility saves data as a pickled Python dictionary.
    Reading this raw data and extracting values of specific variables or metadata
    fields can be complex.

    The ``SaveframeReader`` class provides an easy and efficient way to read this
    raw data and extract specific items. This class has a user-friendly ``repr``
    for visualizing the data and provides various helpful methods to extract
    different items.

    **Usage Example:**

    **Creating an instance**

    First, create an instance of this class by passing the path of the file that
    contains the ``saveframe`` data.

    ::

      >> from pyflyby import SaveframeReader
      >> reader = SaveframeReader('/path/to/file')

    **Extracting all available metadata fields**

    To extract all available metadata fields, use the ``SaveframeReader.metadata``
    property. Example:

    ::

      >> reader.metadata
      ['frame_index', 'filename', 'lineno', 'function_name', 'function_qualname',
      'function_object', 'module_name', 'code', 'frame_identifier',
      'exception_string', 'exception_full_string', 'exception_class_name',
      'exception_class_qualname', 'exception_object', 'traceback']

    **Extracting all stored local variables**

    To extract the names of all local variables stored in the frames, use the
    ``SaveframeReader.variables`` property. Example:

    ::

      >> reader.variables
      {
           1: ['var1', 'var2', ...],
           2: ['var5', 'var8', 'var9', ...],
           ...
      }

    **Extracting the value of a specific metadata field**

    To extract the value of a specific metadata field, use the
    `SaveframeReader.get_metadata` method. Example:

    ::

      >> reader.get_metadata("filename")
      {1: '/dir1/mod1.py', 2: '/dir2/mod2.py', ...}

      >> reader.get_metadata("filename", frame_idx=2)
      '/dir2/mod2.py'

      >> reader.get_metadata("exception_string")
      "Error is raised"

    **Extracting the value of specific local variables**

    To extract the value of specific local variable(s), use the
    `SaveframeReader.get_variables` method. Example:

    ::

      >> reader.get_variables('var1')
      {2: var1_value2, 4: var1_value4}

      >>  reader.get_variables('var1', frame_idx=4)
      var1_value4

      >> reader.get_variables('var2')
      var2_value3

      >> reader.get_variables(['var1', 'var3'])
      {2: {'var1': var1_value2, 'var3': var3_value2},
      4: {'var1': var1_value4}, 5: {'var3': var3_value5}}

      >> reader.get_variables(['var1', 'var3'], frame_idx=2)
      {'var1': var1_value2, 'var3': var3_value2}

    Raw data can be extracted using ``SaveframeReader.data`` property.
    """

    def __init__(self, filename):
        """
        Initializes the ``SaveframeReader`` class.

        :param filename:
          The file path where the ``saveframe`` data is stored.
        """
        self._filename = filename
        with open(filename, 'rb') as f:
            self._data = pickle.load(f)
        if not isinstance(self._data, dict):
            raise ValueError(
                f"The data in the file '{filename}' is of type "
                f"'{type(self._data).__name__}', which is not valid saveframe "
                "data.")


    @property
    def filename(self):
        """
        The file path where the ``saveframe`` data is stored.
        """
        return self._filename


    @property
    def data(self):
        """
        Returns the raw ``saveframe`` data as a Python dictionary.
        """
        return self._data


    @property
    def metadata(self):
        """
        Returns a list of all metadata items present in the data.

        This includes both frame metadata and exception metadata. The returned
        list contains the names of all metadata fields. For example:
        ['frame_index', 'filename', ..., 'exception_object', 'traceback'].

        To obtain the value of a specific metadata field, use the
        `SaveframeReader.get_metadata` method.
        """
        metadata = []
        metadata.extend([field for field in FrameMetadata.__dataclass_fields__])
        metadata.extend([field for field in ExceptionInfo.__dataclass_fields__])
        return metadata


    @property
    def variables(self):
        """
        Returns the local variables present in each frame.

        The returned value is a dictionary where the keys are frame indices and
        the values are lists of local variable names in those frames. For example:

        ::

          {
              1: ['variable1', 'variable2', ...],
              2: ['variable5', 'variable6', 'variable8'],
              ...
          }

        To obtain the value of specific variable(s), use the
        `SaveframeReader.get_variables` method.
        """
        frame_idx_to_variables_map = {}
        for key_item in self._data:
            if not isinstance(key_item, int):
                continue
            frame_idx_to_variables_map[key_item] = list(
                self._data[key_item]['variables'].keys())
        return frame_idx_to_variables_map


    def get_metadata(self, metadata, *, frame_idx=None):
        """
        Retrieve the value of a specific metadata field.

        **Example usage:**

        ::

          >> reader = SaveframeReader("/path/to/file")

          >> reader.get_metadata("filename")
          {1: '/dir1/mod1.py', 2: '/dir2/mod2.py', ...}

          >> reader.get_metadata("filename", frame_idx=2)
          '/dir2/mod2.py'

          >> reader.get_metadata("exception_string")
          "Error is raised"

        :param metadata:
          The metadata field for which to get the value.
        :param frame_idx:
          The index of the frame from which to get the metadata value. Default is
          None, which means metadata from all frames is returned. This parameter
          is only supported for frame metadata, not exception metadata.
        :return:
          - If ``frame_idx`` is None (default):
              - If ``metadata`` is a frame metadata field, a dictionary is returned
                with the frame index as the key and the metadata value as the value.
              - If ``metadata`` is an exception metadata field, the value of the
                metadata is returned.
          - If ``frame_idx`` is specified:
              - If ``metadata`` is a frame metadata field, the metadata value for
                the specified frame is returned.
              - If ``metadata`` is an exception metadata field, an error is raised.
        """
        # Sanity checks.
        all_metadata_entries = self.metadata
        if metadata not in all_metadata_entries:
            raise ValueError(
                f"Invalid metadata requested: {metadata!a}. Allowed metadata "
                f"entries are: {all_metadata_entries}.")
        exception_metadata = ([field for field in ExceptionInfo.__dataclass_fields__])
        # Handle exception metadata.
        if metadata in exception_metadata:
            if frame_idx:
                raise ValueError(
                    "'frame_idx' is not supported for querying exception "
                    f"metadata: {metadata!a}.")
            return self._data[metadata]
        # frame_idx is not passed.
        if frame_idx is None:
            frame_idx_to_metadata_value_map = {}
            for key_item in self._data:
                if key_item in exception_metadata:
                    continue
                metadata_value = self._data[key_item][metadata]
                # Unpickle the 'function_object' metadata value.
                if metadata == "function_object":
                    try:
                        if not isinstance(metadata_value, str):
                            metadata_value = pickle.loads(metadata_value)
                    except Exception as err:
                        logging.warning("Can't unpickle the 'function_object' "
                                        "value for frame: %a. Error: %s",
                                        key_item, err)
                        metadata_value = (
                            f"Can't unpickle the 'function_object'. Error: {err}")
                frame_idx_to_metadata_value_map[key_item] = metadata_value
            return frame_idx_to_metadata_value_map

        # frame_idx is passed.
        if not isinstance(frame_idx, int):
            raise TypeError(
                "'frame_idx' must be of type 'int', not "
                f"'{type(frame_idx).__name__}'.")
        try:
            metadata_value = self._data[frame_idx][metadata]
            if metadata == "function_object":
                try:
                    if not isinstance(metadata_value, str):
                        metadata_value = pickle.loads(metadata_value)
                except Exception as err:
                    logging.warning("Can't unpickle the 'function_object' "
                                    "value for frame: %a. Error: %s",
                                    frame_idx, err)
            return metadata_value
        except KeyError:
            allowed_frame_idx = list(
                set(self._data.keys()) - set(exception_metadata))
            raise ValueError(
                f"Invalid value for 'frame_idx': '{frame_idx}'.  Allowed values "
                f"are: {allowed_frame_idx}.")


    def get_variables(self, variables, *, frame_idx=None):
        """
        Retrieve the value of local variable(s) from specific frames.

        **Example usage:**

        ::

          >> reader = SaveframeReader('/path/to/file')

          >> reader.get_variables('var1')
          {2: var1_value2, 4: var1_value4}

          >>  reader.get_variables('var1', frame_idx=4)
          var1_value4

          >>  reader.get_variables(('var1',), frame_idx=4)
          {'var1': var1_value4}

          >> reader.get_variables('var2')
          var2_value3 # 'var2' is only present in frame 3

          >> reader.get_variables(['var1', 'var3'])
          {2: {'var1': var1_value2, 'var3': var3_value2},
           4: {'var1': var1_value4}, 5: {'var3': var3_value5}}

          >> reader.get_variables(['var1', 'var3'], frame_idx=2)
          {'var1': var1_value2, 'var3': var3_value2}

        :param variables:
          One or more variable names for which to retrieve the values. You can 
          pass a single variable name as a string or a list / tuple of variable
          names.

        :param frame_idx:
          The index of the frame from which to retrieve the value(s) of the
          variable(s). Default is None, which means values from all frames are
          returned.
        :return:
          - If ``frame_idx`` is None (default):
              - For a single variable:
                  - A dictionary with frame indices as keys and variable values
                    as values.
                  - If the variable is present in only one frame, the value is
                    returned directly.
              - For a list / tuple of variables:
                  - A dictionary with frame indices as keys and dictionaries as
                    values, where each inner dictionary contains the queried
                    variables and their values for that frame.
                  - If the queried variables are present in only one frame, a
                    dictionary of those variables and their values is returned.
          - If ``frame_idx`` is specified:
              - For a single variable:
                  - The value of the variable in the specified frame.
                  - If the variable is not present in that frame, an error is raised.
              - For a list / tuple of variables:
                  - A dictionary with the variable names as keys and their values
                    as values, for the specified frame.
                  - If none of the queried variables are present in that frame,
                    an error is raised.
        """
        # Boolean to denote if variables are passed as a list or tuple.
        variables_passed_as_list_or_tuple = False
        # Sanity checks.
        if isinstance(variables, (list, tuple)):
            variables_passed_as_list_or_tuple = True
            for variable in variables:
                if not isinstance(variable, str):
                    raise TypeError(
                        f"Invalid type for variable name: {type(variable).__name__}. "
                        "Expected string type instead.")
        elif isinstance(variables, str):
            variables = (variables,)
        else:
            raise TypeError(
                f"'variables' must either be a string or a list/tuple. "
                f"Got '{type(variables).__name__}'.")
        if len(variables) == 0:
            raise ValueError("No 'variables' passed.")

        def _get_variable_value_on_unpickle_error(err):
            """
            Get variable's value when it fails to unpickle due to error ``err``.
            """
            return f"Can't un-pickle the variable. Error: {err}"

        # frame_idx is not passed.
        if frame_idx is None:
            frame_idx_to_variables_map = {}
            for key_item in self._data:
                if not isinstance(key_item, int):
                    continue
                variables_map = self._data[key_item]['variables']
                for variable in variables:
                    try:
                        variable_value = variables_map[variable]
                    except KeyError:
                        continue
                    try:
                        variable_value = pickle.loads(variable_value)
                    except Exception as err:
                        logging.warning(
                            "Can't un-pickle the value of variable %a for frame "
                            "%a. Error: %s", variable, key_item, err)
                        variable_value = _get_variable_value_on_unpickle_error(err)
                    if len(variables) == 1 and not variables_passed_as_list_or_tuple:
                        # Single variable is queried.
                        frame_idx_to_variables_map[key_item] = variable_value
                    else:
                        # Multiple variables are queried. The result would be
                        # a dict where keys would be the frame indices and values
                        # would the dicts containing the queried variables and
                        # their values for that frame.
                        if not key_item in frame_idx_to_variables_map:
                            frame_idx_to_variables_map[key_item] = {}
                        frame_idx_to_variables_map[key_item][variable] = variable_value
            if not frame_idx_to_variables_map:
                raise ValueError(f"Local variable(s) {variables} not found in "
                                 "any of the saved frames.")
            # If there is only 1 frame in the result, return the value directly.
            if len(frame_idx_to_variables_map) == 1:
                return frame_idx_to_variables_map.popitem()[1]
            return frame_idx_to_variables_map

        # frame_idx is passed.
        if not isinstance(frame_idx, int):
            raise TypeError(
                "'frame_idx' must be of type 'int', not "
                f"'{type(frame_idx).__name__}'.")
        try:
            variables_map = self._data[frame_idx]['variables']
        except KeyError:
            allowed_frame_idx = list(
                set(self._data.keys()) - set(self.metadata))
            raise ValueError(
                f"Invalid value for 'frame_idx': '{frame_idx}'. Allowed values "
                f"are: {allowed_frame_idx}.")
        variable_key_to_value_map = {}
        for variable in variables:
            try:
                variable_value = variables_map[variable]
            except KeyError:
                continue
            try:
                variable_value = pickle.loads(variable_value)
            except Exception as err:
                logging.warning(
                    "Can't un-pickle the value of variable %a for frame "
                    "%a. Error: %s", variable, frame_idx, err)
                if len(variables) > 1:
                    variable_value = _get_variable_value_on_unpickle_error(err)
            if len(variables) == 1 and not variables_passed_as_list_or_tuple:
                # Single variable is queried. Directly return the value.
                return variable_value
            variable_key_to_value_map[variable] = variable_value
        if not variable_key_to_value_map:
            raise ValueError(f"Local variable(s) {variables} not found in "
                             f"frame {frame_idx}")
        return variable_key_to_value_map


    def __str__(self):
        frames_info = []
        for frame_idx, frame_data in self._data.items():
            if isinstance(frame_idx, int):
                frame_info = (
                    f"Frame {frame_idx}:\n"
                    f"  Filename: '{frame_data.get('filename')}'\n"
                    f"  Line Number: {frame_data.get('lineno')}\n"
                    f"  Function: {frame_data.get('function_qualname')}\n"
                    f"  Module: {frame_data.get('module_name')}\n"
                    f"  Frame ID: '{frame_data.get('frame_identifier')}'\n"
                    f"  Code: {frame_data.get('code')}\n"
                    f"  Variables: {list(frame_data.get('variables', {}).keys())}\n"
                )
                frames_info.append(frame_info)

        exception_info = (
            f"Exception:\n"
            f"  Full String: {self._data.get('exception_full_string')}\n"
            f"  String: {self._data.get('exception_string')}\n"
            f"  Class Name: {self._data.get('exception_class_name')}\n"
            f"  Qualified Name: {self._data.get('exception_class_qualname')}\n"
        )

        return "Frames:\n" + "\n".join(frames_info) + "\n" + exception_info

    def __repr__(self):
        return f"{self.__class__.__name__}(\nfilename: {self._filename!a} \n\n{str(self)})"

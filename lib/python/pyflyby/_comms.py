from __future__ import absolute_import, division

from   pyflyby._log             import logger
import six

# These are comm targets that the frontend (lab/notebook) is expected to
# register. At this point, we handle only missing imports and
# formatting imports

MISSING_IMPORTS = "pyflyby.missing_imports"
FORMATTING_IMPORTS = "pyflyby.format_imports"

pyflyby_comm_targets= [MISSING_IMPORTS, FORMATTING_IMPORTS]

# A map of the comms opened with a given target name.
comms = {}

# TODO: Document the expected contract for the different
# custom comm messages

def _register_target(target_name):
    try:
        ip = get_ipython()
    except:
        logger.debug("get_ipython() doesn't work")
    else:
        comm_manager = ip.kernel.comm_manager
        comm_manager.register_target(target_name, comm_open_handler)


def initialize_comms():
    for target in pyflyby_comm_targets:
        _register_target(target)


def remove_comms():
    for target_name, comm in six.iteritems(comms):
        comm.close()
        logger.debug("Closing comm for " + target_name)

def send_comm_message(target_name, msg):
    try:
        comm = comms[target_name]
    except KeyError:
        logger.error("Comm with target_name " + target_name)
    else:
        # Help the frontend distinguish between multiple types
        # of custom comm messages
        msg["type"] = target_name
        comm.send(msg)
        logger.debug("Sending comm message for target " + target_name)


def comm_close_handler(comm, message):
    comm_id = message["comm_id"]
    for target, comm in six.iterkeys(comms):
        if comm.comm_id == comm_id:
            comms.pop(target)

def comm_open_handler(comm, message):
    """
    Handles comm_open message for pyflyby custom comm messages.
    https://jupyter-client.readthedocs.io/en/stable/messaging.html#opening-a-comm.

    Handler for all PYFLYBY custom comm messages that are opened by the frontend
    (at this point, just the jupyterlab frontend does this).

    """
    from   pyflyby._imports2s       import reformat_import_statements

    comm.on_close(comm_close_handler)
    comms[message["content"]["target_name"]] = comm

    @comm.on_msg
    def _recv(msg):

        if msg["content"]["data"]["type"] == FORMATTING_IMPORTS:
            fmt_code = reformat_import_statements(msg["content"]["data"]["input_code"])
            comm.send({"formatted_code": str(fmt_code), "type": FORMATTING_IMPORTS})

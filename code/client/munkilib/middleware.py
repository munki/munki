#!/usr/bin/python

import os
import subprocess
from threading import Timer

import munkicommon
import fetch


"""
To use this module you must provide a path to the middleware
you wish to execute. You must also be able to provide responses
for these 2 arguments.

/path/to/middleware [arg1] [arg2]

arg1: the URL
arg2: is either 'headers' or 'url'
    When 'headers' is called:
        The middleware must return one header per line to stdout
    When 'url' is called:
        The middleware must return the modified URL to stdout.

"""

MIDDLEWARE_PATH = munkicommon.pref('Middleware')


class Exec(Exception):
    """General exception for middleware"""
    pass

class Timeout(Exception):
    """Timeout exception for middleware"""
    pass

def kill_proc(proc, timeout):
    timeout["value"] = True
    proc.kill()

def cmd_with_timeout(cmd, timeout_sec):
    """run command with timeout
    based off http://stackoverflow.com/a/10768774"""
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    timeout = {"value": False}
    timer = Timer(timeout_sec, kill_proc, [proc, timeout])
    timer.start()
    stdout, stderr = proc.communicate()
    timer.cancel()
    return proc.returncode, stdout.decode("utf-8"), stderr.decode("utf-8"), timeout["value"]


def process_request_options(options):
    """Executes a command using options['url'] as an arguement.
    the 'url' and 'additional_headers' keys may be changed as a
    result of the output. Returns modified options."""
    # can't see why you'd need to do this
    # when talking to apple
    if 'swscan.apple.com' not in options['url']:
        if MIDDLEWARE_PATH:
            munkicommon.display_debug2('Middleware: %s' % MIDDLEWARE_PATH)
            if os.path.exists(MIDDLEWARE_PATH):
                if os.access(MIDDLEWARE_PATH, os.X_OK):
                    for request_type in ['headers', 'url']:
                        cmd = [MIDDLEWARE_PATH, options['url'], request_type]
                        (code, output, err, timeout) = cmd_with_timeout(cmd, 5)
                        if timeout:
                            cmd_string = ' '.join(cmd)
                            error = "Command timed out:\n\n" \
                                       + cmd_string + '\n\n' "Output:\n" + output
                            raise Timeout(error)
                        if code != 0:
                            raise Exec(err)
                        if request_type == 'headers':
                            headers_list = output.splitlines()
                            header_dict = fetch.header_dict_from_list(headers_list)
                            options['additional_headers'].update(header_dict)
                        if request_type == 'url':
                            new_url = output.splitlines()[0]
                            if new_url:
                                options['url'] = output.splitlines()[0]
                else:
                    munkicommon.display_warning('%s not executable',
                                                MIDDLEWARE_PATH)
            else:
                munkicommon.display_warning('Middleware not at path %s',
                                            MIDDLEWARE_PATH)
    return options
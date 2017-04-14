#
# Copyright 2010 Per Olofsson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from ctypes import *
libc = CDLL("/usr/lib/libc.dylib")


c_launch_data_t = c_void_p

# size_t launch_data_array_get_count(const launch_data_t)
launch_data_array_get_count = libc.launch_data_array_get_count
launch_data_array_get_count.restype = c_size_t
launch_data_array_get_count.argtypes = [c_launch_data_t]

#launch_data_t launch_data_array_get_index(const launch_data_t, size_t) __ld_getter;
launch_data_array_get_index = libc.launch_data_array_get_index
launch_data_array_get_index.restype = c_launch_data_t
launch_data_array_get_index.argtypes = [c_launch_data_t, c_size_t]

# size_t launch_data_dict_get_count(const launch_data_t)
launch_data_dict_get_count = libc.launch_data_dict_get_count
launch_data_dict_get_count.restype = c_size_t
launch_data_dict_get_count.argtypes = [c_launch_data_t]

# launch_data_t launch_data_dict_lookup(const launch_data_t, const char *)
launch_data_dict_lookup = libc.launch_data_dict_lookup
launch_data_dict_lookup.restype = c_launch_data_t
launch_data_dict_lookup.argtypes = [c_launch_data_t, c_char_p]

#void launch_data_dict_iterate(const launch_data_t, void (*)(const launch_data_t, const char *, void *), void *) __ld_iterator(1, 2)
DICTITCALLBACK = CFUNCTYPE(c_void_p, c_launch_data_t, c_char_p, c_void_p)
launch_data_dict_iterate = libc.launch_data_dict_iterate
launch_data_dict_iterate.restype = None
launch_data_dict_iterate.argtypes = [c_launch_data_t, DICTITCALLBACK, c_void_p]

# void launch_data_free(launch_data_t)
launch_data_free = libc.launch_data_free
launch_data_free.restype = None
launch_data_free.argtypes = [c_launch_data_t]

# int launch_data_get_errno(const launch_data_t)
launch_data_get_errno = libc.launch_data_get_errno
launch_data_get_errno.restype = c_int
launch_data_get_errno.argtypes = [c_launch_data_t]

# int launch_data_get_fd(const launch_data_t)
launch_data_get_fd = libc.launch_data_get_fd
launch_data_get_fd.restype = c_int
launch_data_get_fd.argtypes = [c_launch_data_t]

# launch_data_type_t launch_data_get_type(const launch_data_t)
launch_data_get_type = libc.launch_data_get_type
launch_data_get_type.restype = c_launch_data_t
launch_data_get_type.argtypes = [c_launch_data_t]

# launch_data_t launch_data_new_string(const char *)
launch_data_new_string = libc.launch_data_new_string
launch_data_new_string.restype = c_launch_data_t
launch_data_new_string.argtypes = [c_char_p]

# launch_data_t launch_msg(const launch_data_t)
launch_msg = libc.launch_msg
launch_msg.restype = c_launch_data_t
launch_msg.argtypes = [c_launch_data_t]


LAUNCH_KEY_SUBMITJOB						= c_char_p("SubmitJob")
LAUNCH_KEY_REMOVEJOB						= c_char_p("RemoveJob")
LAUNCH_KEY_STARTJOB							= c_char_p("StartJob")
LAUNCH_KEY_STOPJOB							= c_char_p("StopJob")
LAUNCH_KEY_GETJOB							= c_char_p("GetJob")
LAUNCH_KEY_GETJOBS							= c_char_p("GetJobs")
LAUNCH_KEY_CHECKIN							= c_char_p("CheckIn")

LAUNCH_JOBKEY_LABEL							= c_char_p("Label")
LAUNCH_JOBKEY_DISABLED						= c_char_p("Disabled")
LAUNCH_JOBKEY_USERNAME						= c_char_p("UserName")
LAUNCH_JOBKEY_GROUPNAME						= c_char_p("GroupName")
LAUNCH_JOBKEY_TIMEOUT						= c_char_p("TimeOut")
LAUNCH_JOBKEY_EXITTIMEOUT					= c_char_p("ExitTimeOut")
LAUNCH_JOBKEY_INITGROUPS					= c_char_p("InitGroups")
LAUNCH_JOBKEY_SOCKETS						= c_char_p("Sockets")
LAUNCH_JOBKEY_MACHSERVICES					= c_char_p("MachServices")
LAUNCH_JOBKEY_MACHSERVICELOOKUPPOLICIES		= c_char_p("MachServiceLookupPolicies")
LAUNCH_JOBKEY_INETDCOMPATIBILITY			= c_char_p("inetdCompatibility")
LAUNCH_JOBKEY_ENABLEGLOBBING				= c_char_p("EnableGlobbing")
LAUNCH_JOBKEY_PROGRAMARGUMENTS				= c_char_p("ProgramArguments")
LAUNCH_JOBKEY_PROGRAM						= c_char_p("Program")
LAUNCH_JOBKEY_ONDEMAND						= c_char_p("OnDemand")
LAUNCH_JOBKEY_KEEPALIVE						= c_char_p("KeepAlive")
LAUNCH_JOBKEY_LIMITLOADTOHOSTS				= c_char_p("LimitLoadToHosts")
LAUNCH_JOBKEY_LIMITLOADFROMHOSTS			= c_char_p("LimitLoadFromHosts")
LAUNCH_JOBKEY_LIMITLOADTOSESSIONTYPE		= c_char_p("LimitLoadToSessionType")
LAUNCH_JOBKEY_RUNATLOAD						= c_char_p("RunAtLoad")
LAUNCH_JOBKEY_ROOTDIRECTORY					= c_char_p("RootDirectory")
LAUNCH_JOBKEY_WORKINGDIRECTORY				= c_char_p("WorkingDirectory")
LAUNCH_JOBKEY_ENVIRONMENTVARIABLES			= c_char_p("EnvironmentVariables")
LAUNCH_JOBKEY_USERENVIRONMENTVARIABLES		= c_char_p("UserEnvironmentVariables")
LAUNCH_JOBKEY_UMASK							= c_char_p("Umask")
LAUNCH_JOBKEY_NICE							= c_char_p("Nice")
LAUNCH_JOBKEY_HOPEFULLYEXITSFIRST	  		= c_char_p("HopefullyExitsFirst")
LAUNCH_JOBKEY_HOPEFULLYEXITSLAST   			= c_char_p("HopefullyExitsLast")
LAUNCH_JOBKEY_LOWPRIORITYIO					= c_char_p("LowPriorityIO")
LAUNCH_JOBKEY_SESSIONCREATE					= c_char_p("SessionCreate")
LAUNCH_JOBKEY_STARTONMOUNT					= c_char_p("StartOnMount")
LAUNCH_JOBKEY_SOFTRESOURCELIMITS			= c_char_p("SoftResourceLimits")
LAUNCH_JOBKEY_HARDRESOURCELIMITS			= c_char_p("HardResourceLimits")
LAUNCH_JOBKEY_STANDARDINPATH				= c_char_p("StandardInPath")
LAUNCH_JOBKEY_STANDARDOUTPATH				= c_char_p("StandardOutPath")
LAUNCH_JOBKEY_STANDARDERRORPATH				= c_char_p("StandardErrorPath")
LAUNCH_JOBKEY_DEBUG							= c_char_p("Debug")
LAUNCH_JOBKEY_WAITFORDEBUGGER				= c_char_p("WaitForDebugger")
LAUNCH_JOBKEY_QUEUEDIRECTORIES				= c_char_p("QueueDirectories")
LAUNCH_JOBKEY_WATCHPATHS					= c_char_p("WatchPaths")
LAUNCH_JOBKEY_STARTINTERVAL					= c_char_p("StartInterval")
LAUNCH_JOBKEY_STARTCALENDARINTERVAL			= c_char_p("StartCalendarInterval")
LAUNCH_JOBKEY_BONJOURFDS					= c_char_p("BonjourFDs")
LAUNCH_JOBKEY_LASTEXITSTATUS				= c_char_p("LastExitStatus")
LAUNCH_JOBKEY_PID							= c_char_p("PID")
LAUNCH_JOBKEY_THROTTLEINTERVAL				= c_char_p("ThrottleInterval")
LAUNCH_JOBKEY_LAUNCHONLYONCE				= c_char_p("LaunchOnlyOnce")
LAUNCH_JOBKEY_ABANDONPROCESSGROUP			= c_char_p("AbandonProcessGroup")
LAUNCH_JOBKEY_IGNOREPROCESSGROUPATSHUTDOWN	= c_char_p("IgnoreProcessGroupAtShutdown")
LAUNCH_JOBKEY_POLICIES						= c_char_p("Policies")
LAUNCH_JOBKEY_ENABLETRANSACTIONS			= c_char_p("EnableTransactions")

LAUNCH_JOBPOLICY_DENYCREATINGOTHERJOBS		= c_char_p("DenyCreatingOtherJobs")

LAUNCH_JOBINETDCOMPATIBILITY_WAIT			= c_char_p("Wait")

LAUNCH_JOBKEY_MACH_RESETATCLOSE				= c_char_p("ResetAtClose")
LAUNCH_JOBKEY_MACH_HIDEUNTILCHECKIN			= c_char_p("HideUntilCheckIn")
LAUNCH_JOBKEY_MACH_DRAINMESSAGESONCRASH		= c_char_p("DrainMessagesOnCrash")

LAUNCH_JOBKEY_KEEPALIVE_SUCCESSFULEXIT		= c_char_p("SuccessfulExit")
LAUNCH_JOBKEY_KEEPALIVE_NETWORKSTATE		= c_char_p("NetworkState")
LAUNCH_JOBKEY_KEEPALIVE_PATHSTATE			= c_char_p("PathState")
LAUNCH_JOBKEY_KEEPALIVE_OTHERJOBACTIVE		= c_char_p("OtherJobActive")
LAUNCH_JOBKEY_KEEPALIVE_OTHERJOBENABLED		= c_char_p("OtherJobEnabled")
LAUNCH_JOBKEY_KEEPALIVE_AFTERINITIALDEMAND	= c_char_p("AfterInitialDemand")

LAUNCH_JOBKEY_CAL_MINUTE					= c_char_p("Minute")
LAUNCH_JOBKEY_CAL_HOUR						= c_char_p("Hour")
LAUNCH_JOBKEY_CAL_DAY						= c_char_p("Day")
LAUNCH_JOBKEY_CAL_WEEKDAY					= c_char_p("Weekday")
LAUNCH_JOBKEY_CAL_MONTH						= c_char_p("Month")

LAUNCH_JOBKEY_RESOURCELIMIT_CORE			= c_char_p("Core")
LAUNCH_JOBKEY_RESOURCELIMIT_CPU				= c_char_p("CPU")
LAUNCH_JOBKEY_RESOURCELIMIT_DATA			= c_char_p("Data")
LAUNCH_JOBKEY_RESOURCELIMIT_FSIZE			= c_char_p("FileSize")
LAUNCH_JOBKEY_RESOURCELIMIT_MEMLOCK			= c_char_p("MemoryLock")
LAUNCH_JOBKEY_RESOURCELIMIT_NOFILE			= c_char_p("NumberOfFiles")
LAUNCH_JOBKEY_RESOURCELIMIT_NPROC			= c_char_p("NumberOfProcesses")
LAUNCH_JOBKEY_RESOURCELIMIT_RSS				= c_char_p("ResidentSetSize")
LAUNCH_JOBKEY_RESOURCELIMIT_STACK			= c_char_p("Stack")

LAUNCH_JOBKEY_DISABLED_MACHINETYPE			= c_char_p("MachineType")
LAUNCH_JOBKEY_DISABLED_MODELNAME			= c_char_p("ModelName")

LAUNCH_JOBSOCKETKEY_TYPE					= c_char_p("SockType")
LAUNCH_JOBSOCKETKEY_PASSIVE					= c_char_p("SockPassive")
LAUNCH_JOBSOCKETKEY_BONJOUR					= c_char_p("Bonjour")
LAUNCH_JOBSOCKETKEY_SECUREWITHKEY			= c_char_p("SecureSocketWithKey")
LAUNCH_JOBSOCKETKEY_PATHNAME				= c_char_p("SockPathName")
LAUNCH_JOBSOCKETKEY_PATHMODE				= c_char_p("SockPathMode")
LAUNCH_JOBSOCKETKEY_NODENAME				= c_char_p("SockNodeName")
LAUNCH_JOBSOCKETKEY_SERVICENAME				= c_char_p("SockServiceName")
LAUNCH_JOBSOCKETKEY_FAMILY					= c_char_p("SockFamily")
LAUNCH_JOBSOCKETKEY_PROTOCOL				= c_char_p("SockProtocol")
LAUNCH_JOBSOCKETKEY_MULTICASTGROUP			= c_char_p("MulticastGroup")


(
    LAUNCH_DATA_DICTIONARY,
    LAUNCH_DATA_ARRAY,
    LAUNCH_DATA_FD,
    LAUNCH_DATA_INTEGER,
    LAUNCH_DATA_REAL,
    LAUNCH_DATA_BOOL,
    LAUNCH_DATA_STRING,
    LAUNCH_DATA_OPAQUE,
    LAUNCH_DATA_ERRNO,
    LAUNCH_DATA_MACHPORT
) = range(1, 11)


class LaunchDCheckInError(Exception):
    pass

def get_launchd_socket_fds():
    """Check in with launchd to get socket file descriptors."""

    # Return a dictionary with keys pointing to lists of file descriptors.
    launchd_socket_fds = dict()

    # Callback for dict iterator.
    def add_socket(launch_array, name, context=None):
        if launch_data_get_type(launch_array) != LAUNCH_DATA_ARRAY:
            raise LaunchDCheckInError("Could not get file descriptor array: Type mismatch")
        fds = list()
        for i in range(launch_data_array_get_count(launch_array)):
            data_fd = launch_data_array_get_index(launch_array, i)
            if launch_data_get_type(data_fd) != LAUNCH_DATA_FD:
                raise LaunchDCheckInError("Could not get file descriptor array entry: Type mismatch")
            fds.append(launch_data_get_fd(data_fd))
        launchd_socket_fds[name] = fds

    # Wrap in try/finally to free resources allocated during lookup.
    try:
        # Create a checkin request.
        checkin_request = launch_data_new_string(LAUNCH_KEY_CHECKIN);
        if checkin_request == None:
            raise LaunchDCheckInError("Could not create checkin request")

        # Check the checkin response.
        checkin_response = launch_msg(checkin_request);
        if checkin_response == None:
            raise LaunchDCheckInError("Error checking in")

        if launch_data_get_type(checkin_response) == LAUNCH_DATA_ERRNO:
            errno = launch_data_get_errno(checkin_response)
            raise LaunchDCheckInError("Checkin failed")

        # Get a dictionary of sockets.
        sockets = launch_data_dict_lookup(checkin_response, LAUNCH_JOBKEY_SOCKETS);
        if sockets == None:
            raise LaunchDCheckInError("Could not get socket dictionary from checkin response")

        if launch_data_get_type(sockets) != LAUNCH_DATA_DICTIONARY:
            raise LaunchDCheckInError("Could not get socket dictionary from checkin response: Type mismatch")

        # Iterate over the items with add_socket callback.
        launch_data_dict_iterate(sockets, DICTITCALLBACK(add_socket), None)

        return launchd_socket_fds

    finally:
        if checkin_response is not None:
            launch_data_free(checkin_response)
        if checkin_request is not None:
            launch_data_free(checkin_request)


Munki Tests
===========
Testing key areas of Munki functionality is important as it can help us catch errors that tend to be hard to detect with code review.

The tests found here should focus on functions as a whole (preferably the larger, more complex ones). The general rule is to write tests for any function that is more than 200 lines in length. Once there is sufficient coverage for these functions, then additional functions can be targeted as desired.

Getting started
---------------
To run the test suite, install mock (ships with later versions of unittest, but alas is not on OS X yet.)

    sudo easy_install mock

Then run the following command from the *root* of the project directory:

    python -m unittest discover

This will run all the tests and show the results. If any tests fail, it will throw an exception with the name of the test which failed.


Writing tests
-------------
All unit tests are written using the unittest and mock frameworks. There are many tutorials and books written on how to write unittests, so if you'd like to learn more, *Python Testing Cookbook* by Greg L. Turnquist is a good resource and a good place to start.

The directory structure inside the `tests` directory models the structure of the `code` directory. If a function in munkicommon is being tested, be sure to place the test in the munkicommon directory within the tests directory structure.

For instance, here is the directory structure for all of the tests:

    tests
    ├── README.md
    └── code
        └── client
            └── munkilib
                ├── data_scaffolds.py
                ├── display
                      └── test_munkicommon_unicode.py
                ├── processes    
                      └─── test_munkicommon_isapprunning.py
                


If you want to add tests for the `blockingApplicationsRunning` function, you would name it `test_blockingapplicationsrunning.py` and place it in `tests/code/client/munkilib`. The resulting file structure would look like this:

    tests
    ├── README.md
    └── code
        └── client
            └── munkilib
                ├── appleupdates_test.py
                └── munkicommon
                    ├── data_scaffolds.py
                    ├── test_blockingapplicationsrunning.py
                    ├── test_isapprunning.py
                    └── test_unicode.py


Make sure to always name the tests in a way that clearly describes what is being tested. 

Note the test file must start with `test_` otherwise unittest discover will not find it. For examples of how to mock various types of data, take a look at existing tests and reference *Python Testing Cookbook* by Greg L. Turnquist. Also, feel free to ping @natewalck in #munki on the [MacAdmins Slack](https://macadmins.herokuapp.com/) with any unittest related questions.

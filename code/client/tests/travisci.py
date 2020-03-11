#!/usr/bin/python env
from __future__ import absolute_import, print_function

import subprocess
import sys

print("Checking code against pep8...")
ps = subprocess.Popen(['git', 'diff', 'HEAD^'], stdout=subprocess.PIPE)
tests = subprocess.Popen(['flake8', '--diff', '--ignore=E501'], stdin=ps.stdout, stdout=subprocess.PIPE)
out, err = tests.communicate()

if out:
    print(out)
    print("Time to clean the lint...")
    sys.exit(1)
elif err:
    print("An error occurred!")
    print(err)
    sys.exit(1)
else:
    print("No lint errors, yay!")
    sys.exit(0)

#!/usr/bin/python env

import subprocess

print("Checking code against pep8...")
ps = subprocess.Popen(['git', 'diff', 'HEAD^'], stdout=subprocess.PIPE)
subprocess.call(['flake8', '--diff'], stdin=ps.stdout)

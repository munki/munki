#!/usr/bin/python
"""
munkicommon_test.py

Unit tests for munkicommon functions

"""

import mock
import unittest

import munkicommon

class MunkicommonGetMachineDeployPercentTest(unittest.TestCase):
    def setUp(self):
        """Setup tests with """
        self.managedinstalls = {
        }

        self.machine_facts = {
            'serial_number': 'C02Q32Y5GCN4',
        }

        self.machine_conditions = {}

    def test_deploy_percent_function(self):
        """Make sure percent is correct with a known serial and result"""
        assert munkicommon.get_machine_deploy_percent(
            self.machine_facts['serial_number']
        ) == 31

    @mock.patch('munkicommon.pref', return_value=100)
    def test_deploy_percent_override(self, munkicommon_mock):
        """Mock munkicommon.pref to return a deploy percent setting.
        This should return that setting back rather than generating
        a machine deploy percent (which would be 31 if generated)
        """
        assert munkicommon.get_machine_deploy_percent(
            self.machine_facts['serial_number']
        ) == 100


def main():
    unittest.main(buffer=True)


if __name__ == '__main__':
    main()

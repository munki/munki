# encoding: utf-8
"""Base classes for repo plugins"""

class RepoError(Exception):
    '''Base exception for repo errors'''
    pass


# pylint: disable=too-few-public-methods
class Repo(object):
    '''Abstract base class for repo'''
    def __init__(self, url):
        '''Override in subclasses'''
        pass
# pylint: enable=too-few-public-methods

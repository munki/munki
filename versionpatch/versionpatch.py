# encoding: utf-8

class MunkiLooseVersion(version.LooseVersion):
    '''Subclass version.LooseVersion to compare things like
    "10.6" and "10.6.0" as equal'''

    def __init__(self, vstring=None):
        if vstring is None:
            # treat None like an empty string
            self.parse('')
        if vstring is not None:
            if isinstance(vstring, unicode):
                # unicode string! Why? Oh well...
                # convert to string so version.LooseVersion doesn't choke
                vstring = vstring.encode('UTF-8')
            self.parse(str(vstring))

    def _pad(self, version_list, max_length):
        """Pad a version list by adding extra 0
        components to the end if needed"""
        # copy the version_list so we don't modify it
        cmp_list = list(version_list)
        while len(cmp_list) < max_length:
            cmp_list.append(0)
        return cmp_list

    def _tag(self, version_list):
        # attach a tag to each element so that strings are ordered before numbers
        return [(0 if isinstance(e, StringType) else 1, e) for e in version_list]

    def _normalize(self, version_list, max_length):
    	semantic_version_ordering = True
        if semantic_version_ordering:
            return self._tag(self._pad(version_list, max_length))
        else:
            return self._pad(version_list, max_length)

    def __cmp__(self, other):
        if isinstance(other, StringType):
            other = MunkiLooseVersion(other)

        max_length = max(len(self.version), len(other.version))
        self_cmp_version = self._normalize(self.version, max_length)
        other_cmp_version = self._normalize(other.version, max_length)

        return cmp(self_cmp_version, other_cmp_version)

"""
jobspy.jobboard.exceptions
~~~~~~~~~~~~~~~~~~~

This module contains the set of Scrapers' exceptions.
"""


class LinkedInException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with LinkedIn")


class IndeedException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Indeed")


class ZipRecruiterException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with ZipRecruiter")


class GlassdoorException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Glassdoor")


class GoogleJobsException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Google Jobs")


class BaytException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Bayt")

class NaukriException(Exception):
    def __init__(self,message=None):
        super().__init__(message or "An error occurred with Naukri")

class ProfessionHUException(Exception):
    def __init__(self,message=None):
        super().__init__(message or "An error occurred with ProfessionHU")

class ProfessionHUException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with ProfessionHU")


class PosaoHRException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Posao.hr")


class InfoJobsException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with InfoJobs")


class PracujPLException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Pracuj.pl")


class KarriereATException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Karriere.at")


class ArbetsformedlingenException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Arbetsformedlingen")

class UpworkException(Exception):
    def __init__(self, message=None):
        super().__init__(message or "An error occurred with Upwork")
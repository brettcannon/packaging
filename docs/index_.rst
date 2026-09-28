Index
=====


.. currentmodule:: packaging.index

XXX what the module is about

Usage
-----

.. code-block:: python-console

    >>> from packaging.index import parse_list
    >>> import requests
    >>> response = requests.get("https://pypi.org/simple/")
    >>> project_list = parse_list(response.headers["content-type"], response.text)


XXX manually test the example

Reference
---------

High Level Interface
''''''''''''''''''''

.. autodata:: packaging.index.ACCEPT_JSON_V1

.. autodata:: packaging.index.ACCEPT_HTML

.. autodata:: packaging.index.ACCEPT


Low Level Interface
'''''''''''''''''''

.. autoclass:: packaging.index.RawProjectList

.. autoclass:: packaging.index.RawProjectDetails

.. autoclass:: packaging.index.RawProjectDetailsFile

.. autofunction:: packaging.index.parse_list


Exceptions
''''''''''

.. autoclass:: packaging.index.InvalidContentType
    :members:

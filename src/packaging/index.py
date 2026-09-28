from __future__ import annotations

# Make sure anyone importing this module just for the 'Accept' header values
# don't pay an import penalty for other code.
__lazy_modules__ = ["contextlib", "html.parser", "json", "packaging.utils"]
import contextlib
import html.parser
import json
import typing
from typing import Literal, TypedDict

from . import utils


class InvalidContentType(ValueError):
    """An invalid content type for an index server to respond with.

    Valid content types are encapsulated by :data:`ACCEPT`.
    """

    content_type: str

    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Invalid content type: {content_type}")


ACCEPT_JSON_V1 = "application/vnd.pypi.simple.v1+json"
"""The HTTP ``Accept`` header value for version 1 of the JSON API."""
_ACCEPT_HTML_VALUES = ["application/vnd.pypi.simple.v1+html", "text/html"]
ACCEPT_HTML = f"{_ACCEPT_HTML_VALUES[0]}, {_ACCEPT_HTML_VALUES[1]};q=0.01"
"""The HTTP ``Accept`` header value for the HTML API."""
ACCEPT = ", ".join(
    [
        ACCEPT_JSON_V1,
        f"{_ACCEPT_HTML_VALUES[0]};q=0.02",
        f"{_ACCEPT_HTML_VALUES[1]};q=0.01",
    ]
)
"""The HTTP ``Accept`` header value for all supported response types with JSON prioritized."""  # noqa: E501


# Shared between list and detail responses.
# There is no API version 1.2 as it was introduced by PEP 708 which was rejected.
_RawProjectMeta = TypedDict(
    "_RawProjectMeta", {"api-version": Literal["1.0", "1.1", "1.3", "1.4"]}
)


class RawProjectList(TypedDict):
    """The :class:`~typing.TypedDict` JSON representation of the project list from an index server."""  # noqa: E501

    # 1.0
    meta: _RawProjectMeta
    projects: list[
        dict[Literal["name"], str]  # XXX Type for non-normalized project names?
    ]


# This class only contains keys required across **all** API versions.
class _RawProjectDetailsFileRequired(TypedDict):
    # 1.0
    filename: str
    url: str
    hashes: dict[str, str]


# Since typing.NotRequired isn't available until 3.11, the functional
# TypedDict API doesn't allow subclassing, and there are keys which cannot be
# represented as attribute names, we need to split required and
# optional keys into separate classes that are then combined via
# multiple inheritance.
# Once Python 3.11 is the oldest supported version, the classes should be
# flattened to work with autodoc.
_RawProjectDetailsFileOptional = TypedDict(
    "_RawProjectDetailsFileOptional",
    {
        # 1.0
        "requires-python": str,  # XXX specific type for specifier strings?
        "dist-info-metadata": bool | dict[str, str],  # Deprecated
        "gpg-sig": bool,
        "yanked": bool | str,
        # PEP 714
        "core-metadata": bool | dict[str, str],
        # 1.1
        "size": int,  # Mandatory for 1.1+, but not available for the HTML API.
        "upload-time": str,  # XXX specific type for timestamps?
        # 1.3
        "provenance": str | None,
    },
    total=False,
)


# Once Python 3.11 is the oldest supported version, the classes should be
# flattened to work with autodoc.
class RawProjectDetailsFile(
    _RawProjectDetailsFileRequired, _RawProjectDetailsFileOptional
):
    """The :class:`~typing.TypedDict` JSON representation of the objects contained in the "files" key of :class:`RawProjectDetails`."""  # noqa: E501


class _RawProjectDetailsStatus(TypedDict, total=False):
    status: Literal["active", "archived", "quarantined", "deprecated"]
    reason: str


# This class only contains keys required across **all** API versions.
class _RawProjectDetailsRequired(TypedDict):
    # 1.0
    meta: _RawProjectMeta
    name: str  # XXX Or utils.NormalizedName?
    files: list[RawProjectDetailsFile]


_RawProjectDetailsOptional = TypedDict(
    "_RawProjectDetailsOptional",
    {
        # 1.1
        "versions": list[str],  # XXX Type for version strings?
        # 1.4
        "project-status": _RawProjectDetailsStatus,
    },
    total=False,
)


# Once Python 3.11 is the oldest supported version, the classes should be
# flattened to work with autodoc.
class RawProjectDetails(_RawProjectDetailsRequired, _RawProjectDetailsOptional):
    """The :class:`~typing.TypedDict` JSON representation of the project details from an index server.

    Due to supporting all possible API versions, some keys which are considered
    required in API versions post-1.0 are considered optional.
    """  # noqa: E501


class _RawProjectListHTMLParser(html.parser.HTMLParser):
    names: list[str]
    parsing_anchor: bool
    api_version: str = "1.0"

    def __init__(self) -> None:
        super().__init__()
        self.names = []
        self.parsing_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.parsing_anchor = True
        elif tag == "meta" and attrs:
            attrs_dict = dict(attrs)
            if (
                "content" in attrs_dict
                and attrs_dict["content"] is not None
                and attrs_dict.get("name") == "pypi:repository-version"
            ):
                self.api_version = attrs_dict["content"]

    def handle_data(self, data: str) -> None:
        if self.parsing_anchor:
            self.names.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.parsing_anchor = False


def parse_list(content_type: str, data: str) -> RawProjectList:
    """Parse the project list based on the specified content type.

    If the content type is :data:`ACCEPT_JSON_V1` then the data string is
    deserialized as JSON. If the content type is from :data:`ACCEPT_HTML` then
    the HTML is parsed and the data is converted to the appropriate JSON
    representation. All other content types raise :class:`InvalidContentType`.

    Regardless of content type, all data is normalized by storing the canonical
    project names. No other normalization or validation is performed.
    """
    content_type = content_type.lower()
    project_list: RawProjectList
    if content_type == ACCEPT_JSON_V1:
        project_list = json.loads(data)
    # Watch out for content types that specify the encoding!
    elif any(content_type.startswith(mime_type) for mime_type in _ACCEPT_HTML_VALUES):
        with contextlib.closing(_RawProjectListHTMLParser()) as parser:
            parser.feed(data)
        meta = typing.cast("_RawProjectMeta", {"api-version": parser.api_version})
        project_list = {
            "meta": meta,
            "projects": [{"name": name} for name in parser.names],
        }
    else:
        raise InvalidContentType(content_type)

    for project in project_list["projects"]:
        project["name"] = utils.canonicalize_name(project["name"])

    return project_list


# XXX parse_details(content_type: str, data: str) -> RawProjectDetails
# No 'size' data, so statically declare API version 1.0 with bonus details,
# or be incorrect by leaving off the size? Or use a dummy value like -1?

# API version
# url                                  https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=The%20href%20attribute%20MUST%20be%20a%20URL%20that%20links%20to%20the%20location%20of%20the%20file%20for%20download
# filename                             https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=the%20text%20of%20the%20anchor%20tag%20MUST%20match%20the%20final%20path%20component%20(the%20filename)%20of%20the%20URL.
# hash                                 https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=Each%20file%20URL%20SHOULD%20include%20a%20hash%20in%20the%20form%20of%20a%20URL%20fragment%20with%20the%20following%20syntax%3A%20%23%3Chashname%3E%3D%3Chashvalue%3E
# core-metadata                        https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20a%20data%2Dcore,attribute%E2%80%99s%20value%20if%20a%20hash%20is%20unavailable.
# dist-info-metadata                   https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20a%20data%2Ddist%2Dinfo%2Dmetadata%20attribute%20on%20a%20file%20link.
# gpg-sig                              https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20a%20data%2Dgpg%2Dsig%20attribute%20on%20a%20file%20link%20with%20a%20value%20of%20either%20true%20or%20false%20to%20indicate%20whether%20or%20not%20there%20is%20a%20GPG%20signature.
# requires-python (needs unescaping!)  https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20a%20data%2Drequires,%26lt%3B%20and%20%26gt%3B%2C%20respectively.
# yanked                               https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=The%20data%2Dyanked%20attribute%20may%20have%20no%20value%2C%20or%20may%20have%20an%20arbitrary%20string%20as%20a%20value.%20The%20presence%20of%20a%20data%2Dyanked%20attribute%20SHOULD%20be%20interpreted%20as%20indicating%20that%20the%20file%20pointed%20to%20by%20this%20particular%20link%20has%20been%20%E2%80%9CYanked%E2%80%9D
# provenance                           https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20a%20data%2Dprovenance%20attribute%20on%20a%20file%20link.%20The%20value%20of%20this%20attribute%20MUST%20be%20a%20fully%20qualified%20URL
# status                               https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20pypi,an%20arbitrary%20string%20if%20present.

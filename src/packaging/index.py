from __future__ import annotations

# Make sure anyone importing this module just for the 'Accept' header values
# doesn't pay an unnecessary import penalty for other code.
__lazy_modules__ = {
    "contextlib",
    "html",
    "json",
    "urllib.parse",
    f"{__spec__.parent}.utils",
}
import contextlib
import html
import html.parser  # HTMLParser used as a base class.
import json
import typing  # The `from ... import` forces an eager import.
import urllib.parse
from typing import Literal, TypedDict  # TypedDict is used as a base class.

from . import utils


class IndexServerException(Exception):
    """Base exception for all exceptions related to :mod:`packaging.index`."""


class InvalidContentType(ValueError, IndexServerException):
    """An invalid content type for an index server to respond with.

    Valid content types are encapsulated by :data:`ACCEPT`.
    """

    content_type: str

    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Invalid content type: {content_type}")


class InvalidHTMLAttributeValue(ValueError, IndexServerException):
    """Invalid data returned from an index server serving HTML data."""

    attr: str
    value: str

    def __init__(self, attr: str, value: object) -> None:
        self.attr = attr
        self.value = repr(value)
        super().__init__(f"invalid value for HTML attribute {self.attr}: {self.value}")


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
    """The :class:`~typing.TypedDict` JSON representation of the objects contained in the "files" key of :class:`RawProjectDetails`.

    Do note that the 'size' key is not considered required; it doesn't exist in
    API version 1.0 nor is it supported by the HTML API.
    """  # noqa: E501


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


class _RawProjectMetaHTMLParser(html.parser.HTMLParser):
    api_version: str = "1.0"

    def _handle_meta(self, attrs: dict[str, str | None]) -> None:
        if (
            "content" in attrs
            and attrs["content"] is not None
            and attrs.get("name") == "pypi:repository-version"
        ):
            self.api_version = attrs["content"]


class _RawProjectListHTMLParser(_RawProjectMetaHTMLParser):
    names: list[str]
    parsing_anchor: bool

    def __init__(self) -> None:
        super().__init__()
        self.names = []
        self.parsing_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.parsing_anchor = True
        elif tag == "meta" and attrs:
            attrs_dict = dict(attrs)
            self._handle_meta(attrs_dict)

    def handle_data(self, data: str) -> None:
        if self.parsing_anchor:
            self.names.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.parsing_anchor = False


def parse_list(content_type: str, data: str) -> RawProjectList:
    """Parse the project list based on the specified content type.

    If the content type is :data:`ACCEPT_JSON_V1` then the data string is
    deserialized as JSON. If the content type is from :data:`ACCEPT_HTML` then
    the HTML is parsed and the data is converted to the appropriate JSON
    representation. All other content types raise :exc:`InvalidContentType`.

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


class _RawProjectDetailsHTMLParser(_RawProjectMetaHTMLParser):
    files: list[RawProjectDetailsFile]
    current_file: dict[str, typing.Any]

    def __init__(self) -> None:
        super().__init__()
        self.files = []
        self.current_file = self._new_file()

    def _new_file(self) -> dict[str, typing.Any]:
        return {"hashes": {}}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "meta"}:
            return

        attrs_dict = dict(attrs)

        if tag == "meta":
            self._handle_meta(attrs_dict)
        else:  # "a"
            self.current_file = self._new_file()
            for name, value in attrs_dict.items():
                try:
                    method = getattr(self, f"_handle_{name.replace('-', '_')}")
                except AttributeError:  # noqa: PERF203
                    continue
                else:
                    method(value)

    def _handle_href(self, value: str | None) -> None:
        if value:
            self.current_file["url"] = value
            if fragment := urllib.parse.urlsplit(value).fragment:
                if fragment.count("=") != 1:
                    raise InvalidHTMLAttributeValue("href", value)
                hash_algo, _, hash_value = fragment.partition("=")
                self.current_file["hashes"][hash_algo] = hash_value

    def _process_metadata(self, key: str, value: str | None) -> None:
        result: dict[str, str] | bool = True
        if value:
            if "=" in value:
                hash_algo, _, hash_value = value.partition("=")
                if not (hash_algo and hash_value):
                    raise InvalidHTMLAttributeValue(f"data-{key}", value)
                result = {hash_algo: hash_value}
            elif value != "true":
                raise InvalidHTMLAttributeValue(f"data-{key}", value)
        self.current_file[key] = result

    def _handle_data_core_metadata(self, value: str | None) -> None:
        self._process_metadata("core-metadata", value)

    def _handle_data_dist_info_metadata(self, value: str | None) -> None:
        self._process_metadata("dist-info-metadata", value)

    def _handle_data_gpg_sig(self, value: str | None) -> None:
        match value:
            case "true":
                has_sig = True
            case "false":
                has_sig = False
            case _:
                raise InvalidHTMLAttributeValue("data-gpg-sig", value)
        self.current_file["gpg-sig"] = has_sig

    def _handle_data_requires_python(self, value: str | None) -> None:
        if value is None:
            raise InvalidHTMLAttributeValue("data-requires-python", value)
        self.current_file["requires-python"] = html.unescape(value)

    def _handle_data_yanked(self, value: str | None) -> None:
        self.current_file["yanked"] = True if value is None else value

    def _handle_data_provenance(self, value: str | None) -> None:
        if value is None:
            raise InvalidHTMLAttributeValue("data-provenance", value)
        self.current_file["provenance"] = value

    def handle_data(self, data: str) -> None:
        self.current_file["filename"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.files.append(typing.cast("RawProjectDetailsFile", self.current_file))
            self.current_file = self._new_file()


@typing.overload
def parse_details(
    content_type: str,
    data: str,
    *,
    name: str,
    request_url: str | None = None,
) -> RawProjectDetails: ...


@typing.overload
def parse_details(
    content_type: str,
    data: str,
    *,
    name: str | None = None,
    request_url: str,
) -> RawProjectDetails: ...


def parse_details(
    content_type: str,
    data: str,
    *,
    name: str | None = None,
    request_url: str | None = None,
) -> RawProjectDetails:
    """Parse the project details response from an index server based on *content_type*.

    Either *name* or *request_url* must be provided in order to have the
    project name for an HTML response. If *request_url* is provided then the
    last portion of the URL is used for the project name.

    If the content type is :data:`ACCEPT_JSON_V1` then the data string is
    deserialized as JSON. If the content type is from :data:`ACCEPT_HTML` then
    the HTML is parsed and the data is converted to the appropriate JSON
    representation. All other content types raise :exc:`InvalidContentType`.

    When invalid data is detected while parsing HTML,
    :exc:`InvalidHTMLAttributeValue` is raised. Attempts are made, though, to
    accept non-standard but unambiguous results (.e.g, the data-core-metadata
    attribute being specified with no value).

    Some normalization is done regardless of the content type. The 'name' key
    is made canonical. If *request_url* -- which is expected to be the URL used
    to make the request -- is provided then the 'filename' key is used to make
    sure the URL provided is absolute. If either the 'core-metadata' or
    'dist-info-metadata' key is set and the other is not then the unset key is
    filled with the other's value. Any dictionaries containing hash algorithm
    names as keys will have those name lowercased.
    """
    if name is None and request_url is None:
        raise TypeError("expected either *name* or *request_url* to be provided")
    content_type = content_type.lower()
    project_details: RawProjectDetails
    if content_type == ACCEPT_JSON_V1:
        project_details = json.loads(data)
    # Watch out for content types that specify the encoding!
    elif any(content_type.startswith(mime_type) for mime_type in _ACCEPT_HTML_VALUES):
        with contextlib.closing(_RawProjectDetailsHTMLParser()) as parser:
            parser.feed(data)
        meta = typing.cast("_RawProjectMeta", {"api-version": parser.api_version})

        if name:
            project_name = name
        else:
            path = urllib.parse.urlsplit(request_url).path
            project_name = path.removesuffix("/").rpartition("/")[-1]

        project_details = {
            "meta": meta,
            "name": utils.canonicalize_name(project_name),
            "files": parser.files,
        }
        # XXX status

    project_details["name"] = utils.canonicalize_name(project_details["name"])
    for file in project_details["files"]:
        for keys_with_hash_dicts in ["core-metadata", "dist-info-metadata", "hashes"]:
            hashes = file.get(keys_with_hash_dicts, {})
            if not isinstance(hashes, dict):
                continue
            for key in list(hashes.keys()):
                value = hashes.pop(key)
                hashes[key.lower()] = value

        if "core-metadata" in file and "dist-info-metadata" not in file:
            file["dist-info-metadata"] = file["core-metadata"]
        elif "dist-info-metadata" in file and "core-metadata" not in file:
            file["core-metadata"] = file["dist-info-metadata"]
        if request_url and "url" in file:
            file["url"] = urllib.parse.urljoin(request_url, file["url"])

    return project_details


# pypi:project-status / pypi:project-status-reason  https://packaging.python.org/en/latest/specifications/simple-repository-api/#project-detail:~:text=A%20repository%20MAY%20include%20pypi,an%20arbitrary%20string%20if%20present.

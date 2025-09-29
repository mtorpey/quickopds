import argparse
import os
import xml.etree.ElementTree as ET

from datetime import datetime, UTC
from html.parser import HTMLParser
from importlib import resources
from lxml import etree
from pathlib import Path
from pypdf import PdfReader
from urllib.parse import quote, urlparse
from zipfile import ZipFile

# Filename constants
FEED_FILENAME = "index.xml"
STYLE_FILENAME = "style.xsl"

# Constants for use in the dict we build up, for conversion to xml
NAME = "NAME"
CHILDREN = "CHILDREN"
NAMESPACE = "NAMESPACE"

# URIs for the opds links
ACQUISITION = "http://opds-spec.org/acquisition"
IMAGE = "http://opds-spec.org/image"
# TODO: /image/thumbnail

# Attributes to go into each opds link, based on the filename ending
FORMATS = {
    "_advanced.epub": {
        "title": "Advanced epub",
        CHILDREN: [
            "An advanced format that uses the latest technology not yet fully supported by most ereaders"
        ],
        "type": "application/epub+zip",
        "rel": ACQUISITION,
    },
    ".kepub.epub": {
        "title": "kepub",
        CHILDREN: ["Kobo devices and apps"],
        "type": "application/kepub+zip",
        "rel": ACQUISITION,
    },
    ".epub": {
        "title": "Compatible epub",
        CHILDREN: ["All devices and apps except Kindles and Kobos"],
        "type": "application/epub+zip",
        "rel": ACQUISITION,
    },
    ".azw3": {
        "title": "azw3",
        CHILDREN: ["Kindle devices and apps"],
        "type": "application/x-mobipocket-ebook",
        "rel": ACQUISITION,
    },
    ".mobi": {
        "title": "mobi",
        CHILDREN: ["Old format still supported by most devices"],
        "type": "application/x-mobipocket-ebook",
        "rel": ACQUISITION,
    },
    "_cropped.pdf": {
        "title": "Cropped pdf",
        CHILDREN: ["Fixed page layout cropped tightly to content"],
        "type": "application/pdf",
        "rel": ACQUISITION,
    },
    ".pdf": {
        "title": "pdf",
        CHILDREN: ["Fixed page layout"],
        "type": "application/pdf",
        "rel": ACQUISITION,
    },
    ".html": {
        "title": "html",
        CHILDREN: ["Read directly in the browser"],
        "type": "text/html",
        "rel": ACQUISITION,
    },
    ".txt": {
        "title": "txt",
        CHILDREN: ["Plain text with no formatting"],
        "type": "text/plain",
        "rel": ACQUISITION,
    },
    ".jpg": {
        "type": "image/jpeg",
        "rel": IMAGE,
    },
    ".png": {
        "type": "image/png",
        "rel": IMAGE,
    },
    ".gif": {
        "type": "image/gif",
        "rel": IMAGE,
    },
}
FORMATS[".htm"] = FORMATS[".html"]
FORMATS[".jpeg"] = FORMATS[".jpg"]
FORMATS[""] = {"type": "unknown"}


def dict_to_xml(d: dict) -> etree.Element:
    """Convert the dict we built up into the final xml document."""
    nsmap = d[NAMESPACE] if NAMESPACE in d else {}
    attribs = {k: str(v) for k, v in d.items() if k not in [NAME, CHILDREN, NAMESPACE]}
    element = etree.Element(d[NAME], attrib=attribs, nsmap=nsmap)
    if CHILDREN in d:
        for child in d[CHILDREN]:
            if type(child) is dict:
                element.append(dict_to_xml(child))
            else:
                assert type(child) is str
                element.text = child
    return element


def force_trailing_slash(path: str):
    if not path.endswith("/"):
        return path + "/"
    return path


def text_item(name, text):
    """Make an xml entity with text contents and no attributes."""
    return {
        NAME: name,
        CHILDREN: [text],
    }


def timestamp_now():
    """Get the UTC ISO-8601 timestamp for the current time."""
    return (
        datetime.now(UTC)
        .replace(microsecond=0)  # floor to nearest second
        .isoformat()
        .replace("+00:00", "Z")
    )


def timestamp(f):
    """Get the UTC ISO-8601 timestamp for the given path's last update time."""
    return (
        datetime.fromtimestamp(f.stat().st_mtime, UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


class HTMLFilter(HTMLParser):
    text = ""

    def handle_data(self, data):
        self.text += data


def filter_html(text):
    """Given a string, attempt to sensibly remove html formatting and return plain text."""
    if "<" in text or "&lt;" in text:
        f = HTMLFilter()
        f.feed(text)
        return f.text
    return text


def get_pdf_metadata(path):
    """Get appropriate metadata from the pdf at the given filepath."""
    reader = PdfReader(path)
    info = reader.metadata

    meta = dict()
    for key, tag in [("/Author", "author"), ("/Title", "title")]:
        if key in info.keys():
            meta[tag] = str(info[key])

    return meta


def get_epub_metadata(path):
    """Get appropriate metadata from the epub at the given filepath."""
    meta = dict()

    with ZipFile(path, "r") as z:
        # Find the opf path
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = container.find(
            ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
        )
        opf_path = rootfile.get("full-path")

        # Parse the opf file
        opf = ET.fromstring(z.read(opf_path))

        # OPF uses namespaces, so define them
        NS = {
            "dc": "http://purl.org/dc/elements/1.1/",
            "opf": "http://www.idpf.org/2007/opf",
        }

        # Extract the metadata we want
        for key, tag in [
            ("title", "title"),
            ("creator", "author"),
            ("description", "content"),
        ]:
            el = opf.find(f".//dc:{key}", namespaces=NS)
            if el is not None and el.text:
                meta[tag] = el.text.strip()

    return meta


def make_tree(directory: Path, url: str, feed_title: str, feed_author: str):
    """Look through the given directory and return a dict representing an opds feed for its contents."""

    # Normalise url
    url = force_trailing_slash(url)

    # Dictionaries holding information for each book
    entries = dict()
    updated = dict()
    titles = dict()
    authors = dict()
    contents = dict()

    # Explore the directory looking for book files
    for f in sorted(directory.iterdir()):
        if f.is_file():
            # Get the attributes for this file type
            for ending, attributes in FORMATS.items():
                if f.name.endswith(ending):
                    # Files apply to the same book if they have the same stem
                    stem = f.name[: -len(ending)]
                    break

            # Skip if not a recognised file
            if ending == "":
                print("Ignored file", f.name)
                continue

            # New book? Add an entry
            if stem not in entries:
                entries[stem] = {
                    NAME: "entry",
                    CHILDREN: [text_item("id", url + quote(stem))],
                }
                updated[stem] = ""
                titles[stem] = stem
                authors[stem] = "Unknown"
                contents[stem] = ""

            # Add this file as a link under the appropriate book
            entries[stem][CHILDREN].append(
                {
                    NAME: "link",
                    "href": url + quote(f.name),
                }
                | attributes
            )

            # Keep the latest modified time for this book
            updated[stem] = max(updated[stem], timestamp(f))

            # Extract book metadata from the file if possible
            if f.name.lower().endswith(".pdf"):
                meta = get_pdf_metadata(f.resolve())
            elif f.name.lower().endswith(".epub"):
                meta = get_epub_metadata(f.resolve())
            else:
                meta = dict()
            if "title" in meta:
                titles[stem] = meta["title"]
            if "author" in meta:
                authors[stem] = meta["author"]
            if "content" in meta:
                contents[stem] = meta["content"]

    # Put the final metadata into each book entry
    for stem in updated:
        entries[stem][CHILDREN].insert(1, text_item("updated", updated[stem]))
    for stem in titles:
        entries[stem][CHILDREN].insert(2, text_item("title", titles[stem]))
    for stem in authors:
        entries[stem][CHILDREN].insert(
            3, {NAME: "author", CHILDREN: [text_item("name", authors[stem])]}
        )
    for stem in contents:
        entries[stem][CHILDREN].insert(
            4,
            {NAME: "content", "type": "text", CHILDREN: [filter_html(contents[stem])]},
        )

    # Add metadata for the whole feed
    children = [
        text_item("title", feed_title),
        text_item("id", url + FEED_FILENAME),
        text_item("updated", timestamp_now()),
        {NAME: "author", CHILDREN: [text_item("name", feed_author)]},
        {NAME: "link", "rel": "self", "type": "application/atom+xml", "href": url},
    ] + list(
        entries.values()
    )  # add the book entries
    return {
        NAME: "feed",
        NAMESPACE: {
            None: "http://www.w3.org/2005/Atom",
            "opds": "http://opds-spec.org/2010/catalog",
            "dcterms": "http://purl.org/dc/terms/",
        },
        CHILDREN: children,
    }


def generate_xml(tree: dict, outfile: Path):
    root = dict_to_xml(tree)
    tree = etree.ElementTree(root)

    # <?xml-stylesheet type="text/xsl" href="style.xsl"?>
    xslt_line = etree.ProcessingInstruction(
        "xml-stylesheet", f'type="text/xsl" href="{STYLE_FILENAME}"'
    )
    tree.getroot().addprevious(xslt_line)

    tree.write(str(outfile), encoding="utf-8", xml_declaration=True, pretty_print=True)
    print("Wrote file to", outfile)


def copy_file(source, target):
    with open(source, "r") as f:
        content = f.read()

    with open(target, "w") as f:
        f.write(content)
        print("Wrote file to", target)


def test_xsl(directory: str):
    # Find files
    feed_path = directory + FEED_FILENAME
    xsl_path = directory + STYLE_FILENAME

    # Parse files
    xml = etree.parse(feed_path)
    xsl = etree.parse(STYLE_FILENAME)

    # Construct html form
    transform = etree.XSLT(xsl)
    result = transform(xml)
    return str(result)


def main():
    # Handle arguments
    parser = argparse.ArgumentParser(
        prog="quickopds",
        description="Statically generate an opds ebook feed for a directory",
    )
    parser.add_argument(
        "directory",
        default=".",
        help="path to the local directory containing the ebooks (default current working directory)",
        nargs="?",
        type=force_trailing_slash,
    )
    parser.add_argument(
        "--url",
        default="https://example.com/ebooks",
        help="url where the feed will be hosted (default https://example.com/ebooks)",
        type=force_trailing_slash,
    )
    parser.add_argument(
        "--title",
        default="My ebook catalog",
        help="title for the feed (default 'My ebook catalog')",
    )
    parser.add_argument(
        "--author",
        default="quickopds",
        help="named owner of the feed (default 'quickopds')",
    )
    args = parser.parse_args()

    # Normalise paths
    directory_path = args.directory
    directory_url = args.url
    feed_title = args.title
    feed_author = args.author

    # Compute path to feed file
    feed_path = directory_path + FEED_FILENAME

    # Create feed file
    tree_dict = make_tree(Path(directory_path), directory_url, feed_title, feed_author)
    generate_xml(tree_dict, feed_path)

    # Copy xsl style file
    style_file = resources.files("quickopds").joinpath(STYLE_FILENAME)
    copy_file(style_file, directory_path + STYLE_FILENAME)

    # Test xsl transformation
    html = test_xsl(directory_path)
    print(f"xsl transform succeeded with {len(html)} characters")

if __name__ == "__main__":
    main()

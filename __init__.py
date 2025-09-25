from datetime import datetime, UTC
from html.parser import HTMLParser
from lxml import etree
from pathlib import Path
from pypdf import PdfReader
from urllib.parse import quote

import xml.etree.ElementTree as ET
import zipfile


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


def text_item(name, text):
    """Make an xml entity with text contents and no attributes."""
    return {
        NAME: name,
        CHILDREN: [text],
    }


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


def get_pdf_metadata(name):
    """Get appropriate metadata from the pdf at the given filename."""
    reader = PdfReader(name)
    info = reader.metadata

    meta = dict()
    for key, tag in [("/Author", "author"), ("/Title", "title")]:
        if key in info.keys():
            meta[tag] = str(info[key])

    return meta


def get_epub_metadata(name):
    """Get appropriate metadata from the epub at the given filename."""
    meta = dict()

    with zipfile.ZipFile(name, "r") as z:
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


def make_tree(directory: Path, url: str):
    """Look through the given directory and return a dict representing an opds feed for its contents."""

    # Dictionaries holding information for each book
    entries = dict()
    updated = dict()
    titles = dict()
    authors = dict()
    contents = dict()
    latest = ""

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
                print("Unknown filetype", f.name)
                continue

            # New book? Add an entry
            if stem not in entries:
                entries[stem] = {
                    NAME: "entry",
                    # TODO: title, author, content
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

            # Keep the latest modified time for this book and for the whole directory
            updated[stem] = max(updated[stem], timestamp(f))
            latest = max(latest, timestamp(f))

            # Extract book metadata from the file if possible
            if f.name.lower().endswith(".pdf"):
                meta = get_pdf_metadata(f.name)
            elif f.name.lower().endswith(".epub"):
                meta = get_epub_metadata(f.name)
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
        text_item("title", "Michael Young's ebooks"),
        text_item("id", url + FEED_FILENAME),
        text_item("updated", latest),
        {NAME: "author", CHILDREN: [text_item("name", "Michael Young")]},
        {NAME: "link", "rel": "self", "type": "application/atom+xml", "href": url},
    ] + list(entries.values()) # add the book entries
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


FEED_FILENAME = "index.xml"
STYLE_FILENAME = "style.xsl"

FEED_DIRECTORY_PATH = "." # TODO
FEED_DIRECTORY_URL = "https://myoung.uk/ebooks/"

tree_dict = make_tree(Path(FEED_DIRECTORY_PATH))
feed_path = Path(FEED_DIRECTORY_PATH + "/" + FEED_FILENAME)
generate_xml(tree_dict, DIRECTORY_URL, feed_path)

xml = etree.parse(feed_path)
xsl = etree.parse(STYLE_FILENAME) # TODO: copy style file to directory
transform = etree.XSLT(xsl)
result = transform(xml)

print("STYLED VERSION")
print(str(result))

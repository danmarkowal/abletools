from typing import Callable, Dict, List

from lxml import etree


class XMLConversionError(Exception):
    pass


class XMLConverter:
    """A class used to convert one XML representation to another."""

    def convert(self, root: etree.Element) -> etree.Element:
        raise NotImplementedError(
            "Converter subclasses must implement the convert method.")


def copy_tag(source: etree.Element, target: etree.Element, tag: str):
    target.append(find_not_null(source, tag))


def map_tag(source: etree.Element, target: etree.Element, source_tag: str, target_tag: str):
    """Copies a tag 'source_tag' from a source element to a target element, mapping the tag's name to 'target_tag' if it exists."""
    element = find_not_null(source, source_tag)
    element.tag = target_tag
    target.append(element)


def copy_tags(source: etree.Element, target: etree.Element, tags: List[str]):
    for tag in tags:
        copy_tag(source, target, tag)


def map_tags(source: etree.Element, target: etree.Element, tag_map: Dict[str, str]):
    for source_tag, target_tag in tag_map.items():
        map_tag(source, target, source_tag, target_tag)


def make_tagged_value(tag: str, value: str) -> etree.Element:
    """Helper method to create an XML element with a "Value" attribute.

    The tag is used for the element tag and the value is set as the "Value" attribute.
    """
    element = etree.Element(tag)
    element.set("Value", value)
    return element


def find_not_null(element: etree.Element, tag: str) -> etree.Element:
    """Finds a child tag. Raises XMLConversionError if it is missing or None."""
    found = element.find(tag)
    if found is None:
        # Fall back to a default structured message if a specific one isn't given
        raise XMLConversionError(
            f"Required tag '{tag}' was not found under '{element.tag}'.")
    return found


def get_tagged_value[T](element: etree.Element, tag: str, cast: Callable[[str], T] = str) -> T:
    """Finds a child tag and retrieves its "Value" attribute.

    Raises XMLConversionError if the tag is missing, None, or if the "Value" attribute is missing.
    """
    found = find_not_null(element, tag)
    value = found.get("Value")
    if value is None:
        raise XMLConversionError(
            f"Tag '{tag}' under '{element.tag}' does not have a 'Value' attribute.")

    try:
        return cast(value)
    except ValueError as e:
        raise XMLConversionError(f"Failed to cast tagged value. Error: {e}")


def format_long_text_element(element: etree.Element, chunk_size: int = 80):
    if element.text is None:
        return

    # 1. Strip any existing whitespace from the hex data
    raw_text = "".join(element.text.split())

    # 2. Break the string into chunks
    chunks = [raw_text[i:i+chunk_size]
              for i in range(0, len(raw_text), chunk_size)]

    # 3. Join chunks with a newline, starting on a fresh line
    element.text = "\n" + "\n".join(chunks)

import gzip


from argparse import Namespace
import time
from lxml import etree
from pathlib import Path


from abletools.plugins.vst_converter import Vst3Converter, VstConversionContext
from abletools.plugins.vst_id_converter import get_default_uid_cache_path
from abletools.utils.xml_converter import XMLConversionError
from abletools.utils import project_utils


ABLETON_LIVE_PROJECT_SUFFIX = ".als"


def handle_command(args: Namespace):
    # 1. Read and decode project file (gzip)
    # 2. Check schema version
    # 3. Find all <VstPluginInfo> tags
    # 4. Convert VST2 plugin info to VST3 plugin info
    # 5. Write VST3 plugin info back to the XML tree
    # 6. Gzip XML file and write it to a new file (do not overwrite old project file)
    root = etree.fromstring(project_utils.read_project_file(args.projfile))

    ctx = VstConversionContext(get_default_uid_cache_path())
    converter = Vst3Converter(ctx)

    for vst2_info in root.findall(".//VstPluginInfo"):
        try:
            vst3_info = converter.convert(vst2_info)
            parent = vst2_info.getparent()
            if parent is not None:
                parent.replace(vst2_info, vst3_info)
        except XMLConversionError as e:
            print(f"Error converting plugin: {e}")

    proj_path = Path(args.projfile)
    # The new project file name is the same as the old one but with " (Converted YYYY-MM-DD HH-MM-SS)" appended before the file extension
    timestamp = time.strftime("%Y-%m-%d %H-%M-%S")
    new_proj_name = proj_path.with_name(
        f"{proj_path.stem} (Converted {timestamp}){ABLETON_LIVE_PROJECT_SUFFIX}")
    print(f"Writing converted project to: '{new_proj_name}'.")

    with open(new_proj_name, "wb") as f:
        # Fix indentation
        etree.indent(root, "\t")

        new_proj_file = etree.tostring(
            root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        f.write(gzip.compress(new_proj_file))
